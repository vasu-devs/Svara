"""Adapt Whisper large-v3-turbo to one voice, fast, from the onboarding takes.

Run (needs the training venv, see LINUX.md):

    .venv-train/bin/python -m mywhisper.voice_adapt            # train, convert, A/B
    .venv-train/bin/python -m mywhisper.voice_adapt --apply    # …and switch Svara to it if it wins

Why it is fast. Turbo has 32 encoder layers and 4 decoder layers. The bottom
encoder layers model generic acoustics, the top ones and the decoder are where
an accent and a vocabulary live. So the bottom `--freeze` layers run ONCE per
clip and their output is cached on the GPU; training then only ever runs the
top encoder layers and the decoder, with LoRA adapters on their attention.
On an 8 GB laptop GPU a run over ~100 clips takes well under a minute.

Why it is safe. Every fifth line is held out and never trained on. The
adapted model is merged, converted to the faster-whisper format Svara loads,
and scored against the stock model on those held-out takes with the same
decoder settings. It is only kept if it is better by at least `--margin`
points of word error rate; otherwise it is deleted and nothing changes.

Reads  <root>/lines.jsonl + clips/ (mywhisper.voice_session)
Writes ~/.local/share/svara/models/turbo-voice-<date>/ and <root>/adapt.json
"""

import argparse
import json
import os
import shutil
import sys
import time
import urllib.request
import wave
from pathlib import Path

import numpy as np

from .bench import wer

BASE_HF = "openai/whisper-large-v3-turbo"          # trainable weights
BASE_CT2 = "dropbox-dash/faster-whisper-large-v3-turbo"   # what Svara runs today
SR = 16000


def data_root() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "svara"


def load_takes(root: Path) -> list[dict]:
    takes = []
    for raw in (root / "lines.jsonl").read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        rec = json.loads(raw)
        path = root / rec["wav"]
        if not path.exists():
            continue
        with wave.open(str(path)) as w:
            rec["audio"] = (np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
                            .astype(np.float32) / 32768)
        takes.append(rec)
    return takes


def free_gpu() -> None:
    """Ask Ollama to drop whatever it holds (the polish LLM takes ~5 GB).
    Svara warms it again on the next dictation."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/ps", timeout=2) as r:
            models = [m["name"] for m in json.load(r).get("models", [])]
        for name in models:
            req = urllib.request.Request(
                "http://127.0.0.1:11434/api/generate",
                data=json.dumps({"model": name, "keep_alive": 0}).encode(),
                headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10).read()
        if models:
            print(f"freed the GPU: unloaded {', '.join(models)} from Ollama")
    except OSError:
        pass   # no Ollama: nothing to free


def train(train_takes, out_hf: Path, freeze: int, epochs: int, lr: float,
          rank: int, batch: int) -> float:
    import torch
    import torch.nn.functional as F
    from peft import LoraConfig, get_peft_model
    from torch.utils.checkpoint import checkpoint
    from transformers import WhisperForConditionalGeneration, WhisperProcessor

    dev = "cuda"
    dtype = torch.bfloat16
    proc = WhisperProcessor.from_pretrained(BASE_HF)
    proc.tokenizer.set_prefix_tokens(language="english", task="transcribe")
    model = WhisperForConditionalGeneration.from_pretrained(
        BASE_HF, torch_dtype=dtype, attn_implementation="sdpa").to(dev)
    model.eval()
    enc = model.model.encoder
    n_enc = len(enc.layers)
    freeze = max(0, min(freeze, n_enc - 1))

    def layer_out(layer, x):
        y = layer(x, attention_mask=None)
        return y[0] if isinstance(y, tuple) else y

    # 1. the frozen bottom of the encoder, once per clip
    t0 = time.perf_counter()
    cached, labels = [], []
    with torch.no_grad():
        for i in range(0, len(train_takes), 8):
            chunk = train_takes[i:i + 8]
            feats = proc.feature_extractor([t["audio"] for t in chunk], sampling_rate=SR,
                                           return_tensors="pt").input_features.to(dev, dtype)
            x = F.gelu(enc.conv1(feats))
            x = F.gelu(enc.conv2(x)).permute(0, 2, 1)
            x = x + enc.embed_positions.weight[:x.shape[1]]
            for layer in enc.layers[:freeze]:
                x = layer_out(layer, x)
            cached.extend(x.unbind(0))
        for t in train_takes:
            labels.append(proc.tokenizer(t["text"]).input_ids)
    cache_s = time.perf_counter() - t0

    # 2. LoRA on the attention of the top encoder layers and of the decoder
    top = "|".join(str(i) for i in range(freeze, n_enc))
    target = (rf".*encoder\.layers\.({top})\.self_attn\.(q_proj|k_proj|v_proj|out_proj)"
              rf"|.*decoder\.layers\.\d+\.(self_attn|encoder_attn)\.(q_proj|k_proj|v_proj|out_proj)")
    torch.manual_seed(0)   # same takes, same settings → same model: runs are comparable
    # adapters in bf16 like the model: PEFT would otherwise copy every activation to fp32
    peft_model = get_peft_model(model, LoraConfig(r=rank, lora_alpha=2 * rank, lora_dropout=0.05,
                                                  target_modules=target),
                                autocast_adapter_dtype=False)
    inner = peft_model.base_model.model.model          # WhisperModel inside the adapters
    params = [p for p in peft_model.parameters() if p.requires_grad]
    n_train = sum(p.numel() for p in params)
    opt = torch.optim.AdamW(params, lr=lr, weight_decay=0.01)
    steps = epochs * ((len(cached) + batch - 1) // batch)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=lr, total_steps=steps, pct_start=0.15)
    pad = proc.tokenizer.pad_token_id if proc.tokenizer.pad_token_id is not None else proc.tokenizer.eos_token_id

    t0 = time.perf_counter()
    peft_model.train()
    rng = np.random.default_rng(0)
    last = 0.0
    for ep in range(epochs):
        order = rng.permutation(len(cached))
        losses = []
        for i in range(0, len(order), batch):
            idx = order[i:i + batch]
            x = torch.stack([cached[j] for j in idx])
            seqs = [labels[j] for j in idx]
            L = max(len(s) for s in seqs)
            dec_in = torch.full((len(seqs), L - 1), pad, dtype=torch.long, device=dev)
            tgt = torch.full((len(seqs), L - 1), -100, dtype=torch.long, device=dev)
            for k, s in enumerate(seqs):
                dec_in[k, :len(s) - 1] = torch.tensor(s[:-1], device=dev)
                tgt[k, :len(s) - 1] = torch.tensor(s[1:], device=dev)
                tgt[k, :3] = -100          # language / task / no-timestamps: given, not learned
            with torch.autocast("cuda", dtype=dtype):
                h = x
                for layer in inner.encoder.layers[freeze:]:
                    # recompute instead of storing: 1500 frames × 8 layers of activations
                    # do not fit next to Svara's own model on an 8 GB card
                    h = checkpoint(layer_out, layer, h, use_reentrant=False)
                h = inner.encoder.layer_norm(h)
                dec = inner.decoder(input_ids=dec_in, encoder_hidden_states=h).last_hidden_state
                logits = peft_model.base_model.model.proj_out(dec)
            loss = F.cross_entropy(logits.float().reshape(-1, logits.shape[-1]), tgt.reshape(-1),
                                   ignore_index=-100)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            opt.step()
            sched.step()
            opt.zero_grad(set_to_none=True)
            losses.append(loss.item())
        last = float(np.mean(losses))
        print(f"  epoch {ep + 1}/{epochs}  loss {last:.3f}")
    train_s = time.perf_counter() - t0

    # 3. merge the adapters into plain weights and save them for conversion
    merged = peft_model.merge_and_unload()
    merged.to(torch.float16).save_pretrained(out_hf, safe_serialization=True)
    proc.save_pretrained(out_hf)
    print(f"trained {n_train / 1e6:.1f}M adapter weights on {len(cached)} takes: "
          f"cache {cache_s:.1f}s, train {train_s:.1f}s, final loss {last:.3f}")
    del merged, peft_model, model, cached, opt
    torch.cuda.empty_cache()
    return train_s + cache_s


def convert(hf_dir: Path, ct2_dir: Path) -> None:
    from ctranslate2.converters import TransformersConverter
    from huggingface_hub import hf_hub_download
    # transformers 5 saves processor_config.json; the converter and
    # faster-whisper still read the original preprocessor_config.json
    if not (hf_dir / "preprocessor_config.json").exists():
        shutil.copy(hf_hub_download(BASE_HF, "preprocessor_config.json"), hf_dir)
    TransformersConverter(str(hf_dir), copy_files=["tokenizer.json", "preprocessor_config.json"]
                          ).convert(str(ct2_dir), quantization="float16", force=True)


def score(model_path: str, root: Path) -> float:
    """Held-out WER, measured in Svara's own venv: the CUDA 12 runtime
    faster-whisper is built for, i.e. exactly what dictation will run on.
    (The training venv carries PyTorch's CUDA 13 and cannot load it.)"""
    import subprocess
    runtime = Path(__file__).resolve().parent.parent / ".venv" / "bin" / "python"
    py = str(runtime) if runtime.exists() else sys.executable
    r = subprocess.run([py, "-m", "mywhisper.voice_adapt", "--score", model_path, "--root", str(root)],
                       capture_output=True, text=True, cwd=str(runtime.parent.parent.parent))
    for line in reversed(r.stdout.splitlines()):
        if line.startswith("{"):
            return float(json.loads(line)["wer"])
    raise RuntimeError(f"scoring {model_path} failed:\n{r.stderr[-2000:]}")


def score_here(model_path: str, takes) -> float:
    from .cuda_setup import preload_linux
    preload_linux()
    from faster_whisper import WhisperModel
    m = WhisperModel(model_path, device="cuda", compute_type="int8_float16")
    errs = []
    for t in takes:
        segs, _ = m.transcribe(t["audio"], beam_size=5, language="en", vad_filter=False,
                               condition_on_previous_text=False)
        errs.append(wer(t["text"], " ".join(s.text for s in segs)))
    del m
    return float(np.mean(errs)) if errs else 1.0


def apply_to_config(ct2_dir: Path) -> None:
    cfg = Path(__file__).resolve().parent.parent / "config-linux.yaml"
    text = cfg.read_text(encoding="utf-8")
    import re
    new, n = re.subn(r"(?m)^  name: \S+(.*)$", f"  name: {ct2_dir}\\1", text, count=1)
    if n:
        shutil.copy2(cfg, cfg.with_suffix(".yaml.bak-adapt"))
        cfg.write_text(new, encoding="utf-8")
        print(f"config-linux.yaml now points at the adapted model (backup: {cfg.name}.bak-adapt); "
              "restart with: systemctl --user restart svara.service")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", type=Path, default=data_root() / "voice")
    ap.add_argument("--freeze", type=int, default=24, help="bottom encoder layers run once and cached")
    ap.add_argument("--epochs", type=int, default=3)   # more memorises a 3-minute set
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--margin", type=float, default=1.0, help="WER points the adapted model must win by")
    ap.add_argument("--apply", action="store_true", help="switch Svara to the adapted model if it wins")
    ap.add_argument("--score", metavar="MODEL", help=argparse.SUPPRESS)   # internal: one held-out score
    args = ap.parse_args()

    takes = load_takes(args.root)
    held = [t for t in takes if t["line_id"] % 5 == 0]
    if args.score:
        print(json.dumps({"wer": score_here(args.score, held)}))
        return 0
    train_takes = [t for t in takes if t["line_id"] % 5 != 0]
    minutes = sum(len(t["audio"]) for t in train_takes) / SR / 60
    print(f"{len(takes)} takes: training on {len(train_takes)} ({minutes:.1f} min), "
          f"holding out {len(held)} for the verdict")
    if len(train_takes) < 20 or len(held) < 5:
        print("not enough takes yet: record more of the onboarding session first")
        return 1

    free_gpu()
    stamp = time.strftime("%Y%m%d-%H%M")
    out = data_root() / "models" / f"turbo-voice-{stamp}"
    hf_dir, ct2_dir = out / "hf", out / "ct2"
    out.mkdir(parents=True, exist_ok=True)
    t_all = time.perf_counter()
    train(train_takes, hf_dir, args.freeze, args.epochs, args.lr, args.rank, args.batch)
    t0 = time.perf_counter()
    convert(hf_dir, ct2_dir)
    shutil.rmtree(hf_dir)
    print(f"converted for faster-whisper in {time.perf_counter() - t0:.1f}s")

    base = score(BASE_CT2, args.root)
    adapted = score(str(ct2_dir), args.root)
    gain = (base - adapted) * 100
    verdict = gain >= args.margin
    total = time.perf_counter() - t_all
    print(f"\nheld-out word error rate: stock {base * 100:.1f}%  →  adapted {adapted * 100:.1f}%  "
          f"({'better' if gain > 0 else 'worse'} by {abs(gain):.1f} points)   total {total:.0f}s")
    report = {"when": stamp, "train_takes": len(train_takes), "held_out": len(held),
              "train_minutes": round(minutes, 1), "stock_wer": round(base, 4),
              "adapted_wer": round(adapted, 4), "kept": verdict, "seconds": round(total, 1),
              "model": str(ct2_dir) if verdict else None,
              "settings": {k: getattr(args, k) for k in ("freeze", "epochs", "lr", "rank", "batch")}}
    (args.root / "adapt.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if not verdict:
        shutil.rmtree(out)
        print(f"not kept: it must win by {args.margin:.1f} points. Svara keeps the stock model.")
        return 0
    print(f"kept: {ct2_dir}")
    if args.apply:
        apply_to_config(ct2_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())

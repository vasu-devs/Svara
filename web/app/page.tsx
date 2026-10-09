"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { ScrollSmoother } from "gsap/ScrollSmoother";
import { Flip } from "gsap/Flip";
import { useGSAP } from "@gsap/react";
import { Pill } from "@/components/Pill";
import { Visualizer } from "@/components/Visualizer";
import { setExternalLevel, speak } from "@/lib/engine";
import { fetchReleaseStats, recordVisit, type VisitStats } from "@/lib/stats";

gsap.registerPlugin(useGSAP, ScrollTrigger, ScrollSmoother, Flip);

// Versioned filename, not a static "Svara.exe": re-uploading to the exact same
// URL is a caching landmine, since browsers and CDN edges can keep serving an
// old response for that URL indefinitely. A new version means a new URL, so a
// "fresh download" can never silently be a stale one. The label and the URL
// are built from one constant, so the page cannot advertise one version and
// serve another.
const VERSION = "0.7.0";
const SIZE_MB = 111;
const GITHUB = "https://github.com/vasu-devs/Svara";
const DOWNLOAD = `${GITHUB}/releases/download/v${VERSION}/Svara-${VERSION}.exe`;
const RELEASES = `${GITHUB}/releases`;
const BENCH = `${GITHUB}/blob/main/BENCH.md`;
const PRIVACY = `${GITHUB}/blob/main/PRIVACY.md`;
const BASE = process.env.NEXT_PUBLIC_BASE_PATH || "";
const img = (name: string) => `${BASE}/img/${name}.webp`;
const WPS = 2.6; // a comfortable speaking pace, for the transcript timecodes

/* ------------------------------------------------------------------------
   The page is one dictation, typeset as it lands. Ink is what you said;
   amber is what Svara did to it. Each token below is a word as spoken; the
   special ones are the interventions the real pipeline makes, and each gets
   a proofreader's note in the margin when it fires.
   ------------------------------------------------------------------------ */
type Tok =
  | string
  | { filler: string }                          // spoken, then removed
  | { fix: [string, string]; quiet?: boolean }  // heard as X, typed as Y; quiet = stays ink
  | { shout: [string, string] }                 // said louder than the rest: CAPS
  | { br: true };

type Block = {
  id: string;
  toks: Tok[];
  note?: [string, string];                      // [what happened, how]
  figure?: ReactNode;
  kind?: "opener" | "close";
};

const t = (s: string): Tok[] => s.split(" ").filter(Boolean);

/* Every number in the copy is from BENCH.md and PRIVACY.md. */
const MEASURED = [
  { n: "487", u: "ms", l: "to the first word · CPU" },
  { n: "36", u: "ms", l: "to the first word · GPU" },
  { n: "8.33", u: "%", l: "word error rate" },
  { n: "0.083", u: "", l: "real-time factor" },
];
const CONNECTIONS = [
  { host: "huggingface.co", when: "first run, and when you switch models", what: "the model download. No audio, no text." },
  { host: "api.github.com", when: "once a day, packaged builds only", what: "a version check. No audio, no text, no identifier." },
  { host: "localhost:11434", when: "only if you turn on LLM clean-up", what: "your transcript, to your own Ollama, on your own machine." },
];
const COMPARE = [
  { label: "Where your audio goes", svara: "Your GPU or CPU, in memory", cloud: "Uploaded to their servers" },
  { label: "Works offline", svara: "Yes, fully", cloud: "No" },
  { label: "Cost", svara: "Free", cloud: "$12–15 a month" },
  { label: "Safe in terminals", svara: "Never presses Enter for you", cloud: "Not handled" },
  { label: "Source", svara: "Open, AGPL-3.0", cloud: "Closed" },
];

const BLOCKS: Block[] = [
  {
    id: "open", kind: "opener",
    toks: [{ filler: "Um," }, { filler: "talk into," }, { fix: ["talk", "Talk"], quiet: true }, ...t("into any app."), { br: true }, ...t("Nothing leaves your PC.")],
    note: ["filler and a false start", "heard, then dropped before anything was typed"],
  },
  {
    id: "tray",
    toks: [...t("Svara lives in your tray. Double-tap Right Alt, say what you want written, and it is typed at your cursor in"), { fix: ["slack,", "Slack,"] }, { fix: ["vs code,", "VS Code,"] }, ...t("a browser, a terminal, anywhere you can type.")],
    note: ["dictionary", "your names and jargon, boosted and fixed as they land"],
    figure: (
      <figure className="plate">
        <img src={img("key")} alt="A black Alt key, lit from the side by warm amber light" loading="lazy" decoding="async" />
        <figcaption className="mono">Right Alt. Two taps and the pill is listening; no window to find.</figcaption>
      </figure>
    ),
  },
  {
    id: "fast",
    toks: [...t("It is quick, and it says how quick. On a plain CPU the first word lands 487 milliseconds after you say it; on an NVIDIA GPU, 36. Not a claim, a"), { shout: ["measurement.", "MEASUREMENT."] }],
    note: ["shout to capitalise", "one word said louder than the rest of the sentence"],
    figure: (
      <>
      <figure className="plate">
        <img src={img("silicon")} alt="The pill resting beside a graphics card's heatsink in the dark" loading="lazy" decoding="async" />
        <figcaption className="mono">Whisper runs here, on your own silicon. There is no server to reach.</figcaption>
      </figure>
      <figure className="fig">
        <ul className="nums">
          {MEASURED.map((m) => <li key={m.l}><span className="n mono">{m.n}{m.u && <small> {m.u}</small>}</span><span className="l mono">{m.l}</span></li>)}
        </ul>
        <figcaption className="mono">Measured with <code>run.bat --bench</code> on an RTX 4060 laptop, base.en, 59 s of speech, three passes. A small corpus: read the accuracy as an order of magnitude. <a href={BENCH} target="_blank" rel="noopener">BENCH.md</a></figcaption>
      </figure>
      </>
    ),
  },
  {
    id: "term",
    toks: t("It knows where it is typing. At a shell prompt a newline is the Enter key, so a dictated paragraph lands as one line and never runs itself. Cursor and VS Code get Shift+Insert, because they have claimed Ctrl+V."),
    note: ["line-safe insertion", "Enter stays yours to press, in Windows Terminal, Claude Code, Codex, Cursor, Windsurf"],
    figure: (
      <figure className="fig term">
        <pre className="mono"><span className="dim">PS C:\dev\svara&gt; </span>Review the changes. Explain the failing tests.<span className="caret tcaret" aria-hidden /></pre>
        <figcaption className="mono">Spoken with a pause and a newline between the two sentences. Typed as one line.</figcaption>
      </figure>
    ),
  },
  {
    id: "private",
    toks: t("Nothing you say leaves this machine. Audio lives in RAM, about a second of it at a time, and is never written to disk. No account, no telemetry, no server. Unplug the network cable and it keeps working."),
    note: ["nothing sent", "no analytics endpoint and no crash reporter. Not switched off: absent"],
    figure: (
      <>
      <figure className="plate">
        <img src={img("unplugged")} alt="An unplugged ethernet cable beside the glowing pill" loading="lazy" decoding="async" />
        <figcaption className="mono">Works with the network cable unplugged. Check it with a firewall.</figcaption>
      </figure>
      <figure className="fig">
        <p className="fig-k mono">Every connection it can open</p>
        <dl className="ledger mono">
          {CONNECTIONS.map((c) => <div key={c.host}><dt>{c.host}</dt><dd><em>{c.when}</em> {c.what}</dd></div>)}
        </dl>
        <figcaption className="mono">Everything else: nothing. <a href={PRIVACY} target="_blank" rel="noopener">PRIVACY.md</a> lists every file it writes.</figcaption>
      </figure>
      </>
    ),
  },
  {
    id: "langs",
    toks: [...t("It hears ninety-plus languages, or works out which one you are speaking each time. Speak French and it sets the narrow spaces before « ? » and « ! » ; flip the translate switch and any language comes out as English. Say"), { fix: ["get hub", "GitHub"] }, ...t("and it knows what you meant.")],
    note: ["auto-detect, translate, locale", "French narrow no-break spaces, five English spellings, CJK without stray Latin spacing"],
    figure: (
      <figure className="plate wide">
        <img src={img("strings")} alt="Three amber strands of light across dark glass" loading="lazy" decoding="async" />
        <figcaption className="mono">Ninety-plus languages, one voice.</figcaption>
      </figure>
    ),
  },
  {
    id: "away",
    toks: t("The pill reads the caret of the app you are in and slides aside before it covers your words. It lives in the tray, restarts itself if it crashes, keeps a searchable history on your disk, and updates only when you click Restart to update."),
    note: ["out of your way", "a polled hotkey, never a keyboard hook. Win+Alt+Z re-pastes the last dictation"],
    figure: (
      <>
      <figure className="fig">
        <img className="pill-real" src={img("pill-live")} alt="The Svara pill as it appears on screen while listening: a dark capsule with amber strings" loading="lazy" decoding="async" />
        <figcaption className="mono">The pill, as it appears on screen. It dodges your caret, and you can drag it anywhere.</figcaption>
      </figure>
      <figure className="fig">
        <p className="fig-k mono">Against cloud dictation</p>
        <table className="cmp">
          <thead><tr><th scope="col"><span className="sr">Dimension</span></th><th scope="col" className="mono">Svara</th><th scope="col" className="mono">Cloud</th></tr></thead>
          <tbody>{COMPARE.map((c) => <tr key={c.label}><th scope="row">{c.label}</th><td className="s">{c.svara}</td><td>{c.cloud}</td></tr>)}</tbody>
        </table>
      </figure>
      </>
    ),
  },
  {
    id: "close", kind: "close",
    toks: [...t("That is the whole thing. Free, open source,"), { fix: ["a g p l,", "AGPL-3.0,"] }, ...t("no account, one file. Download it.")],
    note: ["done", `${SIZE_MB} MB · Windows 10 / 11 · installs itself, works offline`],
    figure: (
      <figure className="plate window">
        <img src={img("setup-window")} alt="Svara's first-run window: a headline, the hotkey as keycaps, a list of speech models and a Start button" loading="lazy" decoding="async" />
        <figcaption className="mono">What opens after the download. One window, one choice, then it lives in the tray.</figcaption>
      </figure>
    ),
  },
];

/* Transcript timecodes: where each paragraph starts, at a speaking pace. */
const typedCount = (b: Block) => b.toks.filter((k) => typeof k === "string" || ("fix" in k) || ("shout" in k)).length;
const TIMECODES = BLOCKS.reduce<string[]>((acc, b, i) => {
  const before = BLOCKS.slice(0, i).reduce((a, x) => a + typedCount(x), 0);
  const s = before / WPS; const m = Math.floor(s / 60);
  acc.push(`${String(m).padStart(2, "0")}:${(s % 60).toFixed(1).padStart(4, "0")}`);
  return acc;
}, []);
const fmtTime = (words: number) => { const s = words / WPS; const m = Math.floor(s / 60); return `${String(m).padStart(2, "0")}:${(s % 60).toFixed(1).padStart(4, "0")}`; };

const reduced = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/* ---------- render a spoken token ---------- */
function Word({ tok, caret = false }: { tok: Tok; caret?: boolean }) {
  // The caret is glued to the last word so it can never wrap onto a line of its own.
  if (typeof tok === "string") return caret
    ? <><span className="w nowrap">{tok}<span className="caret" aria-hidden /></span>{" "}</>
    : <span className="w">{tok} </span>;
  if ("br" in tok) return <br />;
  // Grid and inline-block wrappers trim their own trailing whitespace, so the
  // space that separates these words from the next one lives outside them.
  if ("filler" in tok) return <span className="w filler">{tok.filler}</span>;
  if ("fix" in tok) return <><span className={`w fix ${tok.quiet ? "quiet" : ""}`} data-heard={tok.fix[0]}><span className="old">{tok.fix[0]}</span><span className="new">{tok.fix[1]}</span></span>{" "}</>;
  return <><span className="w shout" data-to={tok.shout[1]} data-heard={tok.shout[0]}>{tok.shout[0]}</span>{" "}</>;
}

export default function Page() {
  const root = useRef<HTMLDivElement>(null);
  const pillHolder = useRef<HTMLDivElement>(null);
  const openTlRef = useRef<gsap.core.Timeline | null>(null);
  const [downloads, setDownloads] = useState<number | null>(null);
  const [visits, setVisits] = useState<VisitStats | null>(null);
  const [scrolled, setScrolled] = useState(false);
  const [live, setLive] = useState(false);
  const [pillLabel, setPillLabel] = useState("Listening");
  const liveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [mic, setMic] = useState<"off" | "on" | "denied">("off");
  const micRef = useRef<{ ctx: AudioContext; stream: MediaStream; raf: number } | null>(null);

  // Click the pill and it hears you: a real level from your microphone,
  // measured in this tab with Web Audio and shown on the strings. Nothing is
  // recorded and nothing is sent, which is what the score in the top bar is for.
  const stopMic = () => {
    const m = micRef.current; if (!m) return;
    cancelAnimationFrame(m.raf); m.stream.getTracks().forEach((t) => t.stop()); m.ctx.close().catch(() => {});
    micRef.current = null; setExternalLevel(null); setMic("off");
  };
  const toggleMic = async () => {
    if (micRef.current) { stopMic(); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const ctx = new AudioContext(); const src = ctx.createMediaStreamSource(stream);
      const an = ctx.createAnalyser(); an.fftSize = 1024; src.connect(an);
      const buf = new Uint8Array(an.fftSize); let smooth = 0;
      const m = { ctx, stream, raf: 0 }; micRef.current = m; setMic("on");
      const tick = () => {
        an.getByteTimeDomainData(buf);
        let sum = 0; for (let i = 0; i < buf.length; i++) { const v = (buf[i] - 128) / 128; sum += v * v; }
        const rms = Math.sqrt(sum / buf.length);
        smooth += (Math.min(1, rms * 7) - smooth) * 0.35;
        setExternalLevel(smooth);
        m.raf = requestAnimationFrame(tick);
      };
      tick();
    } catch { setMic("denied"); }
  };
  useEffect(() => () => stopMic(), []);

  useEffect(() => {
    let alive = true;
    fetchReleaseStats().then((s) => { if (alive && s) setDownloads(s.downloads); });
    recordVisit().then((v) => { if (alive && v) setVisits(v); });
    return () => { alive = false; };
  }, []);

  // Double-tap Right Alt, the way you would to start Svara, and the first
  // line dictates itself again.
  useEffect(() => {
    let last = 0;
    const onKey = (e: KeyboardEvent) => {
      if (e.code !== "AltRight") return;
      e.preventDefault();
      const now = performance.now();
      if (now - last < 450) {
        last = 0;
        const tl = openTlRef.current;
        const opener = root.current?.querySelector<HTMLElement>(".block.opener");
        if (!tl || !opener) return;
        opener.querySelectorAll<HTMLElement>(".shout").forEach((el) => { el.textContent = el.dataset.heard || ""; el.classList.remove("done"); });
        tl.restart(true);
        setPillLabel("Typing");
      } else last = now;
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    const on = () => {
      setScrolled(window.scrollY > 24);
      setLive(true); speak(500);
      if (liveTimer.current) clearTimeout(liveTimer.current);
      liveTimer.current = setTimeout(() => setLive(false), 800);
    };
    window.addEventListener("scroll", on, { passive: true });
    return () => { window.removeEventListener("scroll", on); if (liveTimer.current) clearTimeout(liveTimer.current); };
  }, []);

  useGSAP(() => {
    const scope = root.current!;
    const hudWords = scope.querySelector<HTMLElement>(".hud-words");
    const hudTime = scope.querySelector<HTMLElement>(".hud-time");
    const blocks = gsap.utils.toArray<HTMLElement>(".block");
    const counts = blocks.map(() => 0);
    const typed = (b: Element) => b.querySelectorAll(".w:not(.filler)");
    const total = blocks.reduce((a, b) => a + typed(b).length, 0);
    const hud = () => {
      const sum = counts.reduce((a, b) => a + b, 0);
      if (hudWords) hudWords.textContent = String(sum).padStart(String(total).length, "0");
      if (hudTime) hudTime.textContent = fmtTime(sum);
    };
    const isReduced = reduced();

    /* Inertial scroll. Fixed chrome lives outside the smoothed content. */
    let smoother: ScrollSmoother | null = null;
    if (!isReduced && !ScrollTrigger.isTouch) {
      smoother = ScrollSmoother.create({ wrapper: "#smooth-wrapper", content: "#smooth-content", smooth: 1.1, effects: false, normalizeScroll: false });
    }
    const onAnchor = (e: Event) => {
      const a = (e.target as HTMLElement).closest<HTMLAnchorElement>('a[href^="#"]');
      if (!a || !smoother) return;
      const target = document.querySelector(a.getAttribute("href")!);
      if (!target) return;
      e.preventDefault(); smoother.scrollTo(target, true, "top 96px");
    };
    scope.addEventListener("click", onAnchor);

    /* The interventions: what Svara does to a sentence once it has heard it. */
    const intervene = (block: HTMLElement) => {
      const d = isReduced ? 0 : 1;
      const tl = gsap.timeline({ delay: 0.35 * d });
      block.querySelectorAll<HTMLElement>(".filler").forEach((el, i) => {
        tl.to(el, { color: "#a8681a", duration: 0.25 * d }, i * 0.15 * d)
          .to(el, { width: 0, opacity: 0, marginRight: 0, duration: 0.6 * d, ease: "power3.inOut" }, ">-0.05");
      });
      block.querySelectorAll<HTMLElement>(".fix").forEach((el, i) => {
        const old = el.querySelector(".old"), neu = el.querySelector(".new");
        tl.to(old, { opacity: 0, y: -6, duration: 0.3 * d }, 0.2 * d + i * 0.25 * d)
          .fromTo(neu, { opacity: 0, y: 6 }, { opacity: 1, y: 0, duration: 0.4 * d, ease: "power2.out" }, "<0.1")
          .fromTo(el, { backgroundColor: "rgba(217,146,43,.32)" }, { backgroundColor: "rgba(217,146,43,0)", duration: 1.4 * d, ease: "power2.out" }, "<");
      });
      block.querySelectorAll<HTMLElement>(".shout").forEach((el) => {
        tl.to(el, { scale: 1.08, duration: 0.14 * d, ease: "power2.in", onComplete: () => { el.textContent = el.dataset.to || ""; el.classList.add("done"); } }, 0.5 * d)
          .to(el, { scale: 1, duration: 0.35 * d, ease: "back.out(3)" });
      });
      const note = block.querySelector(".note");
      if (note) tl.fromTo(note, { opacity: 0, y: 8 }, { opacity: 1, y: 0, duration: 0.7 * d, ease: "power2.out" }, 0.3 * d);
      return tl;
    };

    if (isReduced) {
      blocks.forEach((b, i) => { counts[i] = typed(b).length; intervene(b); });
      hud();
      const holder = pillHolder.current; if (holder) holder.classList.add("docked");
      setPillLabel("Done");
      return () => scope.removeEventListener("click", onAnchor);
    }

    /* The opener types itself on arrival, then Svara cleans it. */
    const opener = blocks[0];
    const ow = opener.querySelectorAll(".w");
    const ot = typed(opener).length;
    gsap.set(ow, { opacity: 0, y: 10, filter: "blur(10px)" });
    gsap.set(".w .new", { opacity: 0 });
    const holder = pillHolder.current!;
    const slot = scope.querySelector<HTMLElement>(".pill-slot");
    const desktop = () => window.innerWidth > 820;
    // While the first line types, the pill rides beside the caret, the way
    // the real one stays next to where you are typing; it never covers words.
    let following = false;
    const follow = (el: Element) => {
      if (!desktop()) return;
      const r = el.getBoundingClientRect();
      const hw = holder.offsetWidth || 176, hh = holder.offsetHeight || 54;
      let x = r.right + 22, y = r.top + r.height / 2 - hh / 2;
      if (x + hw > window.innerWidth - 24) { x = r.left; y = r.bottom + 14; }
      gsap.to(holder, { x, y, duration: 0.28, ease: "power2.out", overwrite: "auto" });
    };
    const settle = () => {
      following = false;
      if (!desktop() || !slot) return;
      const r = slot.getBoundingClientRect();
      gsap.to(holder, { x: r.left, y: r.top, duration: 0.9, ease: "power3.inOut", overwrite: "auto" });
    };
    const openTl = gsap.timeline({ delay: 0.6 });
    openTlRef.current = openTl;
    openTl.call(() => { setPillLabel("Typing"); following = true; if (desktop()) follow(ow[0]); })
      .to(ow, { opacity: 1, y: 0, filter: "blur(0px)", duration: 0.55, ease: "power2.out",
        stagger: { each: 0.13, onStart(this: gsap.core.Tween) { speak(300); follow(this.targets()[0] as Element); } },
        onUpdate: () => { counts[0] = Math.min(ot, Math.round(openTl.progress() * ow.length)); hud(); } })
      .add(intervene(opener), "+=0.15")
      .call(() => { setPillLabel("Listening"); settle(); }, undefined, "-=0.4")
      .from(".open-cta > *", { y: 12, opacity: 0, duration: 0.7, stagger: 0.08, ease: "power2.out" }, "-=0.6")
      .from(".hud", { opacity: 0, duration: 0.6 }, "<");

    /* Every other block lands at reading speed: the words rise in as you
       scroll them into the middle of the screen, then Svara intervenes. */
    blocks.slice(1).forEach((block, k) => {
      const i = k + 1;
      const last = i === blocks.length - 1;
      const words = block.querySelectorAll(".w");
      const n = typed(block).length;
      gsap.set(words, { opacity: 0.08, y: 6 });
      gsap.to(words, {
        opacity: 1, y: 0, duration: 1, ease: "none", stagger: { each: 0.9 / words.length },
        scrollTrigger: {
          trigger: block, start: last ? "top 92%" : "top 86%", end: last ? "top 62%" : "top 46%", scrub: 0.7,
          onUpdate: (self) => { counts[i] = Math.round(self.progress * n); hud(); },
        },
      });
      ScrollTrigger.create({ trigger: block, start: last ? "top 66%" : "top 54%", once: true, onEnter: () => { intervene(block); if (last) setPillLabel("Done"); } });
      const fig = block.querySelector(".figure");
      if (fig) gsap.from(fig, { y: 28, opacity: 0, duration: 1.1, ease: "power2.out", scrollTrigger: { trigger: fig, start: "top 88%", once: true } });
      const tc = block.querySelector(".tc");
      if (tc) gsap.from(tc, { opacity: 0, duration: 0.8, scrollTrigger: { trigger: block, start: "top 80%", once: true } });
    });

    /* The pill starts beside the first line and flies to its dock once the
       transcript is under way. While parked it follows the slot it belongs
       to, so it scrolls with the paper like a real object on the page. */
    /* The only light in the room. While the pill rides the caret it lights the
       words being typed; afterwards it settles on whatever you are reading. */
    const light = scope.querySelector<HTMLElement>(".light")!;
    const lx = gsap.quickTo(light, "--lx", { duration: 0.9, ease: "power2.out" });
    const ly = gsap.quickTo(light, "--ly", { duration: 0.9, ease: "power2.out" });
    gsap.set(light, { "--lx": window.innerWidth * 0.5, "--ly": window.innerHeight * 0.42 });
    const mouse = { x: -1, y: -1, at: 0 };
    const onMove = (e: PointerEvent) => { mouse.x = e.clientX; mouse.y = e.clientY; mouse.at = performance.now(); };
    window.addEventListener("pointermove", onMove, { passive: true });
    const lightTick = () => {
      light.style.setProperty("--lr", `${46 + Math.sin(performance.now() / 1400) * 2.5}vmax`);
      if (!following && mouse.at && performance.now() - mouse.at < 1600) { lx(mouse.x); ly(mouse.y); return; }
      if (following) {
        const r = holder.getBoundingClientRect();
        lx(r.left + r.width / 2); ly(r.top + r.height / 2);
        return;
      }
      const mid = window.innerHeight * 0.42;
      let best: HTMLElement | null = null, bestD = 1e9;
      for (const b of blocks) {
        const r = b.getBoundingClientRect();
        const c = Math.max(r.top, Math.min(r.bottom, mid));
        const d = Math.abs(c - mid) + (mid < r.top || mid > r.bottom ? 400 : 0);
        if (d < bestD) { bestD = d; best = b; }
      }
      if (!best) return;
      const t = best.querySelector<HTMLElement>(".text") || best;
      const r = t.getBoundingClientRect();
      lx(r.left + Math.min(r.width, 720) * 0.45); ly(Math.max(r.top + 40, Math.min(r.bottom - 40, mid)));
    };
    gsap.ticker.add(lightTick);

    let docked = false, flying = false;
    const park = () => {
      if (docked || flying || following || !slot) return;
      if (gsap.isTweening(holder)) return;
      const r = slot.getBoundingClientRect();
      gsap.set(holder, { x: r.left, y: r.top, xPercent: 0, yPercent: 0 });
    };
    if (desktop()) { gsap.ticker.add(park); if (slot) { const r = slot.getBoundingClientRect(); gsap.set(holder, { x: r.left, y: r.top }); } } else { holder.classList.add("docked"); docked = true; }
    const fly = (toDock: boolean) => {
      if (!desktop() || docked === toDock) return;
      following = false;
      const state = Flip.getState(holder);
      docked = toDock; flying = true;
      if (toDock) { holder.classList.add("docked"); gsap.set(holder, { clearProps: "transform" }); }
      else { holder.classList.remove("docked"); const r = slot!.getBoundingClientRect(); gsap.set(holder, { x: r.left, y: r.top }); }
      Flip.from(state, { duration: 1, ease: "power3.inOut", onComplete: () => { flying = false; } });
    };
    ScrollTrigger.create({ trigger: blocks[1], start: "top 88%", onEnter: () => fly(true), onLeaveBack: () => fly(false) });

    /* The cursor: an amber point that grows over anything you can touch. */
    const cur = scope.querySelector<HTMLElement>(".cursor");
    let cursorOff = () => {};
    if (cur && window.matchMedia("(pointer: fine)").matches) {
      document.documentElement.classList.add("has-cursor");
      const cx = gsap.quickTo(cur, "x", { duration: 0.18, ease: "power3.out" });
      const cy = gsap.quickTo(cur, "y", { duration: 0.18, ease: "power3.out" });
      const move = (e: PointerEvent) => {
        cx(e.clientX); cy(e.clientY); cur.classList.add("on");
        const t = e.target as HTMLElement | null;
        cur.classList.toggle("big", !!t?.closest("a, button, .pill, .w.fix:not(.quiet), .w.shout.done, .plate img"));
      };
      const leave = () => cur.classList.remove("on");
      window.addEventListener("pointermove", move, { passive: true });
      document.documentElement.addEventListener("pointerleave", leave);
      cursorOff = () => { window.removeEventListener("pointermove", move); document.documentElement.removeEventListener("pointerleave", leave); document.documentElement.classList.remove("has-cursor"); };
    }

    /* Plates tilt toward the cursor, with a highlight that slides across. */
    scope.querySelectorAll<HTMLElement>(".plate").forEach((pl) => {
      const im = pl.querySelector<HTMLElement>("img"); if (!im) return;
      const rx = gsap.quickTo(im, "rotationX", { duration: 0.6, ease: "power3.out" });
      const ry = gsap.quickTo(im, "rotationY", { duration: 0.6, ease: "power3.out" });
      gsap.set(im, { transformPerspective: 900 });
      pl.addEventListener("pointermove", (e) => {
        const r = im.getBoundingClientRect(); const px = (e.clientX - r.left) / r.width, py = (e.clientY - r.top) / r.height;
        ry((px - 0.5) * 8); rx((0.5 - py) * 8);
        pl.style.setProperty("--px", `${px * 100}%`); pl.style.setProperty("--py", `${py * 100}%`);
      });
      pl.addEventListener("pointerleave", () => { rx(0); ry(0); });
    });

    /* Buttons lean toward the cursor and glow where it is. */
    scope.querySelectorAll<HTMLElement>(".btn").forEach((btn) => {
      const bx = gsap.quickTo(btn, "x", { duration: 0.35, ease: "power3.out" });
      const by = gsap.quickTo(btn, "y", { duration: 0.35, ease: "power3.out" });
      btn.addEventListener("pointermove", (e) => {
        const r = btn.getBoundingClientRect();
        bx(((e.clientX - r.left) / r.width - 0.5) * 8); by(((e.clientY - r.top) / r.height - 0.5) * 6);
        btn.style.setProperty("--gx", `${e.clientX - r.left}px`); btn.style.setProperty("--gy", `${e.clientY - r.top}px`);
      });
      btn.addEventListener("pointerleave", () => { bx(0); by(0); });
    });

    return () => { scope.removeEventListener("click", onAnchor); window.removeEventListener("pointermove", onMove); cursorOff(); gsap.ticker.remove(park); gsap.ticker.remove(lightTick); };
  }, { scope: root });

  return (
    <div ref={root}>
      <a className="skip" href="#main">Skip to content</a>
      <div className="light" aria-hidden />

      <header className={`top ${scrolled ? "scrolled" : ""}`}>
        <a href="#top" className="brand" aria-label="Svara, back to top" onPointerEnter={() => speak(1200)}>
          <Visualizer style="strings" className="brand-viz" />
          <span className="brand-name">Svara</span>
          <span className="brand-deva" aria-hidden>स्वर</span>
        </a>
        <div className="hud mono" aria-live="off">
          <span><b className="hud-time">00:00.0</b></span>
          <span><b className="hud-words">000</b> words typed</span>
          <span><b>0 B</b> uploaded</span>
        </div>
        <div className="top-end">
          <a className="top-gh mono" href={GITHUB} target="_blank" rel="noopener">GitHub</a>
          <a className="btn sm" href={DOWNLOAD}>Download {VERSION}</a>
        </div>
      </header>

      <div id="smooth-wrapper">
        <div id="smooth-content">
          <main id="main" className="doc">
            <div className="doc-in" id="top">
              {BLOCKS.map((b, i) => (
                <section key={b.id} id={b.id} className={`block ${b.kind || ""}`}>
                  <div className="col-text">
                    {b.kind === "opener" ? (
                      <div className="open-top">
                        <p className="text opener-text">
                          {b.toks.map((tok, j) => <Word key={j} tok={tok} caret={j === b.toks.length - 1} />)}
                        </p>
                        <p className="hint">Keep reading. This page lands the way Svara types: one word at a time, cleaned as it goes. <span className="hint-key">Double-tap <kbd>Right Alt</kbd> to hear the first line again. Click the pill and it hears you: your microphone, in this tab, nothing sent.</span></p>
                      </div>
                    ) : (
                      <p className="text">
                        {b.toks.map((tok, j) => <Word key={j} tok={tok} />)}
                      </p>
                    )}
                    {b.kind === "opener" && (
                      <div className="open-cta">
                        <a className="btn" href={DOWNLOAD}>
                          Download Svara {VERSION}
                          <svg viewBox="0 0 16 16" width="15" height="15" fill="none" aria-hidden><path d="M8 2.5v8m0 0L4.8 7.3M8 10.5l3.2-3.2M3 13.5h10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
                        </a>
                        <p className="meta mono">Private voice dictation for Windows · {SIZE_MB} MB · no account · works offline</p>
                      </div>
                    )}
                    {b.kind === "close" && (
                      <div className="close-cta">
                        <a className="btn lg" href={DOWNLOAD}>
                          Download Svara-{VERSION}.exe
                          <svg viewBox="0 0 16 16" width="15" height="15" fill="none" aria-hidden><path d="M8 2.5v8m0 0L4.8 7.3M8 10.5l3.2-3.2M3 13.5h10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
                        </a>
                        <div className="close-links mono">
                          <a href={RELEASES} target="_blank" rel="noopener">Release notes</a>
                          <a href={`${GITHUB}#quick-start`} target="_blank" rel="noopener">Build from source</a>
                          <a href={PRIVACY} target="_blank" rel="noopener">Privacy</a>
                          {downloads !== null && <span>{downloads.toLocaleString()} downloads so far</span>}
                        </div>
                      </div>
                    )}
                    {b.figure && <div className="figure">{b.figure}</div>}
                  </div>
                  <aside className="col-note">
                    <span className="tc mono" aria-hidden>{TIMECODES[i]}</span>
                    {b.kind === "opener" && <div className="pill-slot" aria-hidden />}
                    {b.note && (
                      <p className="note mono">
                        <span className="note-i">{String(i + 1).padStart(2, "0")}</span>
                        <b>{b.note[0]}</b>
                        <span>{b.note[1]}</span>
                      </p>
                    )}
                  </aside>
                </section>
              ))}
            </div>
          </main>

          <footer className="foot mono">
            <span><span className="brand-deva" aria-hidden>स्वर</span> Svara · © 2026 · AGPL-3.0{visits !== null && <> · {visits.unique.toLocaleString()} visitors</>}</span>
            <span className="foot-links">
              <a href={GITHUB} target="_blank" rel="noopener">GitHub</a>
              <a href={`${GITHUB}/issues`} target="_blank" rel="noopener">Issues</a>
              <a href="https://github.com/SYSTRAN/faster-whisper" target="_blank" rel="noopener">Built on faster-whisper</a>
              <a href="#top">Back to top</a>
            </span>
          </footer>
        </div>
      </div>

      <div className="pill-holder" ref={pillHolder}>
        <Pill live={live || mic === "on"} label={mic === "on" ? "Hearing you" : mic === "denied" ? "No mic" : pillLabel} onTap={toggleMic} />
      </div>
      <div className="cursor" aria-hidden><i /></div>
    </div>
  );
}

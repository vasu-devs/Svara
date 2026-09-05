"use client";

import { useEffect, useRef, useState } from "react";
import { Visualizer } from "@/components/Visualizer";
import { DictationDemo } from "@/components/DictationDemo";
import { MOODS, MOOD_ORDER, applyMood, speak, setPointer, type Style } from "@/lib/engine";
import { fetchReleaseStats, recordVisit, type VisitStats } from "@/lib/stats";

// Versioned filename, not a static "Svara.exe" — re-uploading to the exact
// same URL repeatedly (as every fix does) is a caching landmine: browsers
// and CDN edges can keep serving an old cached response for that URL
// indefinitely. A new version number means a genuinely new URL every time,
// so a "fresh download" can never silently be a stale one.
// Single source of truth: the label and the URL are built from the same
// constant, so the page can never advertise one version and serve another.
const VERSION = "0.7.0";
const SIZE_MB = 111;
const DOWNLOAD = `https://github.com/vasu-devs/Svara/releases/download/v${VERSION}/Svara-${VERSION}.exe`;
const GITHUB = "https://github.com/vasu-devs/Svara";

const SPY = [
  { id: "how", num: "01", name: "Movements" },
  { id: "privacy", num: "02", name: "Private" },
  { id: "features", num: "03", name: "Everything" },
  { id: "compare", num: "04", name: "Compare" },
];

const STEPS: { n: string; mvt: string; viz: Style; title: string; body: string; tag: string }[] = [
  { n: "I", mvt: "largo", viz: "pulse", title: "Double-tap and speak", body: "Tap Right Alt twice and the pill appears, listening. No window to find, no button to hunt for.", tag: "Right Alt · x2" },
  { n: "II", mvt: "allegro", viz: "strings", title: "Just talk, naturally", body: "Words appear as you speak — punctuation and filler cleaned up on the fly. Raise your voice and it lands in caps.", tag: "~1s · spoken to written" },
  { n: "III", mvt: "coda", viz: "beam", title: "It lands at your cursor", body: "The text is written into whatever app you are in — Slack, VS Code, a browser, a terminal.", tag: "works everywhere" },
];

const FEATURES: { n: string; title: string; tag: string; body: string }[] = [
  { n: "01", title: "Runs on your own machine", tag: "on-device", body: "Audio is captured, written, and discarded locally. There is no server to reach — nothing to upload, ever." },
  { n: "02", title: "Fast, and it proves it", tag: "measured", body: "faster-whisper on CTranslate2. Ships CPU-first and steps up to your GPU in one click — and `--bench` measures the latency and error rate on your own hardware instead of asking you to trust a number." },
  { n: "03", title: "Ninety-plus languages", tag: "90+ langs", body: "Dictate in any language Whisper understands, or let it auto-detect what you speak each time." },
  { n: "04", title: "Speak to translate", tag: "translate", body: "Flip one switch and talk in any language — Svara writes clean English at your cursor." },
  { n: "05", title: "Shout to CAPITALISE", tag: "emphasis", body: "Raise your voice on a word and it lands in caps. Loudness-aware and shout-proof, so only real emphasis counts." },
  { n: "06", title: "Cleaned up as you talk", tag: "clean-up", body: "Automatic punctuation, filler removal, self-corrections on the fly. Optional local-LLM polish via Ollama — still offline." },
  { n: "07", title: "Safe in a terminal", tag: "dev-ready", body: "A newline at a shell prompt is the Enter key. Svara knows, so a dictated paragraph lands as one editable line and never runs itself — in Windows Terminal, Claude Code, Codex, Cursor or Windsurf." },
  { n: "08", title: "Written the way you write it", tag: "typography", body: "French gets its non-breaking spaces, CJK loses its Latin spacing, and English picks a side: US, British, Canadian, Australian or Indian spelling." },
  { n: "09", title: "Moves out of your way", tag: "stays clear", body: "The pill reads the caret of the app you are in and slides aside the instant it would cover what you are typing." },
  { n: "10", title: "Free and open source", tag: "open source", body: "No account, no subscription, no telemetry on your voice. The whole thing is yours to read, fork, and build." },
];
const FEAT_VIZ: Style[] = ["strings", "beam", "spectrum", "scope", "pulse", "bars", "beam", "spectrum", "strings", "particles"];

const STATS = [
  { shown: "0", count: 0, suffix: "", label: "bytes uploaded", accent: false },
  { shown: "~1s", count: null, suffix: "", label: "spoken to written", accent: true },
  { shown: "90", count: 90, suffix: "+", label: "languages", accent: false },
  { shown: "10", count: 10, suffix: "", label: "live visualisers", accent: false },
];

/** The last slot goes live once GitHub answers with the real download count.
 *  Until then - and permanently, if the API is rate limited or unreachable -
 *  it stays on the static stat, so the row never shows a gap or a hollow "0". */
function statsWith(downloads: number | null) {
  if (downloads === null) return STATS;
  return [...STATS.slice(0, 3), {
    shown: String(downloads), count: downloads, suffix: "",
    label: downloads === 1 ? "download" : "downloads", accent: false,
  }];
}

const COMPARE = [
  { label: "Where your audio goes", svara: "Your GPU, in memory", cloud: "Uploaded to their servers" },
  { label: "Works offline", svara: "Yes, fully", cloud: "No" },
  { label: "Cost", svara: "Free, forever", cloud: "$12–15 / month" },
  { label: "Account required", svara: "None", cloud: "Sign-up + login" },
  // Deliberately not claiming a latency win: a datacentre GPU is quick, and
  // Svara's own published numbers (BENCH.md) put the CPU default at ~0.8s.
  // What is actually true is that there is no round-trip and no queue.
  { label: "Latency", svara: "No round-trip", cloud: "Network + queue" },
  { label: "Safe in terminals", svara: "Never runs your text", cloud: "Not handled" },
  { label: "Telemetry on your voice", svara: "Zero", cloud: "Varies" },
  { label: "Source", svara: "Open · AGPL-3.0", cloud: "Closed" },
];

/* ---------- scroll reveal ---------- */
function Reveal({ children, className, delay = 0 }: { children: React.ReactNode; className?: string; delay?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current; if (!el) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    if (el.getBoundingClientRect().top <= window.innerHeight * 0.86) return;
    el.style.transitionDelay = `${delay}s`; el.classList.add("rv-hidden");
    let done = false; const reveal = () => { if (done) return; done = true; el.classList.remove("rv-hidden"); };
    const io = new IntersectionObserver((es) => { if (es[0].isIntersecting) { reveal(); io.disconnect(); } }, { threshold: 0.1, rootMargin: "0px 0px -7% 0px" });
    io.observe(el); const fb = setTimeout(reveal, 3400);
    return () => { io.disconnect(); clearTimeout(fb); };
  }, [delay]);
  return <div ref={ref} className={`rv ${className || ""}`}>{children}</div>;
}

/* ---------- magnetic buttons ---------- */
function Magnetic({ children, s = 0.3 }: { children: React.ReactNode; s?: number }) {
  const ref = useRef<HTMLSpanElement>(null);
  return (
    <span ref={ref} className="mag"
      onPointerMove={(e) => { const el = ref.current; if (!el || e.pointerType !== "mouse" || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return; const r = el.getBoundingClientRect(); el.style.transform = `translate(${(e.clientX - r.left - r.width / 2) * s}px,${(e.clientY - r.top - r.height / 2) * s}px)`; }}
      onPointerLeave={() => { if (ref.current) ref.current.style.transform = "translate(0,0)"; }}>
      {children}
    </span>
  );
}

/* ---------- count-up stat ---------- */
function CountStat({ shown, count, suffix, label, accent }: { shown: string; count: number | null; suffix: string; label: string; accent: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const [text, setText] = useState(shown + suffix);
  useEffect(() => {
    setText(shown + suffix);
    if (count === null) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) { setText(shown + suffix); return; }
    const el = ref.current; if (!el) return;
    let frame = 0;
    let done = false;
    const run = () => {
      if (done) return; done = true;
      const dur = 1150, st = performance.now();
      const step = (t: number) => { const p = Math.min(1, (t - st) / dur), e = 1 - Math.pow(1 - p, 3); setText(Math.round(count * e) + suffix); if (p < 1) frame = requestAnimationFrame(step); };
      frame = requestAnimationFrame(step);
    };
    const io = new IntersectionObserver((es) => { if (es[0].isIntersecting) { run(); io.disconnect(); } }, { threshold: 0.2 });
    io.observe(el);
    return () => { io.disconnect(); cancelAnimationFrame(frame); };
  }, [count, suffix, shown]);
  return (
    <div className="stat" ref={ref}>
      <div className="n" style={accent ? { color: "var(--accent)", fontStyle: "italic", transition: "color .6s" } : undefined}>{text}</div>
      <div className="l">{label}</div>
    </div>
  );
}

/* ---------- draggable hero pill ---------- */
function HeroPill() {
  const ref = useRef<HTMLDivElement>(null);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  function clearTimers() { timers.current.forEach(clearTimeout); timers.current = []; }
  useEffect(() => () => { timers.current.forEach(clearTimeout); }, []);
  const drag = useRef({ on: false, ox: 0, oy: 0, px: 0, py: 0, vx: 0, vy: 0, lx: 0, ly: 0 });
  return (
    <div className="hero-pill" ref={ref}
      onPointerDown={(e) => {
        const el = ref.current; if (!el) return;
        clearTimers();
        try { el.setPointerCapture(e.pointerId); } catch { /* noop */ }
        const d = drag.current;
        d.on = true; el.style.animation = "none"; el.style.transition = "none";
        d.ox = e.clientX - d.px; d.oy = e.clientY - d.py; d.lx = e.clientX; d.ly = e.clientY;
      }}
      onPointerMove={(e) => {
        const el = ref.current; const d = drag.current; if (!el || !d.on) return;
        d.px = Math.max(-80, Math.min(80, e.clientX - d.ox)); d.py = Math.max(-55, Math.min(55, e.clientY - d.oy));
        d.vx = e.clientX - d.lx; d.vy = e.clientY - d.ly; d.lx = e.clientX; d.ly = e.clientY;
        const tilt = Math.max(-9, Math.min(9, d.vx));
        el.style.transform = `translate(${d.px}px,${d.py}px) rotate(${tilt}deg)`;
        speak(280);
      }}
      onPointerUp={() => {
        const el = ref.current; const d = drag.current; if (!el || !d.on) return;
        d.on = false;
        d.px += d.vx * 5; d.py += d.vy * 5;
        el.style.transition = "transform .55s cubic-bezier(.16,.9,.3,1)";
        el.style.transform = `translate(${d.px}px,${d.py}px) rotate(0deg)`;
        timers.current.push(setTimeout(() => {
          el.style.transition = "transform 1.15s cubic-bezier(.19,1,.22,1)";
          d.px = 0; d.py = 0; el.style.transform = "translate(0,0) rotate(0deg)";
          timers.current.push(setTimeout(() => { if (!d.on) el.style.animation = "floaty 5.5s ease-in-out infinite"; }, 1150));
        }, 160));
      }}
      onPointerCancel={() => {
        clearTimers(); drag.current.on = false; drag.current.px = 0; drag.current.py = 0;
        if (ref.current) { ref.current.style.transform = ""; ref.current.style.transition = ""; ref.current.style.animation = ""; }
      }}>
      <span className="dot" />
      <Visualizer style="bars" className="pill-viz" />
      <span className="lbl">Listening</span>
    </div>
  );
}

export default function Page() {
  const [mood, setMoodState] = useState("sienna");
  const [spyId, setSpyId] = useState("how");
  const [feat, setFeat] = useState(0);
  const featHover = useRef(false);
  const heroRef = useRef<HTMLDivElement>(null);
  const [downloads, setDownloads] = useState<number | null>(null);
  const [visits, setVisits] = useState<VisitStats | null>(null);

  function morph(key: string) { applyMood(key); setMoodState(key); speak(1600); }

  useEffect(() => { applyMood("sienna"); }, []);

  // Real download count, straight from the GitHub Releases API. Never blocks
  // paint: the stat row renders its static value and swaps if the call lands.
  useEffect(() => {
    let alive = true;
    fetchReleaseStats().then((s) => {
      if (alive && s) setDownloads(s.downloads);
    });
    // No-ops on the static Pages build, which has no /api route to call.
    recordVisit().then((v) => { if (alive && v) setVisits(v); });
    return () => { alive = false; };
  }, []);

  // section-spy
  useEffect(() => {
    const map = new Map<Element, string>();
    SPY.forEach((s) => { const el = document.getElementById(s.id); if (el) map.set(el, s.id); });
    const io = new IntersectionObserver((ents) => {
      ents.forEach((en) => { if (en.isIntersecting) { const id = map.get(en.target); if (id) setSpyId(id); } });
    }, { rootMargin: "-45% 0px -50% 0px", threshold: 0 });
    map.forEach((_id, el) => io.observe(el));
    return () => io.disconnect();
  }, []);

  // feature auto-rotate
  useEffect(() => {
    const iv = setInterval(() => { if (!featHover.current && !document.hidden && !window.matchMedia("(prefers-reduced-motion: reduce)").matches && !document.activeElement?.closest(".feat-grid")) { setFeat((f) => (f + 1) % FEATURES.length); speak(900); } }, 3400);
    return () => clearInterval(iv);
  }, []);

  // click ripple
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const layer = document.querySelector(".ripple-layer");
    if (!layer) return;
    const on = (e: PointerEvent) => {
      const t = e.target as HTMLElement;
      if (t?.closest?.("a,button")) return;
      const d = document.createElement("span");
      d.className = "ripple-dot";
      d.style.left = `${e.clientX}px`; d.style.top = `${e.clientY}px`;
      layer.appendChild(d);
      setTimeout(() => d.remove(), 1000);
      speak(500);
    };
    window.addEventListener("pointerdown", on);
    return () => window.removeEventListener("pointerdown", on);
  }, []);

  return (
    <>
      <a className="skip-link" href="#top">Skip to content</a>
      <div className="ripple-layer" aria-hidden />
      <div className="bg-glow" aria-hidden />
      <div className="bg-staff" aria-hidden />
      <div className="bg-marble" aria-hidden />
      <div className="bg-grain" aria-hidden />
      <AnimatedFavicon mood={mood} />

      <header className="nav-wrap">
        <div className="nav-pill">
          <a href="#top" className="nav-brand"><Visualizer style="strings" className="logo-viz" /><span>Svara</span></a>
          <nav className="nav-mid">
            <a href="#how">Movements</a><a href="#privacy">Private</a><a href="#features">Everything</a><a href="#compare">Compare</a>
          </nav>
          <div className="nav-end">
            <a className="nav-gh" href={GITHUB} target="_blank" rel="noopener" aria-label="GitHub"><GithubIcon /></a>
            <Magnetic s={0.25}><a className="btn btn-solid nav-dl" href={DOWNLOAD}><span>Download</span><span className="btn-ico"><DownloadIcon /></span></a></Magnetic>
          </div>
        </div>
      </header>

      <nav className="spy-nav" aria-label="Sections">
        {SPY.map((s) => {
          const on = s.id === spyId;
          return (
            <a key={s.id} href={`#${s.id}`}>
              <span className={`spy-dot ${on ? "on" : ""}`} />
              <span className={`spy-num ${on ? "on" : ""}`}>{s.num}</span>
              <span className={`spy-label ${on ? "on" : ""}`}>{s.name}</span>
            </a>
          );
        })}
      </nav>

      <main id="top">
        {/* HERO */}
        <section className="hero" ref={heroRef}>
          <div className="hero-copy">
            <span className="hero-kicker"><span className="sw">स्वर</span>a note for every word · local &amp; free</span>
            <h1 className="hero-title">
              <span style={{ animation: "hrise 1.1s cubic-bezier(.19,1,.22,1) both" }}>Your voice,</span>
              <span style={{ animation: "hrise 1.2s cubic-bezier(.19,1,.22,1) both" }}>written like a <em>melody.</em></span>
            </h1>
            <p className="hero-lede" style={{ animation: "hfade 1.5s ease both" }}>Double-tap a key and speak. Svara transcribes in real time, entirely on your machine. No uploads. No servers. No fees.</p>
            <div className="hero-cta" style={{ animation: "hfade 1.6s ease both" }}>
              <Magnetic s={0.3}><a className="btn btn-solid" href={DOWNLOAD}><span>Download Svara.exe</span><span className="btn-ico"><DownloadIcon /></span></a></Magnetic>
              <a className="btn btn-ghost" href={GITHUB} target="_blank" rel="noopener">View source</a>
              {/* Inline in the CTA row rather than stacked beneath it: the hero
                  already carries a kicker, headline, lede, CTAs and stats, and
                  a sixth stacked element is where a hero starts to sprawl.
                  This is spec a visitor wants before a 103 MB download, not a
                  decorative version badge. */}
              <span className="hero-meta">v{VERSION} · Windows · {SIZE_MB} MB</span>
            </div>
            <div className="hero-stats" style={{ animation: "hfade 1.7s ease both" }}>
              <div><div className="n">0</div><div className="l">Bytes uploaded</div></div>
              <div><div className="n accent">~1s</div><div className="l">Latency</div></div>
              <div><div className="n">90+</div><div className="l">Languages</div></div>
            </div>
          </div>
          <div className="hero-panel" style={{ animation: "hfade 1.5s ease both" }}>
            <div className="hero-wave"
              onPointerMove={(e) => { const r = e.currentTarget.getBoundingClientRect(); setPointer((e.clientX - r.left) / r.width, 1); }}
              onPointerLeave={() => setPointer(0.5, 0)}>
              <div className="hero-grid"><div /><div /><div /><div /></div>
              <span className="hero-tag l"><span className="dot-live" />Signal preview</span>
              <span className="hero-tag r">Interactive</span>
              <Visualizer style="strings" hero className="wave-viz" />
              <HeroPill />
            </div>
            <div className="hero-panel-foot">
              <span className="hint">↳ drag the pill · explore the colours</span>
              <div className="mood-row">
                <span className="lbl">Mood</span>
                <div className="swatches">
                  {MOOD_ORDER.map((k) => <button key={k} className={`swatch ${mood === k ? "on" : ""}`} style={{ background: MOODS[k].accent }} aria-label={MOODS[k].name} onClick={() => morph(k)} />)}
                </div>
              </div>
            </div>
          </div>
        </section>

        <DictationDemo />

        {/* MARQUEE */}
        <div className="marquee" aria-hidden>
          <div className="marquee-track">
            {[0, 1].map((k) => (
              <span key={k}>
                {["Speak it", "written live", "on your machine", "no limits"].map((w, i) => <span key={i}>{w}<span className="dot">·</span></span>)}
              </span>
            ))}
          </div>
        </div>

        {/* MOVEMENTS / HOW */}
        <section id="how" className="sec">
          <Reveal className="sec-head">
            <div><span className="eyebrow">Op. 01 · The score</span><h2>Your voice in <em>three movements.</em></h2></div>
            <span className="aside">three distinct voices, one expression</span>
          </Reveal>
          <div className="moves-wrap">
            <div className="moves-lines" aria-hidden><div /><div /><div /><div /><div /></div>
            <div className="moves-grid">
              {STEPS.map((s, i) => (
                <Reveal key={s.n} delay={0.05}>
                  <div className="move-card" onPointerEnter={() => speak(1500)}>
                    <div className="move-top"><span className="move-n">{s.n}</span><span className="move-mvt">{s.mvt}</span></div>
                    <Visualizer style={s.viz} hero className="move-viz" />
                    <div><h3>{s.title}</h3><p>{s.body}</p></div>
                    <span className="move-tag">{s.tag}</span>
                  </div>
                </Reveal>
              ))}
            </div>
          </div>
        </section>

        {/* PRIVACY */}
        <section id="privacy" className="privacy">
          <div className="privacy-in">
            <Reveal><span className="eyebrow">Op. 02 · Private by nature</span></Reveal>
            <Reveal delay={0.05}><h2>Nothing ever leaves <em>your machine.</em></h2></Reveal>
            <Reveal delay={0.1}><p className="privacy-lede">Your audio is processed entirely on your machine. No uploads. No servers. No network required. Disconnect and it still works.</p></Reveal>
            <Reveal delay={0.14}>
              <div className="pipeline">
                <span className="pipeline-tag">Your machine · nothing crosses this line</span>
                <div className="pipeline-row">
                  <div className="pipe-step"><div className="k">Capture</div><div className="v">Microphone</div><div className="s">held in RAM</div></div>
                  <div className="pipe-link"><span /></div>
                  <div className="pipe-mid"><div className="k">Transcribe</div><Visualizer style="strings" hero className="pipe-viz" /><div className="v">Your GPU</div></div>
                  <div className="pipe-link b"><span /></div>
                  <div className="pipe-step"><div className="k">Write</div><div className="v">Your cursor</div><div className="s">any app, instantly</div></div>
                </div>
              </div>
            </Reveal>
            <Reveal delay={0.18}><p className="privacy-note">works with the network cable unplugged ✓</p></Reveal>
          </div>
        </section>

        {/* FEATURES */}
        <section id="features" className="sec">
          <Reveal><span className="eyebrow">Op. 03 · Capabilities</span><h2>What it <em>can do.</em></h2></Reveal>
          <div className="feat-grid" style={{ marginTop: "clamp(2rem,5vh,3.5rem)" }}
            onPointerEnter={() => { featHover.current = true; }}
            onPointerLeave={() => { featHover.current = false; }}>
            <Reveal delay={0.04} className="feat-list">
              {FEATURES.map((f, i) => (
                <button key={f.n} type="button" className={`feat-row ${i === feat ? "on" : ""}`}
                  onPointerEnter={() => { if (i !== feat) { setFeat(i); speak(1100); } }}
                  onClick={() => { if (i !== feat) { setFeat(i); speak(1100); } }}>
                  <span className="feat-n">{f.n}</span>
                  <span className="feat-title">{f.title}</span>
                  <span className="feat-arrow">→</span>
                </button>
              ))}
            </Reveal>
            <Reveal delay={0.08} className="feat-panel">
              <Visualizer style={FEAT_VIZ[feat]} hero className="feat-viz" />
              <div className="feat-panel-body">
                <div className="tag">{FEATURES[feat].tag}</div>
                <h3>{FEATURES[feat].title}</h3>
                <p>{FEATURES[feat].body}</p>
              </div>
            </Reveal>
          </div>
        </section>

        {/* STATS */}
        <section className="sec" style={{ padding: "clamp(3rem,7vh,5rem) var(--pad)" }}>
          <div className="stats-grid">
            {statsWith(downloads).map((s, i) => <Reveal key={i} delay={0.03}><CountStat {...s} /></Reveal>)}
          </div>
        </section>

        {/* COMPARE */}
        <section id="compare" className="sec">
          <Reveal><span className="eyebrow">Op. 04 · The difference</span><h2>Svara vs. <em>the cloud.</em></h2></Reveal>
          <Reveal delay={0.05} className="compare-table">
            <div className="compare-head"><div /><div className="svara-col">Svara</div><div>Cloud dictation</div></div>
            {COMPARE.map((c) => (
              <div className="compare-row" key={c.label}>
                <div className="label">{c.label}</div>
                <div className="svara-col">{c.svara}</div>
                <div className="cloud-col">{c.cloud}</div>
              </div>
            ))}
          </Reveal>
        </section>

        {/* CTA */}
        <section className="cta">
          <div className="cta-in">
            <Reveal><span className="eyebrow">Op. 05 · Get Svara</span></Reveal>
            <Reveal delay={0.05}><h2>Speak it. Ship it. <em>Free.</em></h2></Reveal>
            <Reveal delay={0.1}><p className="cta-lede">One download to get started. No account or GPU required. Svara installs itself, downloads your speech model once, then works offline.</p></Reveal>
            <Reveal delay={0.14}>
              <div className="cta-actions">
                <Magnetic s={0.3}><a className="btn btn-dark" href={DOWNLOAD}><span>Download Svara.exe</span><span className="btn-ico"><DownloadIcon /></span></a></Magnetic>
                <a className="btn btn-dark-ghost" href={GITHUB} target="_blank" rel="noopener">Star on GitHub</a>
              </div>
            </Reveal>
            <Reveal delay={0.18}><p className="cta-note">~{SIZE_MB} MB · Windows 10 / 11 · CPU ready · optional NVIDIA GPU support</p></Reveal>
          </div>
        </section>
      </main>

      <footer className="footer">
        <div className="foot-hero">
          <span className="eyebrow">Op. 06 · स्वर</span>
          <h3>Your voice stays <em>with you.</em></h3>
          <Magnetic s={0.25}><a className="btn btn-solid" href={DOWNLOAD}><span>Download for Windows</span><span className="btn-ico"><DownloadIcon /></span></a></Magnetic>
          <div className="mood-row">
            <span className="lbl">Mood</span>
            <div className="swatches">
              {MOOD_ORDER.map((k) => <button key={k} className={`swatch ${mood === k ? "on" : ""}`} style={{ background: MOODS[k].accent }} aria-label={MOODS[k].name} title={MOODS[k].name} onClick={() => morph(k)} />)}
            </div>
          </div>
        </div>
        <div className="foot-word-wrap">
          <div className="foot-word-inner">
            <span className="foot-word" aria-hidden>Svara</span>
            <Visualizer style="strings" hero className="foot-word-viz" />
          </div>
        </div>
        <div className="foot-bottom-wrap">
          <div className="foot-bottom">
            <div className="foot-links">
              <a href={GITHUB} target="_blank" rel="noopener">GitHub</a>
              <a href={`${GITHUB}/issues`} target="_blank" rel="noopener">Issues</a>
              <a href={`${GITHUB}/releases`} target="_blank" rel="noopener">Releases</a>
              <a href="https://github.com/SYSTRAN/faster-whisper" target="_blank" rel="noopener">Built on faster-whisper</a>
            </div>
            <span>© 2026 Svara · <span className="accent">your voice, your machine</span> · <a className="back" href="#top">back to top ↑</a></span>
            {/* Live totals. Rendered only once real numbers arrive, so the
                line is absent rather than showing placeholder zeros. */}
            {(downloads !== null || visits !== null) && (
              <span className="live">
                {downloads !== null &&
                  <>{downloads.toLocaleString()} download{downloads === 1 ? "" : "s"}</>}
                {downloads !== null && visits !== null && " · "}
                {visits !== null &&
                  <>{visits.unique.toLocaleString()} visitor{visits.unique === 1 ? "" : "s"}</>}
              </span>
            )}
          </div>
        </div>
      </footer>
    </>
  );
}

/* ---------- animated favicon (mood-recolored ribbons) ---------- */
function AnimatedFavicon({ mood }: { mood: string }) {
  const moodRef = useRef(mood); moodRef.current = mood;
  useEffect(() => {
    const c = document.createElement("canvas"); c.width = 64; c.height = 64;
    const x = c.getContext("2d"); if (!x) return;
    let link = document.querySelector<HTMLLinkElement>("link[rel~='icon']");
    if (!link) { link = document.createElement("link"); link.rel = "icon"; document.head.appendChild(link); }
    const prev = link.getAttribute("href");
    const t = 0.12;
    const draw = () => {
      const cols = MOODS[moodRef.current]?.cols || MOODS.sienna.cols;
      x.clearRect(0, 0, 64, 64);
      x.lineCap = "round"; x.lineJoin = "round";
      for (let i = 0; i < 3; i++) {
        const c = cols[i], ys = 1 - i * 0.14;
        x.beginPath();
        for (let j = 0; j <= 30; j++) { const u = j / 30, env = Math.pow(Math.sin(Math.PI * u), 0.82); const y = 32 + env * 16 * ys * (0.72 * Math.sin(7 * u + t + i * 0.9) + 0.44 * Math.sin(11 * u - t * 0.7)); const px = 3 + u * 58; j ? x.lineTo(px, y) : x.moveTo(px, y); }
        x.strokeStyle = c; x.globalCompositeOperation = "multiply"; x.globalAlpha = 0.4; x.lineWidth = 3.5; x.stroke();
        x.globalCompositeOperation = "source-over"; x.globalAlpha = 1; x.lineWidth = 1.6; x.stroke();
      }
      x.globalAlpha = 1;
      link!.href = c.toDataURL("image/png");
    };
    draw();
    return () => { if (prev) link!.setAttribute("href", prev); };
  }, [mood]);
  return null;
}
const DownloadIcon = () => <svg viewBox="0 0 24 24" width="16" height="16" fill="none"><path d="M12 4v11m0 0l-3.5-3.5M12 15l3.5-3.5M6 19h12" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" /></svg>;
const GithubIcon = () => <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M12 2a10 10 0 0 0-3.16 19.49c.5.09.68-.22.68-.48v-1.7c-2.78.6-3.37-1.34-3.37-1.34-.45-1.16-1.11-1.47-1.11-1.47-.91-.62.07-.6.07-.6 1 .07 1.53 1.03 1.53 1.03.9 1.53 2.36 1.09 2.94.83.09-.65.35-1.09.63-1.34-2.22-.25-4.55-1.11-4.55-4.94 0-1.09.39-1.98 1.03-2.68-.1-.25-.45-1.27.1-2.65 0 0 .84-.27 2.75 1.02a9.6 9.6 0 0 1 5 0c1.91-1.29 2.75-1.02 2.75-1.02.55 1.38.2 2.4.1 2.65.64.7 1.03 1.59 1.03 2.68 0 3.84-2.34 4.68-4.57 4.93.36.31.68.92.68 1.85v2.74c0 .27.18.58.69.48A10 10 0 0 0 12 2Z" /></svg>;

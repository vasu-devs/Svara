"use client";

import { useEffect, useRef, useState } from "react";
import { motion, useMotionValue, useSpring, useScroll, useMotionValueEvent, useReducedMotion } from "framer-motion";
import { Visualizer } from "@/components/Visualizer";
import { THEMES, STYLES, speak, setPointer } from "@/lib/engine";

const THEME_KEYS = ["aurora", "cyberpunk", "matrix", "sakura", "dracula", "vaporwave"];

function Reveal({ children, className, delay = 0 }: { children: React.ReactNode; className?: string; delay?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current; if (!el) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    if (el.getBoundingClientRect().top <= window.innerHeight * 0.86) return;
    el.style.transitionDelay = `${delay}s`; el.classList.add("rv-hidden");
    let done = false; const reveal = () => { if (done) return; done = true; el.classList.remove("rv-hidden"); };
    const io = new IntersectionObserver((es) => { if (es[0].isIntersecting) { reveal(); io.disconnect(); } }, { threshold: 0.1, rootMargin: "0px 0px -8% 0px" });
    io.observe(el); const fb = setTimeout(reveal, 2600);
    return () => { io.disconnect(); clearTimeout(fb); };
  }, [delay]);
  return <div ref={ref} className={`rv ${className || ""}`}>{children}</div>;
}

function Magnetic({ children, s = 0.3 }: { children: React.ReactNode; s?: number }) {
  const reduce = useReducedMotion();
  const x = useMotionValue(0), y = useMotionValue(0);
  const sx = useSpring(x, { stiffness: 200, damping: 13 }), sy = useSpring(y, { stiffness: 200, damping: 13 });
  const ref = useRef<HTMLSpanElement>(null);
  return <motion.span ref={ref} style={{ x: sx, y: sy, display: "inline-flex" }}
    onPointerMove={(e) => { if (reduce || !ref.current) return; const r = ref.current.getBoundingClientRect(); x.set((e.clientX - r.left - r.width / 2) * s); y.set((e.clientY - r.top - r.height / 2) * s * 1.1); }}
    onPointerLeave={() => { x.set(0); y.set(0); }}>{children}</motion.span>;
}

export default function Page() {
  const [theme, setTheme] = useState("aurora");
  function morph(key: string) { const t = THEMES[key]; document.documentElement.style.setProperty("--accent", t.accent); document.documentElement.style.setProperty("--dot", t.dot); setTheme(key); speak(1800); }
  useEffect(() => { document.documentElement.style.setProperty("--accent", THEMES.aurora.accent); document.documentElement.style.setProperty("--dot", THEMES.aurora.dot); }, []);

  return (
    <>
      <div className="bg-grid" aria-hidden />
      <div className="grain" aria-hidden />
      <AnimatedFavicon theme={theme} />

      <header className="nav-wrap">
        <div className="nav-pill">
          <a className="nav-brand" href="#top"><LogoMark theme={theme} /><span>Svara</span></a>
          <nav className="nav-mid"><a href="#meters">Meters</a><a href="#themes">Themes</a><a href="#how">How</a><a href="#get">Get it</a></nav>
          <Magnetic s={0.2}><a className="btn group btn-solid nav-dl" href="#get"><span>Download</span><span className="btn-ico"><DownloadIcon /></span></a></Magnetic>
        </div>
      </header>

      <main id="top">
        <Hero theme={theme} onTheme={morph} />

        <div className="bigmar" aria-hidden><div className="bigmar-track">{[0, 1].map((k) => <span className="u" key={k}>{[["Speak", "it"], ["it's", "written"], ["no", "cloud"], ["fully", "yours"]].map(([a, b], j) => <span className="u" key={j}>{a}&nbsp;<span className="o">{b}</span><span className="s" /></span>)}</span>)}</div></div>

        <Meters theme={theme} />

        {/* HOW */}
        <section className="moves" id="how">
          <Reveal className="moves-head"><span className="eyebrow">The whole app</span><h2 style={{ marginTop: "1.2rem" }}>Three moves, and your voice is <em>on the page.</em></h2></Reveal>
          {[
            [<span key="k">Double-tap <kbd>Right Alt</kbd></span>, "The pill appears and Svara starts listening. No window to find, no button to hunt for.", <span key="t" className="tag"><kbd>Right Alt</kbd><b>x2</b></span>],
            ["Just talk", "Words are written as you speak, punctuation and filler cleaned up on the fly. Raise your voice and it writes in caps.", <span key="t" className="tag"><b>~1s</b> spoken to written</span>],
            ["Tap to finish", "The text lands at your cursor in whatever app you are using. Slack, VS Code, a browser, a terminal.", <span key="t" className="tag">Works <b>everywhere</b></span>],
          ].map(([h, p, tag], i) => (
            <Reveal key={i}><div className="move"><span className="move-n">{`0${i + 1}`}</span><div><h3>{h}</h3><p>{p}</p>{tag}</div></div></Reveal>
          ))}
        </section>

        <Themes theme={theme} onTheme={morph} />

        {/* FEATURES */}
        <section className="kfeat">
          <Reveal className="kfeat-head"><span className="eyebrow">Capabilities</span><h2 style={{ marginTop: "1.2rem" }}>Everything it <em>does.</em></h2></Reveal>
          <Reveal className="kfeat-grid">{[
            ["Runs on your own machine", "Audio is captured, written, and discarded locally. It cannot reach a server, because there is no server. Nothing to upload, ever."],
            ["Instant on your GPU", "faster-whisper on CTranslate2, large-v3-turbo at int8 in ~1.5 GB of VRAM. Roughly a second from spoken to written."],
            ["Ninety-plus languages", "Dictate in any language Whisper understands, or let it auto-detect what you speak each time. Not just English."],
            ["Speak-to-translate", "Flip one switch and talk in any language: Svara writes clean English at your cursor. Your Spanish, its English."],
            ["Any Whisper model", "From tiny to distil-large-v3 to large-v3-turbo. Trade speed for accuracy to fit whatever GPU you have."],
            ["Shout to CAPITALISE", "Raise your voice on a word and it lands IN CAPS. Loudness-aware and shout-proof, so only real emphasis counts."],
            ["Cleaned up as you talk", "Automatic punctuation, filler removal (um, uh), and self-corrections on the fly. Optional local-LLM polish via Ollama, still offline."],
            ["Writes into every app", "System-wide injection places your words at the cursor anywhere you can type: Slack, VS Code, browsers, terminals."],
            ["Eight meters, your theme", "Eight live visualizers and pop-culture themes: Matrix, Cyberpunk, Sakura, Evangelion, Saiyan, Vaporwave, and clean minimal."],
            ["Free and open source", "No account, no subscription, no telemetry on your voice. The whole thing is yours to read, fork, and build."],
          ].map(([h, p], i) => <div className="kf" key={h}><span className="kf-n">{String(i + 1).padStart(2, "0")}</span><div><h3>{h}</h3><p>{p}</p></div></div>)}</Reveal>
        </section>

        {/* CTA */}
        <section className="kcta" id="get">
          <Reveal><span className="eyebrow">Get Svara</span></Reveal>
          <Reveal delay={0.05}><h2>Speak it.<br />Ship it. <em>Free.</em></h2></Reveal>
          <Reveal delay={0.1}><p>Windows 10 and 11. NVIDIA GPU for the fast path, CPU still works. The model downloads once, then it runs fully offline.</p></Reveal>
          <Reveal delay={0.15}><div className="kcta-actions">
            <Magnetic><a className="btn group btn-solid" style={{ fontSize: "1.05rem", padding: ".85rem .85rem .85rem 1.6rem" }} href="https://github.com/vasu-devs/Svara/releases" target="_blank" rel="noopener"><span>Download for Windows</span><span className="btn-ico"><DownloadIcon /></span></a></Magnetic>
            <a className="btn btn-ghost" style={{ fontSize: "1.05rem", padding: ".85rem 1.7rem" }} href="https://github.com/vasu-devs/Svara" target="_blank" rel="noopener">Star on GitHub</a>
          </div></Reveal>
          <Reveal delay={0.2}><p className="kcta-note">Open source · built on faster-whisper · your voice never leaves your machine</p></Reveal>
        </section>
      </main>

      <footer className="footer">
        <div className="foot-top">
          <div className="foot-brand">
            <div className="foot-brandrow"><LogoMark theme={theme} /><span>Svara</span></div>
            <p className="foot-tag">Private voice dictation that runs on your own machine. Speak, and it is written, the instant you say it.</p>
            <Magnetic><a className="btn group btn-solid" href="#get"><span>Download for Windows</span><span className="btn-ico"><DownloadIcon /></span></a></Magnetic>
            <div className="foot-themes">
              <span className="lbl">Theme</span>
              <div className="swatches">{THEME_KEYS.map((k) => <button key={k} className={`swatch ${theme === k ? "on" : ""}`} aria-label={THEMES[k].name} style={{ background: THEMES[k].accent }} onClick={() => morph(k)} />)}</div>
            </div>
          </div>
          <div className="foot-col"><h4>Product</h4><a href="#get">Download</a><a href="#meters">Meters</a><a href="#themes">Themes</a><a href="#how">How it works</a></div>
          <div className="foot-col"><h4>Source</h4><a href="https://github.com/vasu-devs/Svara" target="_blank" rel="noopener">GitHub</a><a href="https://github.com/vasu-devs/Svara/issues" target="_blank" rel="noopener">Issues</a><a href="https://github.com/vasu-devs/Svara/releases" target="_blank" rel="noopener">Releases</a></div>
          <div className="foot-col"><h4>Built on</h4><a href="https://github.com/SYSTRAN/faster-whisper" target="_blank" rel="noopener">faster-whisper</a><a href="https://github.com/OpenNMT/CTranslate2" target="_blank" rel="noopener">CTranslate2</a><a href="https://github.com/snakers4/silero-vad" target="_blank" rel="noopener">Silero VAD</a></div>
        </div>
        <div className="foot-word" aria-hidden>Svara</div>
        <div className="foot-bottom">
          <span>Open source · no account · <span className="b">your voice never leaves your machine</span></span>
          <span>© 2026 Svara · built on faster-whisper</span>
        </div>
      </footer>
    </>
  );
}

/* ---------- kinetic hero ---------- */

function Hero({ theme, onTheme }: { theme: string; onTheme: (k: string) => void }) {
  const reduce = useReducedMotion();
  const waveRef = useRef<HTMLDivElement>(null);
  const PHRASES = ["your own GPU did all the work.", "nothing ever left your laptop.", "punctuation, added automatically.", "said out loud, written in a blink."];
  const [typed, setTyped] = useState(reduce ? PHRASES[0] : "");
  useEffect(() => {
    if (reduce) return;
    let pi = 0, ci = 0, dir = 1, timer: ReturnType<typeof setTimeout>;
    const tick = () => {
      const p = PHRASES[pi]; setTyped(p.slice(0, ci));
      if (dir > 0) { if (ci === 0) speak(p.length * 52 + 500); ci++; if (ci > p.length) { dir = -1; timer = setTimeout(tick, 1600); return; } }
      else { ci--; if (ci < 0) { ci = 0; dir = 1; pi = (pi + 1) % PHRASES.length; timer = setTimeout(tick, 320); return; } }
      timer = setTimeout(tick, dir > 0 ? 46 : 22);
    };
    tick(); return () => clearTimeout(timer);
  }, [reduce]);
  return (
    <section className="khero">
      <span className="eyebrow kh-eyebrow">Voice dictation · Windows · Local &amp; free</span>
      <h1 className="kh-title">
        <span className="kh-mask"><span className="kh-in">Speak.</span></span>
        <span className="kh-mask"><span className="kh-in">It&apos;s <em>written.</em></span></span>
      </h1>
      <div className="kh-wave" ref={waveRef}
        onPointerMove={(e) => { if (reduce || !waveRef.current) return; const r = waveRef.current.getBoundingClientRect(); setPointer((e.clientX - r.left) / r.width, 1); }}
        onPointerLeave={() => setPointer(0.5, 0)}>
        <Visualizer style="strings" themeKey={theme} hero />
      </div>
      <div className="kh-live">
        <span className="kh-rec"><i />Transcribing</span>
        <span className="kh-type">{typed}<span className="kh-caret" /></span>
      </div>
      <div className="kh-foot">
        <div>
          <p className="kh-lede">Svara floats over any app and writes down what you say, the instant you say it, on your own GPU. Nothing ever leaves your machine.</p>
          <div className="kh-themes">
            <span className="lbl">Theme</span>
            <div className="swatches">{THEME_KEYS.map((k) => <button key={k} className={`swatch ${theme === k ? "on" : ""}`} aria-label={THEMES[k].name} style={{ background: THEMES[k].accent }} onClick={() => onTheme(k)} />)}</div>
          </div>
        </div>
        <div className="kh-foot-r">
          <div className="kh-stats">
            <div><b>0</b><span>bytes uploaded</span></div>
            <div><b>~1s</b><span>spoken to written</span></div>
            <div><b>90+</b><span>languages</span></div>
            <div><b>100%</b><span>on your machine</span></div>
          </div>
          <div className="kh-cta">
            <Magnetic><a className="btn group btn-solid" href="#get"><span>Download</span><span className="btn-ico"><DownloadIcon /></span></a></Magnetic>
            <a className="btn btn-ghost" href="https://github.com/vasu-devs/Svara" target="_blank" rel="noopener">View source</a>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ---------- pinned meters morph ---------- */

function Meters({ theme }: { theme: string }) {
  const wrap = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({ target: wrap, offset: ["start start", "end end"] });
  const [idx, setIdx] = useState(0);
  useMotionValueEvent(scrollYProgress, "change", (p) => setIdx(Math.min(STYLES.length - 1, Math.max(0, Math.floor(p * STYLES.length * 0.999)))));
  const CAP = ["woven strings", "stacked bars", "mirror spectrum", "raw oscilloscope", "radiating pulse", "drifting particles", "focused beam", "pixel bins"];
  return (
    <section className="kshow" id="meters" ref={wrap} style={{ height: `${STYLES.length * 60}vh` }}>
      <div className="kshow-pin">
        <div className="kshow-top">
          <span className="eyebrow">Live meters</span>
          <span className="kshow-idx"><b>{String(idx + 1).padStart(2, "0")}</b> / 08</span>
        </div>
        <div className="kshow-wave"><Visualizer style={STYLES[idx]} themeKey={theme} hero /></div>
        <h2 className="kshow-name">{STYLES[idx]}<span className="sub">{CAP[idx]} · one of eight ways Svara draws your voice</span></h2>
      </div>
    </section>
  );
}

/* ---------- themes ---------- */

function Themes({ theme, onTheme }: { theme: string; onTheme: (k: string) => void }) {
  return (
    <section className="kthemes" id="themes">
      <Reveal className="kthemes-head"><span className="eyebrow">Make it yours</span><h2 style={{ marginTop: "1.2rem" }}>Every colour recolors <em>everything.</em></h2></Reveal>
      <Reveal className="kthemes-grid">{THEME_KEYS.map((k) => (
        <button className={`kth ${theme === k ? "on" : ""}`} key={k} onClick={() => onTheme(k)}>
          <div className="kth-viz"><Visualizer style="strings" themeKey={k} /></div>
          <div className="kth-row"><span className="kth-name">{THEMES[k].name}</span><span className="kth-tag">{THEMES[k].accent}</span></div>
        </button>
      ))}</Reveal>
    </section>
  );
}

/* ---------- animated logo + favicon + icons ---------- */
const LogoMark = ({ theme }: { theme: string }) => (
  <span className="logo-orb"><Visualizer style="strings" themeKey={theme} /></span>
);

// Live animated favicon: renders the ribbons to a tiny canvas and swaps the tab icon each frame.
function AnimatedFavicon({ theme }: { theme: string }) {
  const themeRef = useRef(theme); themeRef.current = theme;
  useEffect(() => {
    const c = document.createElement("canvas"); c.width = 64; c.height = 64;
    const x = c.getContext("2d"); if (!x) return;
    let link = document.querySelector<HTMLLinkElement>("link[rel~='icon']");
    if (!link) { link = document.createElement("link"); link.rel = "icon"; document.head.appendChild(link); }
    const prev = link.getAttribute("href");
    let t = 0; let id: ReturnType<typeof setTimeout>;
    const draw = () => {
      t += 0.12;
      const cols = (THEMES[themeRef.current] || THEMES.aurora).cols;
      x.clearRect(0, 0, 64, 64); // no chip: distinct glowing ribbons on transparent
      x.lineCap = "round"; x.lineJoin = "round";
      for (let i = 0; i < 3; i++) {
        const c = cols[i], ys = 1 - i * 0.14;
        x.beginPath();
        for (let j = 0; j <= 30; j++) { const u = j / 30, env = Math.pow(Math.sin(Math.PI * u), 0.82); const y = 32 + env * 16 * ys * (0.72 * Math.sin(7 * u + t + i * 0.9) + 0.44 * Math.sin(11 * u - t * 0.7)); const px = 3 + u * 58; j ? x.lineTo(px, y) : x.moveTo(px, y); }
        x.strokeStyle = c; x.shadowColor = c; x.shadowBlur = 8; x.globalAlpha = 0.85; x.lineWidth = 2.3; x.stroke();
        x.shadowBlur = 0; x.globalAlpha = 1; x.lineWidth = 1.3; x.stroke();
      }
      x.shadowBlur = 0; x.globalAlpha = 1;
      link!.href = c.toDataURL("image/png");
      id = setTimeout(draw, 120);
    };
    draw();
    return () => { clearTimeout(id); if (prev) link!.setAttribute("href", prev); };
  }, []);
  return null;
}
const DownloadIcon = () => <svg viewBox="0 0 24 24" fill="none"><path d="M12 4v11m0 0l-3.5-3.5M12 15l3.5-3.5M6 19h12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>;

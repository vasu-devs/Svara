"use client";

import { useEffect, useRef, useState } from "react";
import { motion, useMotionValue, useSpring, useScroll, useMotionValueEvent, useInView, animate, useReducedMotion } from "framer-motion";
import { Visualizer } from "@/components/Visualizer";
import { THEMES, STYLES, speak, setPointer } from "@/lib/engine";

const EASE = [0.32, 0.72, 0, 1] as const;
const THEME_KEYS = ["aurora", "cyberpunk", "matrix", "sakura", "dracula", "vaporwave"];

function Reveal({ children, className, delay = 0 }: { children: React.ReactNode; className?: string; delay?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current; if (!el) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    if (el.getBoundingClientRect().top <= window.innerHeight * 0.84) return;
    el.style.transitionDelay = `${delay}s`; el.classList.add("rv-hidden");
    let done = false; const reveal = () => { if (done) return; done = true; el.classList.remove("rv-hidden"); };
    const io = new IntersectionObserver((es) => { if (es[0].isIntersecting) { reveal(); io.disconnect(); } }, { threshold: 0.12, rootMargin: "0px 0px -7% 0px" });
    io.observe(el); const fb = setTimeout(reveal, 2600);
    return () => { io.disconnect(); clearTimeout(fb); };
  }, [delay]);
  return <div ref={ref} className={`rv ${className || ""}`}>{children}</div>;
}

function Magnetic({ children, s = 0.3 }: { children: React.ReactNode; s?: number }) {
  const reduce = useReducedMotion();
  const x = useMotionValue(0), y = useMotionValue(0);
  const sx = useSpring(x, { stiffness: 220, damping: 14 }), sy = useSpring(y, { stiffness: 220, damping: 14 });
  const ref = useRef<HTMLSpanElement>(null);
  return <motion.span ref={ref} style={{ x: sx, y: sy, display: "inline-flex" }}
    onPointerMove={(e) => { if (reduce || !ref.current) return; const r = ref.current.getBoundingClientRect(); x.set((e.clientX - r.left - r.width / 2) * s); y.set((e.clientY - r.top - r.height / 2) * s * 1.1); }}
    onPointerLeave={() => { x.set(0); y.set(0); }}>{children}</motion.span>;
}

function CountUp({ to, dec = 0, suffix = "" }: { to: number; dec?: number; suffix?: string }) {
  const ref = useRef<HTMLElement>(null);
  const inView = useInView(ref, { once: true, amount: 0.6 });
  const [v, setV] = useState(0);
  useEffect(() => { if (!inView) return; const c = animate(0, to, { duration: 1.2, ease: EASE, onUpdate: setV }); return () => c.stop(); }, [inView, to]);
  return <b ref={ref}>{v.toFixed(dec)}{suffix}</b>;
}

export default function Page() {
  const [theme, setTheme] = useState("aurora");
  function morph(key: string) { const t = THEMES[key]; document.documentElement.style.setProperty("--accent", t.accent); document.documentElement.style.setProperty("--dot", t.dot); setTheme(key); speak(1600); }
  useEffect(() => { document.documentElement.style.setProperty("--accent", THEMES.aurora.accent); document.documentElement.style.setProperty("--dot", THEMES.aurora.dot); }, []);

  return (
    <>
      <div className="bg-grid" aria-hidden />
      <div className="bg-waves" aria-hidden />
      <div className="grain" aria-hidden />

      <header className="nav-wrap">
        <div className="nav-pill">
          <a className="nav-brand" href="#top"><span className="nav-orb"><Visualizer style="scope" themeKey={theme} /></span><span>Svara</span></a>
          <nav className="nav-mid"><a href="#demo">Demo</a><a href="#showcase">Visualizers</a><a href="#themes">Themes</a><a href="#tech">Tech</a></nav>
          <Magnetic s={0.2}><a className="btn group btn-solid nav-dl" href="#download"><span>Download</span><span className="btn-ico"><DownloadIcon /></span></a></Magnetic>
        </div>
      </header>

      <main id="top">
        <Hero theme={theme} onTheme={morph} />

        <div className="marquee" aria-hidden><div className="marquee-track">{[0, 1].map((k) => <span className="mi" key={k}>{["Local", "Private", "Instant", "Free", "Open source", "Streaming", "Offline", "Yours"].map((w) => <span key={w}><span>{w}</span><span className="dot" /></span>)}</span>)}</div></div>

        <section className="demo" id="demo">
          <Reveal className="section-head"><span className="eyebrow">Live, on this page</span><h2>It writes as fast as you <em>speak.</em></h2><p className="section-sub">The pill above is the real overlay from the app. It draws your voice and sets the words at your cursor, about a second behind you.</p></Reveal>
          <div className="demo-rows">
            {[["01", "Nothing to wait on", "No audio leaves the machine, so there is no network trip. The only delay is your GPU, and it is quick."], ["02", "Written while you talk", "Words are set as soon as two passes agree, so the text lands before you finish the sentence."], ["03", "It hears your emphasis", "Raise your voice on a word and Svara writes it in capitals. Punctuation and filler cleanup are automatic."]].map(([n, h, p], i) => (
              <Reveal className="demo-row" key={n} delay={i * 0.06}><span className="n">{n}</span><div><h3>{h}</h3><p>{p}</p></div></Reveal>
            ))}
          </div>
        </section>

        <Showcase theme={theme} />

        <section className="themes" id="themes">
          <Reveal className="section-head"><span className="eyebrow">Make it yours</span><h2>Recolor it in <em>one tap.</em></h2><p className="section-sub">Tap a theme. The pill, the ribbons, and the whole page shift together, exactly like the tray menu on your desktop.</p></Reveal>
          <Reveal className="theme-grid">{THEME_KEYS.map((k) => (
            <button className={`theme bezel ${theme === k ? "active" : ""}`} key={k} onClick={() => morph(k)}><div className="core"><div className="theme-prev"><Visualizer style="strings" themeKey={k} /></div><div className="theme-row"><span className="theme-name">{THEMES[k].name}</span><span className="theme-tag">{THEMES[k].accent}</span></div></div></button>
          ))}</Reveal>
        </section>

        <section className="how">
          <Reveal className="section-head"><span className="eyebrow">The whole app</span><h2>Three moves. That is <em>it.</em></h2></Reveal>
          <Reveal className="steps">
            {[[<span key="k" className="key"><kbd>Right Alt</kbd><span className="x2">x2</span></span>, "Double-tap to start", "The pill appears and Svara begins listening. No window to find, no button to hunt for."], [<MicIcon key="m" />, "Speak naturally", "Words are written as you talk, cleaned up on the fly. Pause whenever, it waits for you."], [<SendIcon key="s" />, "Tap to finish", "The text is set at your cursor, in whatever you are using. Slack, VS Code, a browser, a terminal."]].map(([icon, h, p], i) => (
              <div className="step bezel" key={i}><div className="core"><span className="sn">{`0${i + 1}`}</span>{icon}<h3>{h}</h3><p>{p}</p></div></div>
            ))}
          </Reveal>
        </section>

        <section className="features">
          <Reveal className="section-head"><span className="eyebrow">Engineering</span><h2>Built to <em>disappear.</em></h2></Reveal>
          <Reveal className="feat-grid">{[
            ["Private by architecture", "Your audio is captured, written, and discarded on your own machine. It cannot reach a server, because there is no server.", "lead"],
            ["Fast on your own GPU", "faster-whisper on CTranslate2, large-v3-turbo. Roughly a second from spoken to written.", "wide"],
            ["Works in every app", "System-wide text injection sets your words at the cursor anywhere you can type.", "wide"],
            ["A pill you enjoy", "Eight visualizers, a dozen themes, a draggable overlay that dodges your cursor.", ""],
            ["Always on, out of the way", "Lives in the tray, restarts itself, watches one key with no keyboard hook.", ""],
            ["Free and open", "No subscription, no account, no telemetry. Yours to read and build.", ""],
          ].map(([h, p, cls], i) => (
            <div className={`feat ${cls} bezel`} key={h}><div className="core"><span className="fn">{`0${i + 1}`}</span>{cls === "lead" && <div className="fviz"><Visualizer style="spectrum" themeKey={theme} /></div>}<h3>{h}</h3><p>{p}</p></div></div>
          ))}</Reveal>
        </section>

        <section className="compare">
          <Reveal className="section-head"><span className="eyebrow">The difference</span><h2>Private by <em>design.</em></h2><p className="section-sub">Most dictation tools ship your voice to a company's servers and bill you monthly. Svara does not.</p></Reveal>
          <Reveal className="compare-table">
            <div className="ct-row ct-head"><span /><span>Svara</span><span className="ct-other">Cloud dictation</span></div>
            {[["Where your audio goes", "Your GPU", "A company's servers"], ["Works offline", "Yes", "No"], ["Price", "Free", "Subscription"], ["Source code", "Open, auditable", "Closed"], ["Latency comes from", "Local compute", "A network trip"]].map(([k, a, b]) => <div className="ct-row" key={k}><span className="ct-key">{k}</span><span className="ct-yes">{a}</span><span className="ct-no">{b}</span></div>)}
          </Reveal>
        </section>

        <section className="tech" id="tech">
          <Reveal className="section-head"><span className="eyebrow">Under the hood</span><h2>For the people who read the <em>source.</em></h2></Reveal>
          <Reveal className="tech-grid">{[
            ["stt", "faster-whisper on CTranslate2, large-v3-turbo at int8, warmed up at launch for an instant first word."],
            ["vad", "Silero voice activity detection with a pre-roll buffer, so the first syllable is never clipped."],
            ["input", "Poll-only hotkey via GetAsyncKeyState. No system-wide hook, so it never interferes with your typing."],
            ["output", "Win32 SendInput and clipboard paste for character-perfect injection into any focused app."],
            ["ui", "Per-pixel alpha overlay via Pillow and UpdateLayeredWindow. Smooth edges, no jagged pixels."],
            ["ship", "Packaged with PyInstaller into one folder. Your users double-click an exe. No Python required."],
          ].map(([tag, p]) => <div className="tech-item bezel" key={tag}><div className="core"><span className="tech-tag">{tag}</span><p>{p}</p></div></div>)}</Reveal>
        </section>

        <section className="download" id="download">
          <Reveal className="dl-bezel bezel">
            <div className="core dl-inner">
              <span className="eyebrow">Get Svara</span>
              <h2>Give your voice somewhere to <em>land.</em></h2>
              <p>Windows 10 and 11, with an NVIDIA GPU for the fast path. No GPU still works, just slower on the CPU.</p>
              <div className="dl-actions">
                <Magnetic><a className="btn group btn-solid btn-lg" href="https://github.com/vasu-devs/Svara/releases" target="_blank" rel="noopener"><span>Download for Windows</span><span className="btn-ico"><DownloadIcon /></span></a></Magnetic>
                <a className="btn btn-ghost btn-lg" href="https://github.com/vasu-devs/Svara" target="_blank" rel="noopener">Star on GitHub</a>
              </div>
              <p className="dl-note">First launch downloads the speech model once. After that Svara runs fully offline.</p>
            </div>
          </Reveal>
        </section>
      </main>

      <footer className="footer">
        <div className="foot-top"><div className="foot-brand"><span className="nav-orb"><Visualizer style="scope" themeKey={theme} /></span><span>Svara</span></div><div className="foot-links"><a href="https://github.com/vasu-devs/Svara" target="_blank" rel="noopener">GitHub</a><a href="https://github.com/vasu-devs/Svara/issues" target="_blank" rel="noopener">Issues</a><a href="#download">Download</a></div></div>
        <p className="foot-fine">Private voice dictation that runs on your own machine. Open source, built on faster-whisper. Your voice stays with you.</p>
      </footer>
    </>
  );
}

/* ---------- hero ---------- */

function Hero({ theme, onTheme }: { theme: string; onTheme: (k: string) => void }) {
  const reduce = useReducedMotion();
  const MSG = "Hey Alex, just wrapped the Q3 deck. Can you take a look before the sync tomorrow?";
  const [len, setLen] = useState(reduce ? MSG.length : 0);
  useEffect(() => {
    if (reduce) return;
    let i = 0, hold = 0, timer: ReturnType<typeof setTimeout>;
    const tick = () => {
      if (hold > 0) { hold--; timer = setTimeout(tick, 40); return; }
      if (i <= MSG.length) { if (i === 1) speak(MSG.length * 46 + 800); setLen(i); i++; timer = setTimeout(tick, MSG[i - 1] === " " ? 38 : 46); if (i > MSG.length) hold = 60; }
      else { i = 0; setLen(0); hold = 8; timer = setTimeout(tick, 40); }
    };
    tick(); return () => clearTimeout(timer);
  }, [reduce]);
  const stageRef = useRef<HTMLDivElement>(null);

  return (
    <section className="hero">
      <div className="hero-inner">
        <div className="hero-copy">
          <span className="eyebrow enter">Voice dictation · Windows</span>
          <h1 className="hero-title enter">Speak.<br />It&apos;s <em>written.</em></h1>
          <p className="lede enter">Svara floats over any app and writes down what you say, live, on your own GPU. No cloud, no account.</p>
          <div className="hero-actions enter">
            <Magnetic><a className="btn group btn-solid btn-lg" href="#download"><span>Download for Windows</span><span className="btn-ico"><DownloadIcon /></span></a></Magnetic>
            <a className="btn btn-ghost btn-lg" href="https://github.com/vasu-devs/Svara" target="_blank" rel="noopener">View source</a>
          </div>
          <div className="hero-themes enter">
            <span className="lbl">Theme</span>
            <div className="swatches">{THEME_KEYS.map((k) => { const c = THEMES[k].cols; return <button key={k} className={`swatch ${theme === k ? "on" : ""}`} aria-label={THEMES[k].name} style={{ background: `linear-gradient(120deg, ${c[0]}, ${c[1]}, ${c[2]})` }} onClick={() => onTheme(k)} />; })}</div>
          </div>
        </div>

        <div className="scene enter" ref={stageRef}
          onPointerMove={(e) => { if (reduce || !stageRef.current) return; const r = stageRef.current.getBoundingClientRect(); setPointer((e.clientX - r.left) / r.width, 1); }}
          onPointerLeave={() => setPointer(0.5, 0)}>
          <div className="appwin bezel">
            <div className="core">
              <div className="win-bar"><span className="tl"><i /><i /><i /></span><span className="title">New message</span></div>
              <div className="win-body">
                <div className="win-meta">To: <b>alex@studio.io</b>   Subject: <b>Q3 deck</b></div>
                <div className="win-text"><span>{MSG.slice(0, len)}</span><span className="cursor" /></div>
              </div>
            </div>
          </div>
          <div className="pill-bezel">
            <div className="pill">
              <span className="pill-dot" />
              <Visualizer style="strings" themeKey={theme} hero className="pill-canvas" />
              <div className="pill-ctl"><i className="g" /><i className="d" /><i className="m" /></div>
            </div>
          </div>
        </div>
      </div>

      <div className="hero-stats">
        {[[<CountUp key="a" to={0} />, "bytes uploaded"], [<CountUp key="b" to={0.3} dec={1} suffix="s" />, "per 5s of speech"], [<CountUp key="c" to={1.2} dec={1} suffix="GB" />, "VRAM used"], [<CountUp key="d" to={12} />, "themes, 8 meters"]].map(([v, l], i) => <Reveal className="hstat" key={i} delay={i * 0.05}>{v}<span>{l}</span></Reveal>)}
      </div>
    </section>
  );
}

/* ---------- showcase ---------- */

function Showcase({ theme }: { theme: string }) {
  const wrap = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({ target: wrap, offset: ["start start", "end end"] });
  const [idx, setIdx] = useState(0);
  useMotionValueEvent(scrollYProgress, "change", (p) => setIdx(Math.min(STYLES.length - 1, Math.max(0, Math.floor(p * STYLES.length)))));
  return (
    <section className="showcase" id="showcase" ref={wrap} style={{ height: STYLES.length * 460 }}>
      <div className="showcase-sticky">
        <div className="showcase-head"><span className="eyebrow">Meters</span><h2>Eight ways to see a <em>voice.</em></h2><p className="section-sub">Scroll through every visualizer that ships in the app. All live, all yours.</p></div>
        <div className="showcase-stage">
          <div className="instrument bezel"><div className="core"><div className="ihead"><span className="live">Live</span><span>{STYLES[idx]}</span></div><Visualizer style={STYLES[idx]} themeKey={theme} hero /></div></div>
          <div className="showcase-meta"><span className="showcase-num">{String(idx + 1).padStart(2, "0")}<span className="slash">/08</span></span><span className="showcase-name">{STYLES[idx]}</span></div>
          <ol className="showcase-list">{STYLES.map((s, i) => <li key={s} className={i === idx ? "on" : ""}>{s}</li>)}</ol>
        </div>
      </div>
    </section>
  );
}

/* ---------- icons (ultra-light) ---------- */
const DownloadIcon = () => <svg viewBox="0 0 24 24" fill="none"><path d="M12 4v11m0 0l-3.5-3.5M12 15l3.5-3.5M6 19h12" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" /></svg>;
const MicIcon = () => <span className="step-icon"><svg viewBox="0 0 24 24" fill="none"><path d="M12 3.5v9M12 12.5c-2 0-3.5-1.6-3.5-3.5V7a3.5 3.5 0 0 1 7 0v2c0 1.9-1.5 3.5-3.5 3.5Z" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" /><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" /></svg></span>;
const SendIcon = () => <span className="step-icon"><svg viewBox="0 0 24 24" fill="none"><path d="M4 7h11M4 12h9M4 17h13" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" /><path d="M17 15.5l2 2 3.2-4" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" /></svg></span>;

"use client";

import { useEffect, useRef, useState } from "react";
import {
  motion, useMotionValue, useSpring, useScroll, useMotionValueEvent,
  useInView, animate, useReducedMotion, AnimatePresence, type MotionValue,
} from "framer-motion";
import { Visualizer } from "@/components/Visualizer";
import { THEMES, STYLES, speak, setPointer } from "@/lib/engine";

const EASE = [0.16, 1, 0.3, 1] as const;
const THEME_KEYS = ["aurora", "cyberpunk", "matrix", "sakura", "dracula", "vaporwave"];

/* ---------- small building blocks ---------- */

/* Native-IO reveal that DEFAULTS TO VISIBLE. Only elements currently below
   the fold get hidden-then-revealed on scroll; a fallback timer guarantees
   everything becomes visible even if the observer never fires. Content
   visibility is never at the mercy of an animation. */
function Reveal({ children, className, delay = 0 }: { children: React.ReactNode; className?: string; delay?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current; if (!el) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const rect = el.getBoundingClientRect();
    if (rect.top <= window.innerHeight * 0.82) return; // in/near view: stay visible, no flash
    el.style.transitionDelay = `${delay}s`;
    el.classList.add("rv-hidden");
    let done = false;
    const reveal = () => { if (done) return; done = true; el.classList.remove("rv-hidden"); };
    const io = new IntersectionObserver((es) => { if (es[0].isIntersecting) { reveal(); io.disconnect(); } }, { threshold: 0.14, rootMargin: "0px 0px -6% 0px" });
    io.observe(el);
    const fb = setTimeout(reveal, 2400);
    return () => { io.disconnect(); clearTimeout(fb); };
  }, [delay]);
  return <div ref={ref} className={`rv ${className || ""}`}>{children}</div>;
}

function Magnetic({ children, className, strength = 0.3 }: { children: React.ReactNode; className?: string; strength?: number }) {
  const reduce = useReducedMotion();
  const x = useMotionValue(0), y = useMotionValue(0);
  const sx = useSpring(x, { stiffness: 220, damping: 16 }), sy = useSpring(y, { stiffness: 220, damping: 16 });
  const ref = useRef<HTMLDivElement>(null);
  return (
    <motion.div ref={ref} className={className} style={{ x: sx, y: sy, display: "inline-flex" }}
      onPointerMove={(e) => {
        if (reduce || !ref.current) return;
        const r = ref.current.getBoundingClientRect();
        x.set((e.clientX - r.left - r.width / 2) * strength);
        y.set((e.clientY - r.top - r.height / 2) * strength * 1.3);
      }}
      onPointerLeave={() => { x.set(0); y.set(0); }}>
      {children}
    </motion.div>
  );
}

function CountUp({ to, dec = 0, suffix = "" }: { to: number; dec?: number; suffix?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true, amount: 0.6 });
  const [val, setVal] = useState(0);
  useEffect(() => {
    if (!inView) return;
    const controls = animate(0, to, { duration: 1.1, ease: EASE, onUpdate: (v) => setVal(v) });
    return () => controls.stop();
  }, [inView, to]);
  return <span ref={ref}>{val.toFixed(dec)}{suffix}</span>;
}

function Spotlight({ children, className }: { children: React.ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  return (
    <div ref={ref} className={`cell spotlight ${className || ""}`}
      onPointerMove={(e) => {
        const r = ref.current!.getBoundingClientRect();
        ref.current!.style.setProperty("--mx", e.clientX - r.left + "px");
        ref.current!.style.setProperty("--my", e.clientY - r.top + "px");
      }}>
      {children}
    </div>
  );
}

/* ---------- page ---------- */

export default function Page() {
  const reduce = useReducedMotion();
  const [theme, setThemeState] = useState("aurora");
  const [flash, setFlash] = useState<{ key: number; color: string } | null>(null);
  const themeRef = useRef(theme); themeRef.current = theme;

  function morphTheme(key: string) {
    const th = THEMES[key];
    document.documentElement.style.setProperty("--accent", th.accent);
    document.documentElement.style.setProperty("--accent-soft", th.accent + "24");
    document.documentElement.style.setProperty("--dot", th.dot);
    setThemeState(key);
    setFlash({ key: Date.now(), color: th.accent });
    speak(1600);
  }

  // nav shadow
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 12);
    on(); window.addEventListener("scroll", on, { passive: true });
    return () => window.removeEventListener("scroll", on);
  }, []);

  // set initial dot var
  useEffect(() => { document.documentElement.style.setProperty("--dot", THEMES.aurora.dot); }, []);

  return (
    <>
      <div className="grain" aria-hidden />
      <CursorGlow />
      <AnimatePresence>
        {flash && (
          <motion.div key={flash.key} className="theme-flash" aria-hidden
            style={{ background: `radial-gradient(circle at 50% 40%, ${flash.color}, transparent 60%)` }}
            initial={{ opacity: 0.32, scale: 0.6 }} animate={{ opacity: 0, scale: 1.4 }}
            transition={{ duration: 0.8, ease: EASE }} onAnimationComplete={() => setFlash(null)} />
        )}
      </AnimatePresence>

      {/* NAV */}
      <header className={`nav ${scrolled ? "scrolled" : ""}`}>
        <a className="brand" href="#top">
          <span className="brand-orb"><Visualizer style="strings" themeKey={theme} /></span>
          <span>Svara</span>
        </a>
        <nav className="nav-links">
          <a href="#demo">Demo</a><a href="#showcase">Visualizers</a><a href="#themes">Themes</a><a href="#tech">Under the hood</a>
        </nav>
        <div className="nav-cta">
          <a className="btn btn-ghost" href="https://github.com/vasu-devs/Svara" target="_blank" rel="noopener">GitHub</a>
          <Magnetic><a className="btn btn-solid" href="#download">Download</a></Magnetic>
        </div>
      </header>

      <main id="top">
        <Hero theme={theme} onTheme={morphTheme} reduce={!!reduce} />

        {/* MARQUEE */}
        <div className="marquee" aria-hidden>
          <div className="marquee-track">
            {[0, 1].map((s) => (
              <span className="mi" key={s}>
                {["Local", "Private", "Instant", "Free", "Open source", "Streaming", "GPU-native", "Offline", "Themeable", "System-wide"].map((w) => (
                  <span key={w}><span>{w}</span><span className="dot" /></span>
                ))}
              </span>
            ))}
          </div>
        </div>

        {/* DEMO */}
        <section className="demo" id="demo">
          <Reveal className="section-head">
            <span className="kicker">Live, on this page</span>
            <h2>Watch it think<br />in <em>real time.</em></h2>
            <p className="section-sub">The pill above is not a video. It is the exact visualizer that ships in the app, drawing your voice as ribbons and streaming words to your cursor about a second behind you.</p>
          </Reveal>
          <div className="demo-rows">
            {[
              ["01", "Zero round-trip", "Nothing is sent anywhere, so there is no network delay to wait on. The only latency is your GPU, and it is fast."],
              ["02", "Streaming, not batch", "Words are committed as soon as two passes agree on them, so text lands while you are still talking."],
              ["03", "It reads your tone", "Raise your voice on a word and Svara types it in caps. Punctuation and filler cleanup happen automatically."],
            ].map(([n, h, p], i) => (
              <Reveal className="demo-row" key={n} delay={i * 0.05}>
                <span className="drk">{n}</span><div><h3>{h}</h3><p>{p}</p></div>
              </Reveal>
            ))}
          </div>
        </section>

        <Showcase theme={theme} />

        {/* THEMES */}
        <section className="themes" id="themes">
          <Reveal className="section-head">
            <span className="kicker">Make it yours</span>
            <h2>Recolor everything<br />in <em>one tap.</em></h2>
            <p className="section-sub">Tap a theme. The pill, the page accent, and the ribbons all shift together, exactly like the tray menu on your desktop.</p>
          </Reveal>
          <div className="theme-grid">
            {THEME_KEYS.map((k, i) => {
              const th = THEMES[k];
              return (
                <Reveal key={k} delay={(i % 3) * 0.05}>
                  <button className={`theme ${theme === k ? "active" : ""}`} onClick={() => morphTheme(k)}>
                    <div className="theme-preview"><span className="theme-dot" style={{ background: th.dot }} /><Visualizer style="strings" themeKey={k} /></div>
                    <div className="theme-row"><span className="theme-name">{th.name}</span><span className="theme-meta">tap</span></div>
                  </button>
                </Reveal>
              );
            })}
          </div>
        </section>

        {/* HOW */}
        <section className="how">
          <Reveal className="section-head"><span className="kicker">The whole app</span><h2>Three moves.<br />That is <em>it.</em></h2></Reveal>
          <ol className="steps">
            {[
              ["1", <span key="k" className="step-key"><kbd>Right Alt</kbd><span className="x2">x2</span></span>, "Double-tap to start", "The pill slides up and Svara starts listening. No window to find, no button to hunt for."],
              ["2", <MicIcon key="m" />, "Speak naturally", "Words stream in as you talk and get cleaned up on the fly. Pause whenever, it waits for you."],
              ["3", <SendIcon key="s" />, "Tap to finish", "Text lands right at your cursor, in whatever app you are using. Slack, VS Code, your browser, a terminal."],
            ].map(([n, icon, h, p], i) => (
              <Reveal key={n as string} delay={i * 0.06}>
                <li className="step"><span className="step-n">{n}</span>{icon}<h3>{h}</h3><p>{p}</p></li>
              </Reveal>
            ))}
          </ol>
        </section>

        {/* FEATURES */}
        <section className="features">
          <Reveal className="section-head"><span className="kicker">Engineering</span><h2>Built to <em>vanish</em><br />into your workflow.</h2></Reveal>
          <div className="bento">
            <Reveal className="cell-lead-wrap"><Spotlight className="cell-lead">
              <div className="cell-visual"><div className="mini-pill"><span className="mini-dot" /><Visualizer style="strings" themeKey={theme} /></div></div>
              <div className="cell-body"><h3>Private by architecture</h3><p>Your audio is captured, transcribed, and discarded on your own machine. It physically cannot reach a server, because there is no server. Works on a plane, in a vault, offline.</p></div>
            </Spotlight></Reveal>
            <Reveal className="cell-accent-wrap"><Spotlight className="cell-accent"><h3>GPU-fast streaming</h3><p>faster-whisper running <span className="mono">large-v3-turbo</span> on CTranslate2. Words appear about a second behind your voice.</p></Spotlight></Reveal>
            <Reveal className="cell-sm"><Spotlight><h3>Works in every app</h3><p>System-wide text injection through the Win32 API drops text at your cursor anywhere you can type.</p></Spotlight></Reveal>
            <Reveal className="cell-wide-wrap"><Spotlight className="cell-wide">
              <div className="cell-body"><h3>A UI you will actually enjoy</h3><p>Drag it anywhere, dock it, or click for a little surprise. It dodges your cursor so it never sits on your text.</p></div>
              <div className="looks-strip">{["aurora", "matrix", "cyberpunk", "sakura", "dracula", "midas"].map((k) => <span key={k} className="lchip" style={{ background: `linear-gradient(180deg, ${THEMES[k].cols?.[1] || "#8b5cf6"}22, transparent)`, borderColor: (THEMES[k].cols?.[2] || "#22d3ee") + "33" }} />)}</div>
            </Spotlight></Reveal>
            <Reveal className="cell-sm"><Spotlight><h3>Always on, out of the way</h3><p>Lives in the tray, restarts itself if it ever hiccups, and uses no global keyboard hook. It watches one key and nothing else.</p></Spotlight></Reveal>
          </div>
        </section>

        {/* COMPARE */}
        <section className="compare">
          <Reveal className="section-head"><span className="kicker">The difference</span><h2>Private by <em>design,</em><br />not by promise.</h2><p className="section-sub">Most dictation tools ship your voice to a company's servers and bill you monthly. Svara does not.</p></Reveal>
          <Reveal className="compare-table">
            <div className="ct-row ct-head"><span /><span className="ct-svara">Svara</span><span className="ct-other">Typical cloud dictation</span></div>
            {[
              ["Where your audio goes", "Your GPU", "A company's servers"],
              ["Works offline", "Yes", "No"], ["Price", "Free", "Subscription"],
              ["Source code", "Open, auditable", "Closed"], ["Latency comes from", "Local compute", "A network round-trip"],
            ].map(([k, a, b]) => (
              <div className="ct-row" key={k}><span className="ct-key">{k}</span><span className="ct-yes">{a}</span><span className="ct-no">{b}</span></div>
            ))}
          </Reveal>
        </section>

        {/* TECH */}
        <section className="tech" id="tech">
          <Reveal className="section-head"><span className="kicker">Under the hood</span><h2>For the people<br />who read the <em>source.</em></h2></Reveal>
          <div className="tech-grid">
            {[
              ["stt", <>faster-whisper on CTranslate2, <span className="mono">large-v3-turbo</span> at int8, warmed up at launch for an instant first word.</>],
              ["vad", <>Silero voice activity detection with a pre-roll ring buffer, so the first syllable is never clipped.</>],
              ["input", <>Poll-only hotkey via GetAsyncKeyState. No system-wide keyboard hook, so it can never interfere with your typing.</>],
              ["output", <>Win32 SendInput and clipboard paste for character-perfect text injection into any focused app.</>],
              ["ui", <>Per-pixel alpha overlay rendered with Pillow and UpdateLayeredWindow. Smooth edges, real glow, no jagged pixels.</>],
              ["ship", <>Packaged with PyInstaller into a self-contained folder. Your users double-click one exe. No Python required.</>],
            ].map(([tag, body], i) => (
              <Reveal key={tag as string} delay={(i % 3) * 0.05}><div className="tech-item"><span className="mono tech-tag">{tag}</span><p>{body}</p></div></Reveal>
            ))}
          </div>
        </section>

        {/* DOWNLOAD */}
        <section className="download" id="download">
          <Reveal className="dl-inner">
            <div className="dl-glow" aria-hidden />
            <h2>Give your voice<br />somewhere to <em>land.</em></h2>
            <p>Windows 10 and 11, with an NVIDIA GPU for the fast path. No GPU still works, just slower on the CPU.</p>
            <div className="dl-actions">
              <Magnetic><a className="btn btn-solid btn-lg" href="https://github.com/vasu-devs/Svara/releases" target="_blank" rel="noopener"><DownloadIcon />Download for Windows</a></Magnetic>
              <a className="btn btn-ghost btn-lg" href="https://github.com/vasu-devs/Svara" target="_blank" rel="noopener"><GithubIcon />Star on GitHub</a>
            </div>
            <p className="dl-note">First launch downloads the speech model once. After that Svara runs fully offline.</p>
          </Reveal>
        </section>
      </main>

      <footer className="footer">
        <div className="foot-top">
          <div className="foot-brand"><span className="brand-orb sm"><Visualizer style="strings" themeKey={theme} /></span><span>Svara</span></div>
          <div className="foot-links"><a href="https://github.com/vasu-devs/Svara" target="_blank" rel="noopener">GitHub</a><a href="https://github.com/vasu-devs/Svara/issues" target="_blank" rel="noopener">Issues</a><a href="#download">Download</a></div>
        </div>
        <p className="foot-fine">Private voice dictation that runs on your own machine. Open source, built on faster-whisper. Your voice stays with you.</p>
      </footer>
    </>
  );
}

/* ---------- hero ---------- */

function Hero({ theme, onTheme, reduce }: { theme: string; onTheme: (k: string) => void; reduce: boolean }) {
  const [typed, setTyped] = useState("");
  useEffect(() => {
    if (reduce) { setTyped("nothing left your laptop."); return; }
    const phrases = ["nothing left your laptop.", "this text was typed by a voice.", "no cloud, no account, no waiting.", "your GPU did all the work."];
    let pi = 0, ci = 0, dir = 1, timer: ReturnType<typeof setTimeout>;
    const tick = () => {
      const p = phrases[pi]; setTyped(p.slice(0, ci));
      if (dir > 0) { if (ci === 0) speak(p.length * 55 + 400); ci++; if (ci > p.length) { dir = -1; timer = setTimeout(tick, 1400); return; } }
      else { ci--; if (ci < 0) { ci = 0; dir = 1; pi = (pi + 1) % phrases.length; timer = setTimeout(tick, 260); return; } }
      timer = setTimeout(tick, dir > 0 ? 52 : 26);
    };
    tick(); return () => clearTimeout(timer);
  }, [reduce]);

  const stageRef = useRef<HTMLDivElement>(null);

  return (
    <section className="hero">
      <div className="aurora" aria-hidden><span className="blob b1" /><span className="blob b2" /><span className="blob b3" /></div>
      <div className="hero-inner">
        <div className="hero-copy">
          <motion.span className="eyebrow" initial={reduce ? false : { opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.7, ease: EASE }}>Local voice dictation for Windows</motion.span>
          <motion.h1 className="hero-title"
            initial={reduce ? false : { opacity: 0, y: 22 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.85, ease: EASE, delay: 0.08 }}>
            Speak&nbsp;anywhere.<br />It types <em className="grad">itself.</em>
          </motion.h1>
          <motion.p className="lede" initial={reduce ? false : { opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.8, ease: EASE, delay: 0.16 }}>Svara turns your voice into text in any app, on your own GPU. No cloud, no account, no waiting.</motion.p>
          <motion.div className="hero-actions" initial={reduce ? false : { opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.8, ease: EASE, delay: 0.24 }}>
            <Magnetic><a className="btn btn-solid btn-lg" href="#download"><DownloadIcon />Download for Windows</a></Magnetic>
            <a className="btn btn-ghost btn-lg" href="https://github.com/vasu-devs/Svara" target="_blank" rel="noopener">View source</a>
          </motion.div>
        </div>

        <motion.div className="hero-stage" ref={stageRef}
          initial={reduce ? false : { opacity: 0, y: 30 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.9, ease: EASE, delay: 0.2 }}
          onPointerMove={(e) => { if (reduce || !stageRef.current) return; const r = stageRef.current.getBoundingClientRect(); setPointer((e.clientX - r.left) / r.width, 1); }}
          onPointerLeave={() => setPointer(0.5, 0)}>
          <div className="stage-glow" aria-hidden />
          <motion.div className="pill" drag={!reduce} dragSnapToOrigin dragElastic={0.16}
            dragTransition={{ bounceStiffness: 300, bounceDamping: 18 }} whileTap={{ scale: 1.03, cursor: "grabbing" }}
            title="Drag me">
            <span className="pill-dot" />
            <Visualizer style="strings" themeKey={theme} hero className="pill-canvas" />
            <div className="pill-controls" aria-hidden><span className="ctl ctl-grid" /><span className="ctl ctl-diamond" /><span className="ctl ctl-moon" /></div>
          </motion.div>
          <div className="type-line"><span>{typed}</span><span className="caret" /></div>
          <div className="stage-foot">
            <Magnetic strength={0.2}><button className="try" onClick={() => speak()}>Say something</button></Magnetic>
            <div className="swatches">
              {["aurora", "cyberpunk", "matrix", "sakura", "dracula", "rgb"].map((k) => {
                const c = THEMES[k].cols || ["#ff0055", "#00ff88", "#22d3ee"];
                return <button key={k} className={`swatch ${theme === k ? "on" : ""}`} aria-label={THEMES[k].name}
                  style={{ background: `linear-gradient(120deg, ${c[0]}, ${c[1]}, ${c[2]})` }} onClick={() => onTheme(k)} />;
              })}
            </div>
          </div>
        </motion.div>
      </div>

      <div className="hero-stats">
        {[
          [<CountUp key="a" to={0} />, "bytes uploaded"],
          [<CountUp key="b" to={0.3} dec={1} suffix="s" />, "for 5s of speech"],
          [<CountUp key="c" to={1.2} dec={1} suffix="GB" />, "VRAM used"],
          [<CountUp key="d" to={12} />, "themes, 8 visualizers"],
        ].map(([v, l], i) => (
          <Reveal className="hstat" key={i} delay={i * 0.05}><b>{v}</b><span>{l}</span></Reveal>
        ))}
      </div>
    </section>
  );
}

/* ---------- scroll-driven visualizer showcase ---------- */

function Showcase({ theme }: { theme: string }) {
  const wrap = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({ target: wrap, offset: ["start start", "end end"] });
  const [idx, setIdx] = useState(0);
  useMotionValueEvent(scrollYProgress, "change", (p) => {
    const i = Math.min(STYLES.length - 1, Math.max(0, Math.floor(p * STYLES.length)));
    setIdx(i);
  });
  return (
    <section className="showcase" id="showcase" ref={wrap} style={{ height: STYLES.length * 460 }}>
      <div className="showcase-sticky">
        <div className="showcase-head">
          <span className="kicker">Signature</span>
          <h2>Eight ways to watch your <em>voice.</em></h2>
          <p className="section-sub">Scroll through every visualizer that ships in the app. All live, all yours.</p>
        </div>
        <div className="showcase-stage">
          <div className="showcase-pill">
            <span className="pill-dot" />
            <Visualizer style={STYLES[idx]} themeKey={theme} hero className="pill-canvas big" />
          </div>
          <div className="showcase-meta">
            <span className="showcase-num">{String(idx + 1).padStart(2, "0")}<span className="slash">/08</span></span>
            <span className="showcase-name">{STYLES[idx]}</span>
          </div>
          <ol className="showcase-list">
            {STYLES.map((s, i) => <li key={s} className={i === idx ? "on" : ""}>{s}</li>)}
          </ol>
        </div>
      </div>
    </section>
  );
}

/* ---------- cursor glow ---------- */

function CursorGlow() {
  const reduce = useReducedMotion();
  const x = useMotionValue(-999), y = useMotionValue(-999);
  const sx = useSpring(x, { stiffness: 300, damping: 30 }), sy = useSpring(y, { stiffness: 300, damping: 30 });
  useEffect(() => {
    if (reduce) return;
    const on = (e: PointerEvent) => { x.set(e.clientX); y.set(e.clientY); };
    window.addEventListener("pointermove", on, { passive: true });
    return () => window.removeEventListener("pointermove", on);
  }, [reduce, x, y]);
  if (reduce) return null;
  return <motion.div className="cursor-glow" aria-hidden style={{ left: sx as MotionValue<number>, top: sy as MotionValue<number> }} />;
}

/* ---------- icons ---------- */
const DownloadIcon = () => <svg viewBox="0 0 24 24" className="btn-ic" fill="none"><path d="M12 3v12m0 0l-4-4m4 4l4-4M5 19h14" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" /></svg>;
const GithubIcon = () => <svg viewBox="0 0 24 24" className="btn-ic" fill="none"><path d="M12 2a10 10 0 0 0-3.16 19.49c.5.09.68-.22.68-.48v-1.7c-2.78.6-3.37-1.34-3.37-1.34-.45-1.16-1.11-1.47-1.11-1.47-.91-.62.07-.6.07-.6 1 .07 1.53 1.03 1.53 1.03.9 1.53 2.36 1.09 2.94.83.09-.65.35-1.09.63-1.34-2.22-.25-4.55-1.11-4.55-4.94 0-1.09.39-1.98 1.03-2.68-.1-.25-.45-1.27.1-2.65 0 0 .84-.27 2.75 1.02a9.6 9.6 0 0 1 5 0c1.91-1.29 2.75-1.02 2.75-1.02.55 1.38.2 2.4.1 2.65.64.7 1.03 1.59 1.03 2.68 0 3.84-2.34 4.68-4.57 4.93.36.31.68.92.68 1.85v2.74c0 .27.18.58.69.48A10 10 0 0 0 12 2Z" fill="currentColor" /></svg>;
const MicIcon = () => <span className="step-icon"><svg viewBox="0 0 24 24" fill="none"><path d="M12 3v10M12 13c-2.2 0-4-1.8-4-4V7a4 4 0 0 1 8 0v2c0 2.2-1.8 4-4 4Z" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg></span>;
const SendIcon = () => <span className="step-icon"><svg viewBox="0 0 24 24" fill="none"><path d="M4 7h11M4 12h9M4 17h13" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /><path d="M17.5 15.5l2 2 3-4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg></span>;

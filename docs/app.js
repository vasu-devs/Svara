/* ============================================================
   Svara landing (v2): multi-style visualizer engine ported from
   the app's real overlay, full-page theme morph, live typing
   demo, magnetic buttons, spotlight cards, scroll choreography.
   Vanilla JS, no build step.
   ============================================================ */
(() => {
  "use strict";
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const TAU = Math.PI * 2;

  const THEMES = {
    aurora:    { name: "Aurora",    accent: "#22d3ee", dot: "#ff5fa2", cols: ["#ff5fa2", "#8b5cf6", "#22d3ee"] },
    cyberpunk: { name: "Cyberpunk", accent: "#00f0ff", dot: "#ff003c", cols: ["#fcee0a", "#00f0ff", "#ff003c"] },
    matrix:    { name: "Matrix",    accent: "#00ff66", dot: "#00ff66", cols: ["#00ff66", "#00cc44", "#8dffbb"] },
    sakura:    { name: "Sakura",    accent: "#ff8fab", dot: "#ff8fab", cols: ["#ff8fab", "#ffc2d1", "#e05780"] },
    dracula:   { name: "Dracula",   accent: "#bd93f9", dot: "#ff79c6", cols: ["#ff79c6", "#bd93f9", "#8be9fd"] },
    midas:     { name: "Midas",     accent: "#ffd700", dot: "#ffd700", cols: ["#ffd700", "#ffb84d", "#fff2b0"] },
    vaporwave: { name: "Vaporwave", accent: "#01cdfe", dot: "#ff71ce", cols: ["#ff71ce", "#01cdfe", "#05ffa1"] },
    rgb:       { name: "RGB",       accent: "#ff3d7f", dot: "#ff0055", cols: null, rainbow: true },
  };
  let current = "aurora";

  // shared voice-level envelope so pills feel alive
  let level = 0.12, target = 0.12, speaking = 0;
  const speak = (ms = 2600) => { speaking = performance.now() + ms; };
  function envelope(t) {
    target = speaking > t
      ? 0.42 + 0.42 * Math.abs(Math.sin(t / 130)) * (0.6 + 0.4 * Math.sin(t / 43))
      : 0.12 + 0.05 * Math.sin(t / 900);
    level += (target - level) * 0.08;
    return level;
  }
  const rainbow = (i, t) => `hsl(${((t * 0.00006 + i / 3) % 1) * 360} 90% 62%)`;

  // ---- visualizer engine ----
  const viz = [];
  function register(canvas, style, themeKey) {
    const ctx = canvas.getContext("2d");
    const v = { canvas, ctx, style, theme: THEMES[themeKey || current], visible: true };
    viz.push(v);
    fit(v);
    return v;
  }
  function fit(v) {
    const dpr = Math.min(devicePixelRatio || 1, 2);
    const w = v.canvas.clientWidth || v.canvas.width;
    const h = v.canvas.clientHeight || v.canvas.height;
    v.canvas.width = w * dpr; v.canvas.height = h * dpr;
    v.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    v.w = w; v.h = h;
  }
  const colAt = (v, i, t) => v.theme.rainbow ? rainbow(i, t) : v.theme.cols[i % 3];

  const RENDER = {
    strings(v, t, lv) {
      const { ctx, w, h } = v, mid = h / 2, amp = (2.2 + 12.5 * lv) * (h / 56);
      for (let pass = 0; pass < 2; pass++)
        for (let i = 0; i < 3; i++) {
          const ph1 = t * 0.0028 + i * 2.1, ph2 = t * 0.0018 - i * 1.4;
          ctx.beginPath();
          for (let j = 0; j <= 30; j++) {
            const u = j / 30, env = Math.sin(Math.PI * u);
            const y = mid + env * (amp * 0.72 * Math.sin(9.4 * u + ph1) + amp * 0.5 * Math.sin(14.6 * u - ph2));
            j ? ctx.lineTo(u * w, y) : ctx.moveTo(u * w, y);
          }
          ctx.strokeStyle = colAt(v, i, t); ctx.lineCap = "round";
          ctx.globalAlpha = pass ? 1 : 0.34; ctx.lineWidth = pass ? 2 : 5; ctx.stroke();
        }
      ctx.globalAlpha = 1;
    },
    bars(v, t, lv) {
      const { ctx, w, h } = v, mid = h / 2, n = 12, step = w / n, bw = 3.4;
      for (let i = 0; i < n; i++) {
        const ph = Math.sin(t * 0.012 + i * 0.9);
        const bh = (2 + (0.3 + 0.7 * Math.abs(ph)) * 13 * lv + 1.2) * (h / 56);
        const cx = i * step + step / 2;
        ctx.fillStyle = colAt(v, i, t); ctx.globalAlpha = 0.95;
        rr(ctx, cx - bw / 2, mid - bh, bw, bh * 2, bw / 2); ctx.fill();
      }
      ctx.globalAlpha = 1;
    },
    spectrum(v, t, lv) {
      const { ctx, w, h } = v, mid = h / 2, maxa = (2 + 12 * lv) * (h / 56);
      const top = [], bot = [];
      for (let j = 0; j <= 40; j++) {
        const u = j / 40, env = Math.sin(Math.PI * u);
        const a = env * maxa * (0.35 + 0.65 * Math.abs(Math.sin(7.1 * u + t * 0.008) * Math.sin(3.3 * u - t * 0.004)));
        top.push([u * w, mid - a]); bot.push([u * w, mid + a]);
      }
      ctx.beginPath(); [...top, ...bot.reverse()].forEach((p, i) => i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]));
      ctx.closePath(); ctx.fillStyle = colAt(v, 0, t); ctx.globalAlpha = 0.16; ctx.fill();
      ctx.globalAlpha = 0.9; ctx.lineWidth = 1.8; ctx.lineJoin = "round";
      poly(ctx, top, colAt(v, 1, t)); poly(ctx, bot, colAt(v, 2, t)); ctx.globalAlpha = 1;
    },
    scope(v, t, lv) {
      const { ctx, w, h } = v, mid = h / 2, amp = (1.5 + 11 * lv) * (h / 56), pts = [];
      for (let j = 0; j <= 60; j++) {
        const u = j / 60, env = Math.sin(Math.PI * u);
        pts.push([u * w, mid + env * amp * (Math.sin(18 * u + t * 0.018) + 0.4 * Math.sin(31 * u - t * 0.013))]);
      }
      ctx.lineCap = "round";
      ctx.globalAlpha = 0.28; ctx.lineWidth = 4; poly(ctx, pts, colAt(v, 0, t));
      ctx.globalAlpha = 1; ctx.lineWidth = 1.3; poly(ctx, pts, colAt(v, 0, t));
    },
    pulse(v, t, lv) {
      const { ctx, w, h } = v, cx = w / 2, mid = h / 2;
      const r = (5 + 9 * lv + 1.2 * Math.sin(t * 0.012)) * (h / 56);
      if (lv > 0.12) for (let k = 0; k < 2; k++) {
        const prog = ((t * 0.00035 + k * 0.5) % 1), rr2 = r + prog * (w / 2 - r);
        ctx.globalAlpha = (1 - prog) * 0.5; ctx.lineWidth = 1.4;
        ctx.beginPath(); ctx.arc(cx, mid, rr2, 0, TAU); ctx.strokeStyle = colAt(v, k + 1, t); ctx.stroke();
      }
      ctx.globalAlpha = 0.28; disc(ctx, cx, mid, r * 2, colAt(v, 0, t));
      ctx.globalAlpha = 1; disc(ctx, cx, mid, r, colAt(v, 0, t));
    },
    particles(v, t, lv) {
      const { ctx, w, h } = v, mid = h / 2, n = 15;
      for (let i = 0; i < n; i++) {
        const u = (i + 0.5) / n, y = mid + Math.sin(t * 0.0085 + i * 1.7) * (2 + 10 * lv) * (h / 56) * Math.sin(Math.PI * u);
        const r = (1.1 + ((i * 53) % 9) / 9 * 1.6) * (h / 56) * 2;
        ctx.globalAlpha = 0.45 + 0.45 * Math.abs(Math.sin(t * 0.006 + i * 0.8));
        disc(ctx, u * w, y, r, colAt(v, i, t));
      }
      ctx.globalAlpha = 1;
    },
    beam(v, t, lv) {
      const { ctx, w, h } = v, mid = h / 2;
      const orb = (3.5 + 5 * lv + 0.8 * Math.sin(t * 0.018)) * (h / 56);
      const bx = orb + 4, thick = (1.2 + 9 * lv) * (h / 56), top = [], bot = [];
      for (let j = 0; j <= 24; j++) {
        const u = j / 24, x = bx + u * (w - bx - 4), wob = Math.sin(11 * u - t * 0.027) * thick * 0.25;
        top.push([x, mid - thick / 2 + wob]); bot.push([x, mid + thick / 2 + wob]);
      }
      ctx.beginPath(); [...top, ...bot.reverse()].forEach((p, i) => i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]));
      ctx.closePath(); ctx.fillStyle = colAt(v, 2, t); ctx.globalAlpha = 0.4; ctx.fill();
      ctx.globalAlpha = 1; ctx.lineWidth = Math.max(2, thick * 0.35); ctx.lineCap = "round";
      ctx.beginPath(); ctx.moveTo(bx, mid); ctx.lineTo(w - 4, mid); ctx.strokeStyle = colAt(v, 0, t); ctx.stroke();
      ctx.globalAlpha = 0.28; disc(ctx, bx, mid, orb * 1.9, colAt(v, 1, t));
      ctx.globalAlpha = 1; disc(ctx, bx, mid, orb, colAt(v, 0, t));
    },
    pixels(v, t, lv) {
      const { ctx, w, h } = v, mid = h / 2, n = 11, step = w / n, block = 2.6 * (h / 56) * 2, gap = 2;
      for (let i = 0; i < n; i++) {
        const ph = Math.abs(Math.sin(t * 0.01 + i * 1.1)), levels = 1 + Math.floor((0.25 + 0.75 * ph) * lv * 4 + 0.4);
        const cx = i * step + step / 2; ctx.fillStyle = colAt(v, i, t); ctx.globalAlpha = 0.95;
        for (let k = 0; k < levels; k++) {
          const off = k * (block + gap);
          ctx.fillRect(cx - block / 2, mid - off - block, block, block);
          ctx.fillRect(cx - block / 2, mid + off, block, block);
        }
      }
      ctx.globalAlpha = 1;
    },
  };
  function rr(c, x, y, w, h, r) { c.beginPath(); c.moveTo(x + r, y); c.arcTo(x + w, y, x + w, y + h, r); c.arcTo(x + w, y + h, x, y + h, r); c.arcTo(x, y + h, x, y, r); c.arcTo(x, y, x + w, y, r); c.closePath(); }
  function poly(c, pts, col) { c.beginPath(); pts.forEach((p, i) => i ? c.lineTo(p[0], p[1]) : c.moveTo(p[0], p[1])); c.strokeStyle = col; c.stroke(); }
  function disc(c, x, y, r, col) { c.beginPath(); c.arc(x, y, r, 0, TAU); c.fillStyle = col; c.fill(); }

  function loop(t) {
    const lv = envelope(t);
    for (const v of viz) if (v.visible) { v.ctx.clearRect(0, 0, v.w, v.h); (RENDER[v.style] || RENDER.strings)(v, t, lv); }
    requestAnimationFrame(loop);
  }

  // ---- build UI ----
  const dot = document.getElementById("pillDot");
  const hero = register(document.getElementById("wave"), "strings");
  ["navWave", "footWave", "miniWave"].forEach(id => { const el = document.getElementById(id); if (el) register(el, "strings"); });

  function setTheme(key) {
    current = key;
    const th = THEMES[key];
    document.documentElement.style.setProperty("--accent", th.accent);
    document.documentElement.style.setProperty("--accent-soft", th.accent + "24");
    if (dot) dot.style.background = th.dot;
    viz.forEach(v => { if (!v.fixed) v.theme = th; });  // theme-grid previews keep their own palette
    document.querySelectorAll("[data-theme]").forEach(el => el.setAttribute("aria-pressed", String(el.dataset.theme === key)));
    speak(1600);
  }

  // swatches (hero)
  const sw = document.getElementById("swatches");
  ["aurora", "cyberpunk", "matrix", "sakura", "dracula", "rgb"].forEach((k, i) => {
    const b = document.createElement("button");
    b.className = "swatch"; b.type = "button"; b.dataset.theme = k;
    b.setAttribute("aria-label", THEMES[k].name); b.setAttribute("aria-pressed", String(i === 0));
    const c = THEMES[k].cols || ["#ff0055", "#00ff88", "#22d3ee"];
    b.style.background = `linear-gradient(120deg,${c[0]},${c[1]},${c[2]})`;
    b.addEventListener("click", () => setTheme(k));
    sw && sw.appendChild(b);
  });

  // visualizer grid (all 8)
  const vg = document.getElementById("vizGrid");
  const STYLES = [["strings", "Strings"], ["bars", "Bars"], ["spectrum", "Spectrum"], ["scope", "Scope"], ["pulse", "Pulse"], ["particles", "Particles"], ["beam", "Beam"], ["pixels", "Pixels"]];
  STYLES.forEach(([style, label], i) => {
    const card = document.createElement("div");
    card.className = "vcard reveal";
    card.innerHTML = `<div class="vwrap"><canvas width="240" height="44"></canvas></div>
      <div class="vrow"><span class="vname">${label}</span><span class="vnum">0${i + 1}</span></div>`;
    vg && vg.appendChild(card);
    register(card.querySelector("canvas"), style);
  });

  // theme grid (recolors the whole page)
  const tg = document.getElementById("themeGrid");
  ["aurora", "cyberpunk", "matrix", "sakura", "dracula", "vaporwave"].forEach(k => {
    const th = THEMES[k];
    const card = document.createElement("button");
    card.className = "theme reveal"; card.type = "button"; card.dataset.theme = k;
    card.setAttribute("aria-pressed", String(k === current));
    card.innerHTML = `<div class="theme-preview"><span class="theme-dot" style="background:${th.dot}"></span><canvas width="240" height="40"></canvas></div>
      <div class="theme-row"><span class="theme-name">${th.name}</span><span class="theme-meta">tap</span></div>`;
    tg && tg.appendChild(card);
    register(card.querySelector("canvas"), "strings", k).fixed = true;
    card.addEventListener("click", () => { setTheme(k); document.getElementById("pill")?.scrollIntoView({ behavior: "smooth", block: "center" }); });
  });

  // looks strip chips
  const strip = document.getElementById("looksStrip");
  ["aurora", "matrix", "cyberpunk", "sakura", "dracula", "midas"].forEach(k => {
    const d = document.createElement("div"); d.className = "lchip";
    const c = THEMES[k].cols || ["#f57", "#5f8", "#2de"];
    d.style.background = `linear-gradient(180deg,${c[1]}22,transparent)`; d.style.borderColor = c[2] + "33";
    strip && strip.appendChild(d);
  });

  // marquee
  const mq = document.getElementById("marquee");
  if (mq) {
    const words = ["Local", "Private", "Instant", "Free", "Open source", "Streaming", "GPU-native", "Offline", "Themeable", "System-wide"];
    const seg = () => { const s = document.createElement("span"); s.className = "mi";
      words.forEach(w => { const a = document.createElement("span"); a.textContent = w; s.appendChild(a); const d = document.createElement("span"); d.className = "dot"; s.appendChild(d); }); return s; };
    mq.appendChild(seg()); mq.appendChild(seg());
  }

  // ---- interactions ----
  const pill = document.getElementById("pill");
  pill?.addEventListener("click", () => speak());
  document.getElementById("tryBtn")?.addEventListener("click", () => speak());

  // magnetic buttons
  if (!reduce) document.querySelectorAll(".magnetic").forEach(el => {
    el.addEventListener("pointermove", e => {
      const r = el.getBoundingClientRect();
      el.style.transform = `translate(${(e.clientX - r.left - r.width / 2) * 0.22}px,${(e.clientY - r.top - r.height / 2) * 0.32}px)`;
    });
    el.addEventListener("pointerleave", () => el.style.transform = "");
  });

  // cursor glow + spotlight cards
  const glow = document.getElementById("cursorGlow");
  if (!reduce) {
    addEventListener("pointermove", e => {
      if (glow) { glow.style.left = e.clientX + "px"; glow.style.top = e.clientY + "px"; glow.style.opacity = "1"; }
    }, { passive: true });
    document.querySelectorAll(".spotlight").forEach(c => c.addEventListener("pointermove", e => {
      const r = c.getBoundingClientRect();
      c.style.setProperty("--mx", (e.clientX - r.left) + "px");
      c.style.setProperty("--my", (e.clientY - r.top) + "px");
    }));
  }

  // ---- live typing demo ----
  const typed = document.getElementById("typed");
  if (typed && !reduce) {
    const phrases = ["nothing left your laptop.", "this text was typed by a voice.", "no cloud, no account, no waiting.", "your GPU did all the work."];
    let pi = 0, ci = 0, dir = 1;
    (function type() {
      const p = phrases[pi];
      typed.textContent = p.slice(0, ci);
      if (dir > 0) { if (ci === 0) speak(p.length * 55 + 400); ci++; if (ci > p.length) { dir = -1; return setTimeout(type, 1400); } }
      else { ci--; if (ci < 0) { ci = 0; dir = 1; pi = (pi + 1) % phrases.length; return setTimeout(type, 260); } }
      setTimeout(type, dir > 0 ? 52 : 26);
    })();
  } else if (typed) { typed.textContent = "nothing left your laptop."; }

  // ---- reveal + hero title + stagger ----
  const io = "IntersectionObserver" in window && !reduce
    ? new IntersectionObserver((es, obs) => es.forEach(e => { if (e.isIntersecting) { e.target.classList.add("in"); obs.unobserve(e.target); } }), { threshold: 0.15 })
    : null;
  if (io) {
    document.querySelectorAll(".reveal").forEach((el, i) => { el.style.transitionDelay = (i % 6) * 0.05 + "s"; io.observe(el); });
    const title = document.querySelector(".hero-title");
    setTimeout(() => title?.classList.add("in"), 120);
  } else {
    document.querySelectorAll(".reveal").forEach(el => el.classList.add("in"));
    document.querySelector(".hero-title")?.classList.add("in");
  }

  // ---- count-up stats ----
  const stats = document.querySelectorAll(".hstat b[data-count]");
  if ("IntersectionObserver" in window && !reduce) {
    const so = new IntersectionObserver((es, obs) => es.forEach(e => {
      if (!e.isIntersecting) return; obs.unobserve(e.target);
      const el = e.target, end = parseFloat(el.dataset.count), dec = parseInt(el.dataset.dec || "0"), suf = el.dataset.suffix || "";
      const t0 = performance.now();
      (function step(t) {
        const k = Math.min(1, (t - t0) / 1100), e2 = 1 - Math.pow(1 - k, 3);
        el.textContent = (end * e2).toFixed(dec) + suf;
        if (k < 1) requestAnimationFrame(step); else el.textContent = end.toFixed(dec) + suf;
      })(t0);
    }), { threshold: 0.6 });
    stats.forEach(s => so.observe(s));
  } else stats.forEach(s => s.textContent = s.dataset.count + (s.dataset.suffix || ""));

  // ---- visibility gating ----
  if ("IntersectionObserver" in window) {
    const go = new IntersectionObserver(es => es.forEach(e => { const v = viz.find(x => x.canvas === e.target); if (v) v.visible = e.isIntersecting; }), { rootMargin: "100px" });
    viz.forEach(v => go.observe(v.canvas));
  }
  addEventListener("resize", () => viz.forEach(fit));

  // nav shadow
  const nav = document.getElementById("nav");
  addEventListener("scroll", () => nav?.classList.toggle("scrolled", scrollY > 12), { passive: true });

  // ---- run ----
  if (reduce) { const t = 1200, lv = 0.28; viz.forEach(v => { v.ctx.clearRect(0, 0, v.w, v.h); (RENDER[v.style] || RENDER.strings)(v, t, lv); }); }
  else { requestAnimationFrame(loop); setInterval(() => { if (speaking < performance.now()) speak(2000); }, 8000); speak(2600); }
})();

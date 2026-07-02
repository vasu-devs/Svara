/* ============================================================
   Svara landing: live ribbon renderer (ported from the app's
   real Siri-style flowing-strings visualizer), theme switching,
   scroll reveals. Vanilla JS, no build step.
   ============================================================ */
(() => {
  "use strict";
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const THEMES = {
    aurora:    { name: "Aurora",    dot: "#ff5fa2", cols: ["#ff5fa2", "#8b5cf6", "#22d3ee"] },
    cyberpunk: { name: "Cyberpunk", dot: "#ff003c", cols: ["#fcee0a", "#00f0ff", "#ff003c"] },
    matrix:    { name: "Matrix",    dot: "#00ff66", cols: ["#00ff66", "#00cc44", "#8dffbb"] },
    sakura:    { name: "Sakura",    dot: "#ff8fab", cols: ["#ff8fab", "#ffc2d1", "#e05780"] },
    dracula:   { name: "Dracula",   dot: "#ff79c6", cols: ["#ff79c6", "#bd93f9", "#8be9fd"] },
    midas:     { name: "Midas",     dot: "#ffd700", cols: ["#ffd700", "#ffb84d", "#fff2b0"] },
    vaporwave: { name: "Vaporwave", dot: "#ff71ce", cols: ["#ff71ce", "#01cdfe", "#05ffa1"] },
    rgb:       { name: "RGB",       dot: "#ff0055", cols: null, rainbow: true },
  };

  // shared "voice level" envelope so the hero always feels alive
  let level = 0.12, levelTarget = 0.12, speaking = 0;
  function speak(ms = 2600) { speaking = performance.now() + ms; }

  function updateLevel(t) {
    if (speaking > t) {
      // noisy speaking envelope
      levelTarget = 0.45 + 0.4 * Math.abs(Math.sin(t / 140)) * (0.6 + 0.4 * Math.sin(t / 47));
    } else {
      levelTarget = 0.12 + 0.05 * Math.sin(t / 900); // gentle idle breathing
    }
    level += (levelTarget - level) * 0.08;
    return level;
  }

  function rainbow(i, t) {
    const h = ((t * 0.00006 + i / 3) % 1) * 360;
    return `hsl(${h} 90% 62%)`;
  }

  const ribbons = []; // {canvas, ctx, theme, visible}

  function makeRibbon(canvas, themeKey) {
    const ctx = canvas.getContext("2d");
    const r = { canvas, ctx, theme: THEMES[themeKey], visible: true };
    ribbons.push(r);
    resize(r);
    return r;
  }

  function resize(r) {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = r.canvas.clientWidth || r.canvas.width;
    const h = r.canvas.clientHeight || r.canvas.height;
    r.canvas.width = w * dpr;
    r.canvas.height = h * dpr;
    r.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    r.w = w; r.h = h;
  }

  function drawRibbon(r, t, lv) {
    const { ctx, w, h } = r;
    ctx.clearRect(0, 0, w, h);
    const mid = h / 2;
    const amp = (2.2 + 12.5 * lv) * (h / 56);
    const cols = r.theme.cols;
    const N = 3, pts = 30;
    for (let pass = 0; pass < 2; pass++) {
      for (let i = 0; i < N; i++) {
        const col = r.theme.rainbow ? rainbow(i, t) : cols[i];
        const ph1 = t * 0.0028 + i * 2.1;
        const ph2 = t * 0.0018 - i * 1.4;
        ctx.beginPath();
        for (let j = 0; j <= pts; j++) {
          const u = j / pts;
          const env = Math.sin(Math.PI * u);
          const y = mid + env * (amp * 0.72 * Math.sin(9.4 * u + ph1)
                                 + amp * 0.5 * Math.sin(14.6 * u - ph2));
          const x = u * w;
          j === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        }
        ctx.strokeStyle = col;
        ctx.lineCap = "round";
        if (pass === 0) { ctx.globalAlpha = 0.34; ctx.lineWidth = 5; }
        else { ctx.globalAlpha = 1; ctx.lineWidth = 2; }
        ctx.stroke();
      }
    }
    ctx.globalAlpha = 1;
  }

  function frame(t) {
    const lv = updateLevel(t);
    for (const r of ribbons) if (r.visible) drawRibbon(r, t, lv);
    requestAnimationFrame(frame);
  }

  // ---- hero pill ----
  const pill = document.getElementById("pill");
  const dot = document.getElementById("pillDot");
  const heroCanvas = document.getElementById("wave");
  const hero = heroCanvas ? makeRibbon(heroCanvas, "aurora") : null;

  function applyTheme(key) {
    if (!hero) return;
    hero.theme = THEMES[key];
    if (dot) dot.style.background = THEMES[key].dot;
    document.querySelectorAll(".swatch").forEach(s =>
      s.setAttribute("aria-pressed", String(s.dataset.theme === key)));
    speak(1600);
  }

  // ---- swatches ----
  const swatchKeys = ["aurora", "cyberpunk", "matrix", "sakura", "dracula", "rgb"];
  const sw = document.getElementById("swatches");
  if (sw) swatchKeys.forEach((k, idx) => {
    const b = document.createElement("button");
    b.className = "swatch";
    b.type = "button";
    b.dataset.theme = k;
    b.setAttribute("aria-label", THEMES[k].name);
    b.setAttribute("aria-pressed", String(idx === 0));
    const c = THEMES[k].cols || ["#ff0055", "#00ff88", "#22d3ee"];
    b.style.background = `linear-gradient(120deg, ${c[0]}, ${c[1]}, ${c[2]})`;
    b.addEventListener("click", () => applyTheme(k));
    sw.appendChild(b);
  });

  const tryBtn = document.getElementById("tryBtn");
  if (tryBtn) tryBtn.addEventListener("click", () => speak());
  if (pill) pill.addEventListener("click", () => speak());

  // ---- mini pill (features) ----
  const mini = document.getElementById("miniWave");
  if (mini) makeRibbon(mini, "aurora");

  // ---- looks strip chips (feature cell) ----
  const strip = document.getElementById("looksStrip");
  if (strip) ["aurora", "matrix", "cyberpunk", "sakura", "dracula", "midas"].forEach(k => {
    const d = document.createElement("div");
    d.className = "lchip";
    const c = THEMES[k].cols || ["#ff0055", "#00ff88", "#22d3ee"];
    d.style.background = `linear-gradient(180deg, ${c[1]}22, transparent)`;
    d.style.borderColor = c[2] + "33";
    strip.appendChild(d);
  });

  // ---- looks grid ----
  const grid = document.getElementById("looksGrid");
  const gridKeys = ["aurora", "cyberpunk", "matrix", "sakura", "dracula", "vaporwave"];
  if (grid) gridKeys.forEach(k => {
    const th = THEMES[k];
    const card = document.createElement("button");
    card.className = "look reveal";
    card.type = "button";
    card.innerHTML = `
      <div class="look-preview">
        <span class="look-dot" style="background:${th.dot}"></span>
        <canvas width="240" height="42"></canvas>
      </div>
      <div class="look-row">
        <span class="look-name">${th.name}</span>
        <span class="look-meta">tap to apply</span>
      </div>`;
    grid.appendChild(card);
    makeRibbon(card.querySelector("canvas"), k);
    card.addEventListener("click", () => {
      applyTheme(k);
      pill?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  });

  // ---- visibility gating (only animate on-screen ribbons) ----
  if ("IntersectionObserver" in window) {
    const io = new IntersectionObserver(es => {
      es.forEach(e => {
        const r = ribbons.find(x => x.canvas === e.target);
        if (r) r.visible = e.isIntersecting;
      });
    }, { rootMargin: "80px" });
    ribbons.forEach(r => io.observe(r.canvas));
  }

  window.addEventListener("resize", () => ribbons.forEach(resize));

  // ---- reveal on scroll ----
  const revs = document.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window && !reduce) {
    const ro = new IntersectionObserver((es, obs) => {
      es.forEach(e => { if (e.isIntersecting) { e.target.classList.add("in"); obs.unobserve(e.target); } });
    }, { threshold: 0.15 });
    revs.forEach(el => ro.observe(el));
  } else {
    revs.forEach(el => el.classList.add("in"));
  }

  // ---- nav shadow on scroll ----
  const nav = document.getElementById("nav");
  const onScroll = () => nav && nav.classList.toggle("scrolled", window.scrollY > 12);
  document.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  // ---- run ----
  if (reduce) {
    ribbons.forEach(r => drawRibbon(r, 1200, 0.28)); // single static frame
  } else {
    requestAnimationFrame(frame);
    // occasional auto-speak so the hero feels alive without interaction
    setInterval(() => { if (speaking < performance.now()) speak(2200); }, 7000);
    speak(2600);
  }
})();

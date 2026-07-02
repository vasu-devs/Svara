/* Visualizer engine, "ink" edition. The app's real waveform math, but drawn
   as crisp ink line-art on paper with a single accent, no neon glow. Eight
   styles, one shared rAF loop, cursor-reactive hero, tap-to-recolor accent. */

export type Theme = { name: string; accent: string };

export const INK = "#1a160f";
export const INK_SOFT = "#4a4438";
export const MUTED = "#a9a290";

export const THEMES: Record<string, Theme> = {
  vermillion: { name: "Vermillion", accent: "#ff4a1c" },
  cobalt:     { name: "Cobalt",     accent: "#2440e8" },
  forest:     { name: "Forest",     accent: "#127a4b" },
  magenta:    { name: "Magenta",    accent: "#d6217e" },
  violet:     { name: "Violet",     accent: "#6a3de8" },
  ochre:      { name: "Ochre",      accent: "#c4820e" },
};

export const STYLES = ["strings", "bars", "spectrum", "scope", "pulse", "particles", "beam", "pixels"] as const;
export type Style = (typeof STYLES)[number];

const TAU = Math.PI * 2;

let level = 0.12, target = 0.12, speaking = 0;
export const pointer = { x: 0.5, active: 0 };
export function speak(ms = 2600) { speaking = performance.now() + ms; }
export function setPointer(nx: number, active: number) { pointer.x = nx; pointer.active = active; }

type Node = {
  canvas: HTMLCanvasElement; ctx: CanvasRenderingContext2D;
  style: () => Style; theme: () => Theme; visible: () => boolean; hero?: boolean;
  w: number; h: number;
};
const nodes = new Set<Node>();
let running = false;

function fit(n: Node) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = n.canvas.clientWidth || n.canvas.width;
  const h = n.canvas.clientHeight || n.canvas.height;
  n.canvas.width = Math.max(1, w * dpr); n.canvas.height = Math.max(1, h * dpr);
  n.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  n.w = w; n.h = h;
}

export function register(canvas: HTMLCanvasElement, style: () => Style, theme: () => Theme, visible: () => boolean, hero = false) {
  const ctx = canvas.getContext("2d")!;
  const n: Node = { canvas, ctx, style, theme, visible, hero, w: 0, h: 0 };
  fit(n); nodes.add(n);
  if (!running) { running = true; requestAnimationFrame(loop); }
  const onResize = () => fit(n);
  window.addEventListener("resize", onResize);
  return () => { nodes.delete(n); window.removeEventListener("resize", onResize); };
}

function envelope(t: number) {
  target = speaking > t
    ? 0.42 + 0.42 * Math.abs(Math.sin(t / 130)) * (0.6 + 0.4 * Math.sin(t / 43))
    : 0.12 + 0.05 * Math.sin(t / 900);
  level += (target - level) * 0.08;
  return level;
}
function loop(t: number) {
  const lv = envelope(t);
  nodes.forEach(n => { if (n.visible()) { n.ctx.clearRect(0, 0, n.w, n.h); draw(n, t, lv); } });
  if (nodes.size) requestAnimationFrame(loop); else running = false;
}

function poly(c: CanvasRenderingContext2D, pts: number[][], col: string, w: number) {
  c.beginPath(); pts.forEach((p, i) => i ? c.lineTo(p[0], p[1]) : c.moveTo(p[0], p[1]));
  c.strokeStyle = col; c.lineWidth = w; c.lineCap = "round"; c.lineJoin = "round"; c.stroke();
}
function disc(c: CanvasRenderingContext2D, x: number, y: number, r: number, col: string) { c.beginPath(); c.arc(x, y, r, 0, TAU); c.fillStyle = col; c.fill(); }

function draw(n: Node, t: number, lv: number) {
  const { ctx, w, h } = n, mid = h / 2, sc = h / 56;
  const accent = n.theme().accent;
  const style = n.style();
  const lean = n.hero ? (pointer.x - 0.5) * pointer.active : 0;
  ctx.lineCap = "round"; ctx.lineJoin = "round";

  if (style === "strings") {
    const amp = (2.2 + 12 * lv) * sc * (1 + 0.3 * Math.abs(lean));
    const palette = [INK, accent, INK_SOFT];
    const widths = [2.1, 1.8, 1.4];
    for (let i = 0; i < 3; i++) {
      const ph1 = t * 0.0026 + i * 2.1 + lean * 1.3, ph2 = t * 0.0017 - i * 1.4;
      const pts: number[][] = [];
      for (let j = 0; j <= 34; j++) {
        const u = j / 34, env = Math.sin(Math.PI * u);
        pts.push([u * w, mid + env * (amp * 0.72 * Math.sin(9.4 * u + ph1) + amp * 0.5 * Math.sin(14.6 * u - ph2))]);
      }
      poly(ctx, pts, palette[i], widths[i]);
    }
  } else if (style === "bars") {
    const N = 13, step = w / N, bw = 2.6 * sc;
    for (let i = 0; i < N; i++) {
      const ph = Math.sin(t * 0.012 + i * 0.9);
      const bh = (2 + (0.3 + 0.7 * Math.abs(ph)) * 12 * lv + 1.2) * sc;
      const cx = i * step + step / 2;
      ctx.strokeStyle = i % 4 === 2 ? accent : INK; ctx.lineWidth = bw;
      ctx.beginPath(); ctx.moveTo(cx, mid - bh); ctx.lineTo(cx, mid + bh); ctx.stroke();
    }
  } else if (style === "spectrum") {
    const maxa = (2 + 12 * lv) * sc, top: number[][] = [], bot: number[][] = [];
    for (let j = 0; j <= 42; j++) {
      const u = j / 42, env = Math.sin(Math.PI * u);
      const a = env * maxa * (0.35 + 0.65 * Math.abs(Math.sin(7.1 * u + t * 0.008) * Math.sin(3.3 * u - t * 0.004)));
      top.push([u * w, mid - a]); bot.push([u * w, mid + a]);
    }
    poly(ctx, top, INK, 1.8); poly(ctx, bot, accent, 1.8);
  } else if (style === "scope") {
    const amp = (1.5 + 11 * lv) * sc, pts: number[][] = [];
    for (let j = 0; j <= 64; j++) { const u = j / 64, env = Math.sin(Math.PI * u); pts.push([u * w, mid + env * amp * (Math.sin(18 * u + t * 0.018) + 0.4 * Math.sin(31 * u - t * 0.013))]); }
    poly(ctx, pts, INK, 1.5);
  } else if (style === "pulse") {
    const cx = w / 2, r = (5 + 8 * lv + 1.2 * Math.sin(t * 0.012)) * sc;
    if (lv > 0.12) for (let k = 0; k < 2; k++) { const prog = ((t * 0.00035 + k * 0.5) % 1); ctx.globalAlpha = 1 - prog; ctx.lineWidth = 1.3; ctx.beginPath(); ctx.arc(cx, mid, r + prog * (w / 2 - r), 0, TAU); ctx.strokeStyle = k ? accent : INK_SOFT; ctx.stroke(); ctx.globalAlpha = 1; }
    disc(ctx, cx, mid, r, accent);
  } else if (style === "particles") {
    for (let i = 0; i < 16; i++) { const u = (i + 0.5) / 16, y = mid + Math.sin(t * 0.0085 + i * 1.7) * (2 + 10 * lv) * sc * Math.sin(Math.PI * u); const r = (1 + ((i * 53) % 9) / 9 * 1.3) * sc; disc(ctx, u * w, y, r, i % 3 === 1 ? accent : INK); }
  } else if (style === "beam") {
    const orb = (3 + 5 * lv + 0.8 * Math.sin(t * 0.018)) * sc, bx = orb + 4;
    ctx.strokeStyle = INK; ctx.lineWidth = Math.max(1.5, (1 + 5 * lv) * sc); ctx.beginPath(); ctx.moveTo(bx, mid); ctx.lineTo(w - 4, mid); ctx.stroke();
    disc(ctx, bx, mid, orb, accent);
  } else if (style === "pixels") {
    const N = 12, step = w / N, block = 2.2 * sc, gap = 2.4;
    for (let i = 0; i < N; i++) { const ph = Math.abs(Math.sin(t * 0.01 + i * 1.1)), levels = 1 + Math.floor((0.25 + 0.75 * ph) * lv * 4 + 0.4); const cx = i * step + step / 2; ctx.fillStyle = i % 5 === 2 ? accent : INK; for (let k = 0; k < levels; k++) { const off = k * (block + gap); ctx.fillRect(cx - block / 2, mid - off - block, block, block); ctx.fillRect(cx - block / 2, mid + off, block, block); } }
  }
  ctx.globalAlpha = 1;
}

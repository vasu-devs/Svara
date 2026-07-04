/* Svara visualizer engine — "ink on paper" edition. Ribbons render as soft,
   multiply-blended silk on a warm page; six moods recolor the whole site via
   CSS custom properties (--accent/--c1/--c2/--c3/--tint/--tint2/--paper/--panel). */

export type Mood = { key: string; name: string; accent: string; cols: [string, string, string] };

export const MOODS: Record<string, Mood> = {
  sienna: { key: "sienna", name: "Sienna", accent: "#c1573a", cols: ["#e08a5e", "#c1573a", "#8f3a26"] },
  ochre:  { key: "ochre",  name: "Ochre",  accent: "#c99a2e", cols: ["#e6be5a", "#c99a2e", "#96721c"] },
  olive:  { key: "olive",  name: "Olive",  accent: "#6f8a3e", cols: ["#93b263", "#6f8a3e", "#4d6428"] },
  petrol: { key: "petrol", name: "Petrol", accent: "#2f8482", cols: ["#5fada9", "#2f8482", "#1c605e"] },
  indigo: { key: "indigo", name: "Indigo", accent: "#4a5f9e", cols: ["#7889c4", "#4a5f9e", "#33447a"] },
  mauve:  { key: "mauve",  name: "Mauve",  accent: "#954a86", cols: ["#bb75ab", "#954a86", "#6b3260"] },
};
export const MOOD_ORDER = ["sienna", "ochre", "olive", "petrol", "indigo", "mauve"];

export const STYLES = ["strings", "bars", "spectrum", "scope", "pulse", "particles", "beam", "pixels"] as const;
export type Style = (typeof STYLES)[number];

function hexRgba(hex: string, a: number): string {
  const h = hex.replace("#", "");
  const n = parseInt(h.length === 3 ? h.split("").map((c) => c + c).join("") : h, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}
function mix(hex: string, base: string, amt: number): string {
  const p = (h: string) => { h = h.replace("#", ""); const n = parseInt(h.length === 3 ? h.split("").map((c) => c + c).join("") : h, 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; };
  const a = p(hex), b = p(base), r = b.map((v, i) => Math.round(v + (a[i] - v) * amt));
  return `rgb(${r[0]},${r[1]},${r[2]})`;
}

/** Recolor the whole page for a mood — mirrors the design's applyTheme(). */
export function applyMood(key: string) {
  const m = MOODS[key] || MOODS.sienna;
  const d = document.documentElement.style;
  d.setProperty("--accent", m.accent);
  d.setProperty("--c1", m.cols[0]); d.setProperty("--c2", m.cols[1]); d.setProperty("--c3", m.cols[2]);
  d.setProperty("--tint", hexRgba(m.accent, 0.22));
  d.setProperty("--tint2", hexRgba(m.cols[0], 0.17));
  d.setProperty("--paper", mix(m.accent, "#ece3d0", 0.16));
  d.setProperty("--panel", mix(m.accent, "#faf5ec", 0.07));
}

const TAU = Math.PI * 2;
let level = 0.15, target = 0.15, speaking = 0;
export const pointer = { x: 0.5, active: 0 };
export function speak(ms = 2200) { speaking = performance.now() + ms; }
export function setPointer(nx: number, active: number) { pointer.x = nx; pointer.active = active; }

function rootCols(): [string, string, string] {
  const s = getComputedStyle(document.documentElement);
  return [
    s.getPropertyValue("--c1").trim() || "#e08a5e",
    s.getPropertyValue("--c2").trim() || "#c1573a",
    s.getPropertyValue("--c3").trim() || "#8f3a26",
  ];
}

type Node = { canvas: HTMLCanvasElement; ctx: CanvasRenderingContext2D; style: () => Style; visible: () => boolean; hero?: boolean; w: number; h: number };
const nodes = new Set<Node>();
let running = false;

function fit(n: Node) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = n.canvas.clientWidth || n.canvas.width, h = n.canvas.clientHeight || n.canvas.height;
  n.canvas.width = Math.max(1, w * dpr); n.canvas.height = Math.max(1, h * dpr);
  n.ctx.setTransform(dpr, 0, 0, dpr, 0, 0); n.w = w; n.h = h;
}
export function register(canvas: HTMLCanvasElement, style: () => Style, visible: () => boolean, hero = false) {
  const ctx = canvas.getContext("2d")!;
  const n: Node = { canvas, ctx, style, visible, hero, w: 0, h: 0 };
  fit(n); nodes.add(n);
  if (!running) { running = true; requestAnimationFrame(loop); }
  const onResize = () => fit(n);
  window.addEventListener("resize", onResize);
  return () => { nodes.delete(n); window.removeEventListener("resize", onResize); };
}
function envelope(t: number) {
  target = speaking > t ? 0.42 + 0.36 * Math.abs(Math.sin(t / 150)) * (0.62 + 0.38 * Math.sin(t / 47)) : 0.15 + 0.06 * Math.sin(t / 1100);
  level += (target - level) * 0.06; return level;
}
function loop(t: number) {
  const lv = envelope(t);
  const gc = rootCols();
  nodes.forEach((n) => { if (n.visible()) { n.ctx.clearRect(0, 0, n.w, n.h); draw(n, t, lv, gc); } });
  if (nodes.size) requestAnimationFrame(loop); else running = false;
}
function disc(c: CanvasRenderingContext2D, x: number, y: number, r: number, s: string) { c.beginPath(); c.arc(x, y, r, 0, TAU); c.fillStyle = s; c.fill(); }

function draw(n: Node, t: number, lv: number, cols: [string, string, string]) {
  const { ctx, w, h } = n, mid = h / 2, sc = h / 56;
  const col = (i: number) => cols[i % 3];
  const style = n.style();
  const rich = !!n.hero; // hero panels get more strands + softer bloom
  const lean = n.hero ? (pointer.x - 0.5) * pointer.active : 0;
  ctx.lineCap = "round"; ctx.lineJoin = "round";

  if (style === "strings") {
    const strands = rich ? 7 : 4;
    const amp = (3 + 15 * lv) * sc * (1 + 0.4 * Math.abs(lean));
    for (let i = 0; i < strands; i++) {
      const c = col(i % 3);
      const ph1 = t * 0.0014 + i * 0.9 + lean * 1.2, ph2 = t * 0.0009 - i * 0.7;
      const ys = 1 - (i % 3) * 0.16;
      ctx.beginPath();
      for (let j = 0; j <= 52; j++) { const u = j / 52, env = Math.pow(Math.sin(Math.PI * u), 0.82); const y = mid + env * (amp * ys * 0.72 * Math.sin(7.1 * u + ph1) + amp * ys * 0.44 * Math.sin(11.3 * u - ph2)); j ? ctx.lineTo(u * w, y) : ctx.moveTo(u * w, y); }
      ctx.strokeStyle = c;
      ctx.globalCompositeOperation = "multiply";
      ctx.globalAlpha = rich ? 0.17 : 0.2; ctx.lineWidth = (rich ? 7 : 5) * (0.6 + h / 260); ctx.stroke();
      ctx.globalCompositeOperation = "source-over";
      ctx.globalAlpha = rich ? 0.5 : 0.62; ctx.lineWidth = 1.3; ctx.stroke();
    }
  } else if (style === "bars") {
    const N = 13, step = w / N, bw = 3.4;
    for (let i = 0; i < N; i++) { const ph = Math.sin(t * 0.011 + i * 0.9); const bh = (2 + (0.3 + 0.7 * Math.abs(ph)) * 12 * lv + 1.2) * sc; const cx = i * step + step / 2; ctx.strokeStyle = col(i); ctx.globalAlpha = 0.85; ctx.lineWidth = bw; ctx.beginPath(); ctx.moveTo(cx, mid - bh); ctx.lineTo(cx, mid + bh); ctx.stroke(); }
  } else if (style === "spectrum") {
    const maxa = (2 + 12 * lv) * sc, top: number[][] = [], bot: number[][] = [];
    for (let j = 0; j <= 44; j++) { const u = j / 44, env = Math.sin(Math.PI * u); const a = env * maxa * (0.35 + 0.65 * Math.abs(Math.sin(7.1 * u + t * 0.007) * Math.sin(3.3 * u - t * 0.004))); top.push([u * w, mid - a]); bot.push([u * w, mid + a]); }
    ctx.globalCompositeOperation = "multiply"; ctx.beginPath(); [...top, ...bot.slice().reverse()].forEach((p, i) => i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])); ctx.closePath(); ctx.fillStyle = col(0); ctx.globalAlpha = 0.16; ctx.fill();
    ctx.globalCompositeOperation = "source-over"; ctx.globalAlpha = 0.7; ctx.lineWidth = 1.7;
    ctx.beginPath(); top.forEach((p, i) => i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])); ctx.strokeStyle = col(1); ctx.stroke();
    ctx.beginPath(); bot.forEach((p, i) => i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])); ctx.strokeStyle = col(2); ctx.stroke();
  } else if (style === "scope") {
    const amp = (1.5 + 11 * lv) * sc, pts: number[][] = [];
    for (let j = 0; j <= 66; j++) { const u = j / 66, env = Math.sin(Math.PI * u); pts.push([u * w, mid + env * amp * (Math.sin(18 * u + t * 0.016) + 0.4 * Math.sin(31 * u - t * 0.012))]); }
    ctx.beginPath(); pts.forEach((p, i) => i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]));
    ctx.globalCompositeOperation = "multiply"; ctx.globalAlpha = 0.2; ctx.lineWidth = 5; ctx.strokeStyle = col(0); ctx.stroke();
    ctx.globalCompositeOperation = "source-over"; ctx.globalAlpha = 0.62; ctx.lineWidth = 1.4; ctx.stroke();
  } else if (style === "pulse") {
    const cx = w / 2, r = (5 + 8 * lv + 1.2 * Math.sin(t * 0.011)) * sc;
    if (lv > 0.12) for (let k = 0; k < 2; k++) { const prog = (t * 0.00032 + k * 0.5) % 1; ctx.globalAlpha = (1 - prog) * 0.5; ctx.lineWidth = 1.4; ctx.beginPath(); ctx.arc(cx, mid, r + prog * (w / 2 - r), 0, TAU); ctx.strokeStyle = col(k + 1); ctx.stroke(); }
    ctx.globalCompositeOperation = "multiply"; ctx.globalAlpha = 0.22; disc(ctx, cx, mid, r * 2, col(0));
    ctx.globalCompositeOperation = "source-over"; ctx.globalAlpha = 0.85; disc(ctx, cx, mid, r, col(0));
  } else if (style === "particles") {
    ctx.globalCompositeOperation = "multiply";
    for (let i = 0; i < 16; i++) { const u = (i + 0.5) / 16, y = mid + Math.sin(t * 0.008 + i * 1.7) * (2 + 10 * lv) * sc * Math.sin(Math.PI * u); const r = (1.2 + ((i * 53) % 9) / 9 * 1.6) * sc; ctx.globalAlpha = 0.45 + 0.4 * Math.abs(Math.sin(t * 0.005 + i * 0.8)); disc(ctx, u * w, y, r, col(i)); }
  } else if (style === "beam") {
    const orb = (3.2 + 5 * lv + 0.8 * Math.sin(t * 0.016)) * sc, bx = orb + 4;
    ctx.globalCompositeOperation = "multiply"; ctx.globalAlpha = 0.28; ctx.strokeStyle = col(2); ctx.lineWidth = (3 + 9 * lv) * sc; ctx.beginPath(); ctx.moveTo(bx, mid); ctx.lineTo(w - 4, mid); ctx.stroke();
    ctx.globalCompositeOperation = "source-over"; ctx.globalAlpha = 0.85; ctx.strokeStyle = col(0); ctx.lineWidth = Math.max(1.5, (1 + 4 * lv) * sc); ctx.beginPath(); ctx.moveTo(bx, mid); ctx.lineTo(w - 4, mid); ctx.stroke();
    ctx.globalCompositeOperation = "multiply"; ctx.globalAlpha = 0.24; disc(ctx, bx, mid, orb * 1.9, col(1));
    ctx.globalCompositeOperation = "source-over"; ctx.globalAlpha = 0.9; disc(ctx, bx, mid, orb, col(0));
  } else if (style === "pixels") {
    const N = 12, step = w / N, block = 2.4 * sc, gap = 2.4;
    ctx.globalAlpha = 0.85;
    for (let i = 0; i < N; i++) { const ph = Math.abs(Math.sin(t * 0.009 + i * 1.1)), levels = 1 + Math.floor((0.25 + 0.75 * ph) * lv * 4 + 0.4); const cx = i * step + step / 2; ctx.fillStyle = col(i); for (let k = 0; k < levels; k++) { const off = k * (block + gap); ctx.fillRect(cx - block / 2, mid - off - block, block, block); ctx.fillRect(cx - block / 2, mid + off, block, block); } }
  }
  ctx.globalAlpha = 1; ctx.globalCompositeOperation = "source-over";
}

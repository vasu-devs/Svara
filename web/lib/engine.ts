/* Visualizer engine, product edition: the real Svara ribbons in color with a
   soft glow, on dark. One shared rAF loop, cursor-reactive hero, tap-to-recolor. */

export type Theme = { name: string; accent: string; dot: string; cols: string[] };

export const THEMES: Record<string, Theme> = {
  aurora:    { name: "Aurora",    accent: "#22d3ee", dot: "#ff5fa2", cols: ["#ff5fa2", "#8b5cf6", "#22d3ee"] },
  cyberpunk: { name: "Cyberpunk", accent: "#00f0ff", dot: "#ff003c", cols: ["#fcee0a", "#00f0ff", "#ff003c"] },
  matrix:    { name: "Matrix",    accent: "#38ff88", dot: "#38ff88", cols: ["#00ff66", "#00cc44", "#8dffbb"] },
  sakura:    { name: "Sakura",    accent: "#ff8fab", dot: "#ff8fab", cols: ["#ff8fab", "#ffc2d1", "#e05780"] },
  dracula:   { name: "Dracula",   accent: "#bd93f9", dot: "#ff79c6", cols: ["#ff79c6", "#bd93f9", "#8be9fd"] },
  vaporwave: { name: "Vaporwave", accent: "#01cdfe", dot: "#ff71ce", cols: ["#ff71ce", "#01cdfe", "#05ffa1"] },
};

export const STYLES = ["strings", "bars", "spectrum", "scope", "pulse", "particles", "beam", "pixels"] as const;
export type Style = (typeof STYLES)[number];

const TAU = Math.PI * 2;

let level = 0.12, target = 0.12, speaking = 0;
export const pointer = { x: 0.5, active: 0 };
export function speak(ms = 2600) { speaking = performance.now() + ms; }
export function setPointer(nx: number, active: number) { pointer.x = nx; pointer.active = active; }

type Node = { canvas: HTMLCanvasElement; ctx: CanvasRenderingContext2D; style: () => Style; theme: () => Theme; visible: () => boolean; hero?: boolean; w: number; h: number };
const nodes = new Set<Node>();
let running = false;

function fit(n: Node) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = n.canvas.clientWidth || n.canvas.width, h = n.canvas.clientHeight || n.canvas.height;
  n.canvas.width = Math.max(1, w * dpr); n.canvas.height = Math.max(1, h * dpr);
  n.ctx.setTransform(dpr, 0, 0, dpr, 0, 0); n.w = w; n.h = h;
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
  target = speaking > t ? 0.42 + 0.42 * Math.abs(Math.sin(t / 130)) * (0.6 + 0.4 * Math.sin(t / 43)) : 0.12 + 0.05 * Math.sin(t / 900);
  level += (target - level) * 0.08; return level;
}
function loop(t: number) {
  const lv = envelope(t);
  nodes.forEach(n => { if (n.visible()) { n.ctx.clearRect(0, 0, n.w, n.h); draw(n, t, lv); } });
  if (nodes.size) requestAnimationFrame(loop); else running = false;
}
// The product IS colour: ribbons render in the active theme's palette.
const col = (n: Node, i: number) => n.theme().cols[i % 3];
function disc(c: CanvasRenderingContext2D, x: number, y: number, r: number, s: string) { c.beginPath(); c.arc(x, y, r, 0, TAU); c.fillStyle = s; c.fill(); }

function draw(n: Node, t: number, lv: number) {
  const { ctx, w, h } = n, mid = h / 2, sc = h / 56;
  const style = n.style();
  const lean = n.hero ? (pointer.x - 0.5) * pointer.active : 0;
  ctx.lineCap = "round"; ctx.lineJoin = "round";

  if (style === "strings") {
    const amp = (2.2 + 12.5 * lv) * sc * (1 + 0.3 * Math.abs(lean));
    for (let pass = 0; pass < 2; pass++)
      for (let i = 0; i < 3; i++) {
        const ph1 = t * 0.0027 + i * 2.1 + lean * 1.3, ph2 = t * 0.0018 - i * 1.4;
        ctx.beginPath();
        for (let j = 0; j <= 32; j++) { const u = j / 32, env = Math.sin(Math.PI * u); const y = mid + env * (amp * 0.72 * Math.sin(9.4 * u + ph1) + amp * 0.5 * Math.sin(14.6 * u - ph2)); j ? ctx.lineTo(u * w, y) : ctx.moveTo(u * w, y); }
        ctx.strokeStyle = col(n, i); ctx.globalAlpha = pass ? 1 : 0.3; ctx.lineWidth = pass ? 2 : 5.5; ctx.stroke();
      }
    ctx.globalAlpha = 1;
  } else if (style === "bars") {
    const N = 13, step = w / N, bw = 3.2;
    for (let i = 0; i < N; i++) { const ph = Math.sin(t * 0.012 + i * 0.9); const bh = (2 + (0.3 + 0.7 * Math.abs(ph)) * 12 * lv + 1.2) * sc; const cx = i * step + step / 2; ctx.strokeStyle = col(n, i); ctx.lineWidth = bw; ctx.beginPath(); ctx.moveTo(cx, mid - bh); ctx.lineTo(cx, mid + bh); ctx.stroke(); }
  } else if (style === "spectrum") {
    const maxa = (2 + 12 * lv) * sc, top: number[][] = [], bot: number[][] = [];
    for (let j = 0; j <= 42; j++) { const u = j / 42, env = Math.sin(Math.PI * u); const a = env * maxa * (0.35 + 0.65 * Math.abs(Math.sin(7.1 * u + t * 0.008) * Math.sin(3.3 * u - t * 0.004))); top.push([u * w, mid - a]); bot.push([u * w, mid + a]); }
    ctx.beginPath(); [...top, ...bot.slice().reverse()].forEach((p, i) => i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])); ctx.closePath(); ctx.fillStyle = col(n, 0); ctx.globalAlpha = 0.14; ctx.fill(); ctx.globalAlpha = 1;
    ctx.lineWidth = 1.8; ctx.beginPath(); top.forEach((p, i) => i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])); ctx.strokeStyle = col(n, 1); ctx.stroke();
    ctx.beginPath(); bot.forEach((p, i) => i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])); ctx.strokeStyle = col(n, 2); ctx.stroke();
  } else if (style === "scope") {
    const amp = (1.5 + 11 * lv) * sc, pts: number[][] = [];
    for (let j = 0; j <= 64; j++) { const u = j / 64, env = Math.sin(Math.PI * u); pts.push([u * w, mid + env * amp * (Math.sin(18 * u + t * 0.018) + 0.4 * Math.sin(31 * u - t * 0.013))]); }
    ctx.beginPath(); pts.forEach((p, i) => i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])); ctx.globalAlpha = 0.28; ctx.lineWidth = 4.5; ctx.strokeStyle = col(n, 0); ctx.stroke();
    ctx.globalAlpha = 1; ctx.lineWidth = 1.5; ctx.stroke();
  } else if (style === "pulse") {
    const cx = w / 2, r = (5 + 8 * lv + 1.2 * Math.sin(t * 0.012)) * sc;
    if (lv > 0.12) for (let k = 0; k < 2; k++) { const prog = ((t * 0.00035 + k * 0.5) % 1); ctx.globalAlpha = (1 - prog) * 0.55; ctx.lineWidth = 1.4; ctx.beginPath(); ctx.arc(cx, mid, r + prog * (w / 2 - r), 0, TAU); ctx.strokeStyle = col(n, k + 1); ctx.stroke(); }
    ctx.globalAlpha = 0.25; disc(ctx, cx, mid, r * 2, col(n, 0)); ctx.globalAlpha = 1; disc(ctx, cx, mid, r, col(n, 0));
  } else if (style === "particles") {
    for (let i = 0; i < 16; i++) { const u = (i + 0.5) / 16, y = mid + Math.sin(t * 0.0085 + i * 1.7) * (2 + 10 * lv) * sc * Math.sin(Math.PI * u); const r = (1.1 + ((i * 53) % 9) / 9 * 1.5) * sc; ctx.globalAlpha = 0.5 + 0.45 * Math.abs(Math.sin(t * 0.006 + i * 0.8)); disc(ctx, u * w, y, r, col(n, i)); }
    ctx.globalAlpha = 1;
  } else if (style === "beam") {
    const orb = (3.2 + 5 * lv + 0.8 * Math.sin(t * 0.018)) * sc, bx = orb + 4;
    ctx.globalAlpha = 0.3; ctx.strokeStyle = col(n, 2); ctx.lineWidth = (3 + 9 * lv) * sc; ctx.beginPath(); ctx.moveTo(bx, mid); ctx.lineTo(w - 4, mid); ctx.stroke();
    ctx.globalAlpha = 1; ctx.strokeStyle = col(n, 0); ctx.lineWidth = Math.max(1.5, (1 + 4 * lv) * sc); ctx.beginPath(); ctx.moveTo(bx, mid); ctx.lineTo(w - 4, mid); ctx.stroke();
    ctx.globalAlpha = 0.25; disc(ctx, bx, mid, orb * 1.9, col(n, 1)); ctx.globalAlpha = 1; disc(ctx, bx, mid, orb, col(n, 0));
  } else if (style === "pixels") {
    const N = 12, step = w / N, block = 2.3 * sc, gap = 2.4;
    for (let i = 0; i < N; i++) { const ph = Math.abs(Math.sin(t * 0.01 + i * 1.1)), levels = 1 + Math.floor((0.25 + 0.75 * ph) * lv * 4 + 0.4); const cx = i * step + step / 2; ctx.fillStyle = col(n, i); for (let k = 0; k < levels; k++) { const off = k * (block + gap); ctx.fillRect(cx - block / 2, mid - off - block, block, block); ctx.fillRect(cx - block / 2, mid + off, block, block); } }
  }
  ctx.globalAlpha = 1;
}

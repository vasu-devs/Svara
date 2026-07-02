/* Shared visualizer engine: the app's real Siri-style ribbon math plus 7 more
   styles, driven by ONE rAF loop. Canvases register themselves; the loop
   updates a shared time + voice-level envelope and redraws visible ones.
   A pointer influence lets the hero ribbons lean toward the cursor. */

export type Theme = {
  name: string; accent: string; dot: string; cols: string[] | null; rainbow?: boolean;
};

export const THEMES: Record<string, Theme> = {
  aurora:    { name: "Aurora",    accent: "#22d3ee", dot: "#ff5fa2", cols: ["#ff5fa2", "#8b5cf6", "#22d3ee"] },
  cyberpunk: { name: "Cyberpunk", accent: "#00f0ff", dot: "#ff003c", cols: ["#fcee0a", "#00f0ff", "#ff003c"] },
  matrix:    { name: "Matrix",    accent: "#00ff66", dot: "#00ff66", cols: ["#00ff66", "#00cc44", "#8dffbb"] },
  sakura:    { name: "Sakura",    accent: "#ff8fab", dot: "#ff8fab", cols: ["#ff8fab", "#ffc2d1", "#e05780"] },
  dracula:   { name: "Dracula",   accent: "#bd93f9", dot: "#ff79c6", cols: ["#ff79c6", "#bd93f9", "#8be9fd"] },
  midas:     { name: "Midas",     accent: "#ffd700", dot: "#ffd700", cols: ["#ffd700", "#ffb84d", "#fff2b0"] },
  vaporwave: { name: "Vaporwave", accent: "#01cdfe", dot: "#ff71ce", cols: ["#ff71ce", "#01cdfe", "#05ffa1"] },
  rgb:       { name: "RGB",       accent: "#ff3d7f", dot: "#ff0055", cols: null, rainbow: true },
};

export const STYLES = ["strings", "bars", "spectrum", "scope", "pulse", "particles", "beam", "pixels"] as const;
export type Style = (typeof STYLES)[number];

const TAU = Math.PI * 2;
const rainbow = (i: number, t: number) => `hsl(${((t * 0.00006 + i / 3) % 1) * 360} 90% 62%)`;

type Node = {
  canvas: HTMLCanvasElement; ctx: CanvasRenderingContext2D;
  style: () => Style; theme: () => Theme; visible: () => boolean; hero?: boolean;
  w: number; h: number; dpr: number;
};

const nodes = new Set<Node>();
let running = false;
let level = 0.12, target = 0.12, speaking = 0;
export let pointer = { x: 0.5, active: 0 };

export function speak(ms = 2600) { speaking = performance.now() + ms; }
export function setPointer(nx: number, active: number) { pointer.x = nx; pointer.active = active; }

function fit(n: Node) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = n.canvas.clientWidth || n.canvas.width;
  const h = n.canvas.clientHeight || n.canvas.height;
  n.canvas.width = Math.max(1, w * dpr); n.canvas.height = Math.max(1, h * dpr);
  n.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  n.w = w; n.h = h; n.dpr = dpr;
}

export function register(
  canvas: HTMLCanvasElement, style: () => Style, theme: () => Theme, visible: () => boolean, hero = false
) {
  const ctx = canvas.getContext("2d")!;
  const n: Node = { canvas, ctx, style, theme, visible, hero, w: 0, h: 0, dpr: 1 };
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

const colAt = (n: Node, i: number, t: number) => n.theme().rainbow ? rainbow(i, t) : (n.theme().cols as string[])[i % 3];
function poly(c: CanvasRenderingContext2D, pts: number[][], col: string) { c.beginPath(); pts.forEach((p, i) => i ? c.lineTo(p[0], p[1]) : c.moveTo(p[0], p[1])); c.strokeStyle = col; c.stroke(); }
function disc(c: CanvasRenderingContext2D, x: number, y: number, r: number, col: string) { c.beginPath(); c.arc(x, y, r, 0, TAU); c.fillStyle = col; c.fill(); }
function rr(c: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) { c.beginPath(); c.moveTo(x + r, y); c.arcTo(x + w, y, x + w, y + h, r); c.arcTo(x + w, y + h, x, y + h, r); c.arcTo(x, y + h, x, y, r); c.arcTo(x, y, x + w, y, r); c.closePath(); }

function draw(n: Node, t: number, lv: number) {
  const { ctx, w, h } = n, mid = h / 2, sc = h / 56;
  const style = n.style();
  // hero canvases lean toward the cursor
  const lean = n.hero ? (pointer.x - 0.5) * pointer.active : 0;

  if (style === "strings") {
    const amp = (2.2 + 12.5 * lv) * sc * (1 + 0.35 * Math.abs(lean));
    for (let pass = 0; pass < 2; pass++)
      for (let i = 0; i < 3; i++) {
        const ph1 = t * 0.0028 + i * 2.1 + lean * 1.4, ph2 = t * 0.0018 - i * 1.4;
        ctx.beginPath();
        for (let j = 0; j <= 30; j++) {
          const u = j / 30, env = Math.sin(Math.PI * u);
          const y = mid + env * (amp * 0.72 * Math.sin(9.4 * u + ph1) + amp * 0.5 * Math.sin(14.6 * u - ph2));
          j ? ctx.lineTo(u * w, y) : ctx.moveTo(u * w, y);
        }
        ctx.strokeStyle = colAt(n, i, t); ctx.lineCap = "round";
        ctx.globalAlpha = pass ? 1 : 0.34; ctx.lineWidth = pass ? 2 : 5; ctx.stroke();
      }
    ctx.globalAlpha = 1;
  } else if (style === "bars") {
    const N = 12, step = w / N, bw = 3.4;
    for (let i = 0; i < N; i++) {
      const ph = Math.sin(t * 0.012 + i * 0.9);
      const bh = (2 + (0.3 + 0.7 * Math.abs(ph)) * 13 * lv + 1.2) * sc;
      const cx = i * step + step / 2;
      ctx.fillStyle = colAt(n, i, t); ctx.globalAlpha = 0.95; rr(ctx, cx - bw / 2, mid - bh, bw, bh * 2, bw / 2); ctx.fill();
    }
    ctx.globalAlpha = 1;
  } else if (style === "spectrum") {
    const maxa = (2 + 12 * lv) * sc, top: number[][] = [], bot: number[][] = [];
    for (let j = 0; j <= 40; j++) {
      const u = j / 40, env = Math.sin(Math.PI * u);
      const a = env * maxa * (0.35 + 0.65 * Math.abs(Math.sin(7.1 * u + t * 0.008) * Math.sin(3.3 * u - t * 0.004)));
      top.push([u * w, mid - a]); bot.push([u * w, mid + a]);
    }
    ctx.beginPath(); [...top, ...bot.reverse()].forEach((p, i) => i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]));
    ctx.closePath(); ctx.fillStyle = colAt(n, 0, t); ctx.globalAlpha = 0.16; ctx.fill();
    ctx.globalAlpha = 0.9; ctx.lineWidth = 1.8; ctx.lineJoin = "round"; poly(ctx, top, colAt(n, 1, t)); poly(ctx, bot, colAt(n, 2, t)); ctx.globalAlpha = 1;
  } else if (style === "scope") {
    const amp = (1.5 + 11 * lv) * sc, pts: number[][] = [];
    for (let j = 0; j <= 60; j++) { const u = j / 60, env = Math.sin(Math.PI * u); pts.push([u * w, mid + env * amp * (Math.sin(18 * u + t * 0.018) + 0.4 * Math.sin(31 * u - t * 0.013))]); }
    ctx.lineCap = "round"; ctx.globalAlpha = 0.28; ctx.lineWidth = 4; poly(ctx, pts, colAt(n, 0, t)); ctx.globalAlpha = 1; ctx.lineWidth = 1.3; poly(ctx, pts, colAt(n, 0, t));
  } else if (style === "pulse") {
    const cx = w / 2, r = (5 + 9 * lv + 1.2 * Math.sin(t * 0.012)) * sc;
    if (lv > 0.12) for (let k = 0; k < 2; k++) { const prog = ((t * 0.00035 + k * 0.5) % 1), rr2 = r + prog * (w / 2 - r); ctx.globalAlpha = (1 - prog) * 0.5; ctx.lineWidth = 1.4; ctx.beginPath(); ctx.arc(cx, mid, rr2, 0, TAU); ctx.strokeStyle = colAt(n, k + 1, t); ctx.stroke(); }
    ctx.globalAlpha = 0.28; disc(ctx, cx, mid, r * 2, colAt(n, 0, t)); ctx.globalAlpha = 1; disc(ctx, cx, mid, r, colAt(n, 0, t));
  } else if (style === "particles") {
    for (let i = 0; i < 15; i++) { const u = (i + 0.5) / 15, y = mid + Math.sin(t * 0.0085 + i * 1.7) * (2 + 10 * lv) * sc * Math.sin(Math.PI * u); const r = (1.1 + ((i * 53) % 9) / 9 * 1.6) * sc * 2; ctx.globalAlpha = 0.45 + 0.45 * Math.abs(Math.sin(t * 0.006 + i * 0.8)); disc(ctx, u * w, y, r, colAt(n, i, t)); }
    ctx.globalAlpha = 1;
  } else if (style === "beam") {
    const orb = (3.5 + 5 * lv + 0.8 * Math.sin(t * 0.018)) * sc, bx = orb + 4, thick = (1.2 + 9 * lv) * sc, top: number[][] = [], bot: number[][] = [];
    for (let j = 0; j <= 24; j++) { const u = j / 24, x = bx + u * (w - bx - 4), wob = Math.sin(11 * u - t * 0.027) * thick * 0.25; top.push([x, mid - thick / 2 + wob]); bot.push([x, mid + thick / 2 + wob]); }
    ctx.beginPath(); [...top, ...bot.reverse()].forEach((p, i) => i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])); ctx.closePath(); ctx.fillStyle = colAt(n, 2, t); ctx.globalAlpha = 0.4; ctx.fill();
    ctx.globalAlpha = 1; ctx.lineWidth = Math.max(2, thick * 0.35); ctx.lineCap = "round"; ctx.beginPath(); ctx.moveTo(bx, mid); ctx.lineTo(w - 4, mid); ctx.strokeStyle = colAt(n, 0, t); ctx.stroke();
    ctx.globalAlpha = 0.28; disc(ctx, bx, mid, orb * 1.9, colAt(n, 1, t)); ctx.globalAlpha = 1; disc(ctx, bx, mid, orb, colAt(n, 0, t));
  } else if (style === "pixels") {
    const N = 11, step = w / N, block = 2.6 * sc * 2, gap = 2;
    for (let i = 0; i < N; i++) { const ph = Math.abs(Math.sin(t * 0.01 + i * 1.1)), levels = 1 + Math.floor((0.25 + 0.75 * ph) * lv * 4 + 0.4); const cx = i * step + step / 2; ctx.fillStyle = colAt(n, i, t); ctx.globalAlpha = 0.95; for (let k = 0; k < levels; k++) { const off = k * (block + gap); ctx.fillRect(cx - block / 2, mid - off - block, block, block); ctx.fillRect(cx - block / 2, mid + off, block, block); } }
    ctx.globalAlpha = 1;
  }
}

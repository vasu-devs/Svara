"use client";

import { useEffect, useRef } from "react";
import { speak } from "@/lib/engine";
import { Visualizer } from "./Visualizer";

/* Svara's pill: the one dark object on the page. Like the real one it listens,
   shows a level, and can be dragged around; it springs home when let go. */
export function Pill({ live, label, className = "", onTap }: { live: boolean; label?: string; className?: string; onTap?: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const drag = useRef({ on: false, ox: 0, oy: 0, px: 0, py: 0, vx: 0, vy: 0, lx: 0, ly: 0 });
  const press = useRef({ x: 0, y: 0, moved: 0 });
  useEffect(() => () => { timers.current.forEach(clearTimeout); }, []);
  const cx = (v: number) => Math.max(-320, Math.min(80, v));
  const cy = (v: number) => Math.max(-260, Math.min(120, v));

  return (
    <div className={`pill ${live ? "live" : ""} ${className}`} ref={ref} title="Drag me"
      onPointerDown={(e) => {
        const el = ref.current; if (!el) return;
        timers.current.forEach(clearTimeout); timers.current = [];
        try { el.setPointerCapture(e.pointerId); } catch { /* noop */ }
        const d = drag.current; d.on = true; el.style.transition = "none";
        d.ox = e.clientX - d.px; d.oy = e.clientY - d.py; d.lx = e.clientX; d.ly = e.clientY;
        press.current = { x: e.clientX, y: e.clientY, moved: 0 };
      }}
      onPointerMove={(e) => {
        const el = ref.current; const d = drag.current; if (!el || !d.on) return;
        d.px = cx(e.clientX - d.ox); d.py = cy(e.clientY - d.oy);
        d.vx = e.clientX - d.lx; d.vy = e.clientY - d.ly; d.lx = e.clientX; d.ly = e.clientY;
        press.current.moved = Math.max(press.current.moved, Math.hypot(e.clientX - press.current.x, e.clientY - press.current.y));
        const tilt = Math.max(-8, Math.min(8, d.vx));
        el.style.transform = `translate(${d.px}px,${d.py}px) rotate(${tilt}deg)`;
        speak(240);
      }}
      onPointerUp={() => {
        const el = ref.current; const d = drag.current; if (!el || !d.on) return;
        d.on = false;
        if (press.current.moved < 5 && onTap) { el.style.transition = ""; onTap(); return; }
        d.px = cx(d.px + d.vx * 4); d.py = cy(d.py + d.vy * 4);
        el.style.transition = "transform .5s cubic-bezier(.2,.8,.2,1)";
        el.style.transform = `translate(${d.px}px,${d.py}px) rotate(0deg)`;
        timers.current.push(setTimeout(() => {
          el.style.transition = "transform 1.1s cubic-bezier(.19,1,.22,1)";
          d.px = 0; d.py = 0; el.style.transform = "translate(0,0) rotate(0deg)";
        }, 900));
      }}
      onPointerCancel={() => {
        drag.current.on = false; drag.current.px = 0; drag.current.py = 0;
        if (ref.current) { ref.current.style.transform = ""; ref.current.style.transition = ""; }
      }}>
      <span className="pill-dot" />
      <Visualizer style="bars" onDark className="pill-viz" />
      {label && <span className="pill-lbl mono">{label}</span>}
    </div>
  );
}

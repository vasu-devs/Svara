"use client";
import { useEffect, useRef } from "react";
import { register, requestDraw, type Style } from "@/lib/engine";

export function Visualizer({
  style, hero = false, onDark = false, className, ariaHidden = true,
}: { style: Style; hero?: boolean; onDark?: boolean; className?: string; ariaHidden?: boolean }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const styleRef = useRef(style); styleRef.current = style;
  const visible = useRef(true);

  useEffect(() => {
    const c = ref.current; if (!c) return;
    const io = new IntersectionObserver(([e]) => { visible.current = e.isIntersecting; requestDraw(); }, { rootMargin: "120px" });
    io.observe(c);
    const unregister = register(c, () => styleRef.current, () => visible.current, hero, onDark);
    return () => { io.disconnect(); unregister(); };
  }, [hero, onDark]);
  useEffect(() => { requestDraw(); }, [style]);

  return <canvas ref={ref} className={className} aria-hidden={ariaHidden} />;
}

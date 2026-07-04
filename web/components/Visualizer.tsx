"use client";
import { useEffect, useRef } from "react";
import { register, type Style } from "@/lib/engine";

export function Visualizer({
  style, hero = false, className, ariaHidden = true,
}: { style: Style; hero?: boolean; className?: string; ariaHidden?: boolean }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const styleRef = useRef(style); styleRef.current = style;
  const visible = useRef(true);

  useEffect(() => {
    const c = ref.current; if (!c) return;
    const io = new IntersectionObserver(([e]) => { visible.current = e.isIntersecting; }, { rootMargin: "120px" });
    io.observe(c);
    const unregister = register(c, () => styleRef.current, () => visible.current, hero);
    return () => { io.disconnect(); unregister(); };
  }, [hero]);

  return <canvas ref={ref} className={className} aria-hidden={ariaHidden} />;
}

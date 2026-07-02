"use client";
import { useEffect, useRef } from "react";
import { register, THEMES, type Style, type Theme } from "@/lib/engine";

export function Visualizer({
  style, themeKey, hero = false, className, ariaHidden = true,
}: { style: Style; themeKey: string; hero?: boolean; className?: string; ariaHidden?: boolean }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const styleRef = useRef(style); styleRef.current = style;
  const themeRef = useRef(themeKey); themeRef.current = themeKey;
  const visible = useRef(true);

  useEffect(() => {
    const c = ref.current; if (!c) return;
    const io = new IntersectionObserver(([e]) => { visible.current = e.isIntersecting; }, { rootMargin: "120px" });
    io.observe(c);
    const getTheme = (): Theme => THEMES[themeRef.current] || THEMES.aurora;
    const unregister = register(c, () => styleRef.current, getTheme, () => visible.current, hero);
    return () => { io.disconnect(); unregister(); };
  }, [hero]);

  return <canvas ref={ref} className={className} aria-hidden={ariaHidden} />;
}

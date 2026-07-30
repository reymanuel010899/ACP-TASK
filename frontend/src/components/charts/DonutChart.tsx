"use client";

import { useEffect, useRef, type ReactNode } from "react";

export type DonutSegment = { label: string; value: number; color: string };

/**
 * Crisp canvas donut chart (HiDPI-aware). Draws a soft neutral track plus one
 * arc per segment with a subtle same-color glow. The center stays transparent
 * so the card background shows through and `children` can be overlaid (total,
 * caption, ...). Accent colors are passed in and identical across themes; the
 * only theme-neutral paint is the track (a low-alpha slate), so the chart looks
 * right in both light and dark without reading CSS variables.
 */
export default function DonutChart({
  data,
  size = 130,
  thickness = 22,
  gap = 0.06,
  children,
}: {
  data: DonutSegment[];
  size?: number;
  thickness?: number;
  gap?: number;
  children?: ReactNode;
}) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    canvas.width = size * dpr;
    canvas.height = size * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, size, size);

    const cx = size / 2;
    const cy = size / 2;
    const r = (size - thickness) / 2 - 2;
    const total = data.reduce((s, d) => s + d.value, 0) || 1;

    // Neutral track
    ctx.lineCap = "butt";
    ctx.lineWidth = thickness;
    ctx.strokeStyle = "rgba(148,163,184,0.12)";
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.stroke();

    // Segments
    let start = -Math.PI / 2;
    const hasMany = data.length > 1;
    for (const d of data) {
      const frac = d.value / total;
      const angle = frac * Math.PI * 2;
      const a0 = start + (hasMany ? gap / 2 : 0);
      const a1 = start + angle - (hasMany ? gap / 2 : 0);
      if (a1 > a0) {
        ctx.beginPath();
        ctx.strokeStyle = d.color;
        ctx.shadowColor = d.color;
        ctx.shadowBlur = 7;
        ctx.lineWidth = thickness;
        ctx.arc(cx, cy, r, a0, a1);
        ctx.stroke();
      }
      start += angle;
    }
    ctx.shadowBlur = 0;
  }, [data, size, thickness, gap]);

  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <canvas ref={ref} style={{ width: size, height: size }} />
      {children && (
        <div className="absolute inset-0 flex flex-col items-center justify-center">{children}</div>
      )}
    </div>
  );
}

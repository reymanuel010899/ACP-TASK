"use client";

import { useEffect, useRef, useState } from "react";

export type TrendSeries = { label: string; color: string; points: number[] };

function rgba(hex: string, a: number): string {
  const h = hex.replace("#", "");
  const n = h.length === 3 ? h.split("").map((c) => c + c).join("") : h;
  const r = parseInt(n.slice(0, 2), 16);
  const g = parseInt(n.slice(2, 4), 16);
  const b = parseInt(n.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${a})`;
}

type Pt = { x: number; y: number };

// Catmull-Rom → cubic bezier for a smooth line through the points.
function traceSmooth(ctx: CanvasRenderingContext2D, p: Pt[]) {
  if (p.length === 0) return;
  ctx.moveTo(p[0].x, p[0].y);
  for (let i = 0; i < p.length - 1; i++) {
    const p0 = p[i - 1] || p[i];
    const p1 = p[i];
    const p2 = p[i + 1];
    const p3 = p[i + 2] || p2;
    ctx.bezierCurveTo(
      p1.x + (p2.x - p0.x) / 6,
      p1.y + (p2.y - p0.y) / 6,
      p2.x - (p3.x - p1.x) / 6,
      p2.y - (p3.y - p1.y) / 6,
      p2.x,
      p2.y,
    );
  }
}

/**
 * Smooth multi-series area/line chart on canvas (HiDPI-aware, width-responsive
 * via ResizeObserver). Each series gets a gradient area fill fading to
 * transparent, a glowing rounded line, and an end-point marker. Grid lines use
 * a theme-neutral low-alpha slate so it reads well in light and dark; series
 * colors are passed in and constant across themes.
 */
export default function TrendAreaChart({
  series,
  height = 190,
  max = 100,
  showArea = true,
}: {
  series: TrendSeries[];
  height?: number;
  max?: number;
  showArea?: boolean;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [w, setW] = useState(0);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const cr = entries[0]?.contentRect;
      if (cr) setW(Math.round(cr.width));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || w === 0) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    canvas.width = w * dpr;
    canvas.height = height * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, height);

    const padT = 12;
    const padB = 12;
    const padX = 4;
    const plotW = w - padX * 2;
    const plotH = height - padT - padB;

    // Grid
    ctx.strokeStyle = "rgba(148,163,184,0.13)";
    ctx.lineWidth = 1;
    const rows = 4;
    for (let i = 0; i <= rows; i++) {
      const y = Math.round(padT + (plotH / rows) * i) + 0.5;
      ctx.beginPath();
      ctx.moveTo(padX, y);
      ctx.lineTo(padX + plotW, y);
      ctx.stroke();
    }

    const xAt = (i: number, n: number) => padX + (n <= 1 ? plotW / 2 : (plotW * i) / (n - 1));
    const yAt = (v: number) => padT + plotH - (Math.max(0, Math.min(max, v)) / max) * plotH;

    for (const s of series) {
      const n = s.points.length;
      const coords: Pt[] = s.points.map((v, i) => ({ x: xAt(i, n), y: yAt(v) }));
      if (coords.length === 0) continue;

      // Area fill (skipped for multi-line charts where fills would overlap)
      if (showArea) {
        const grad = ctx.createLinearGradient(0, padT, 0, padT + plotH);
        grad.addColorStop(0, rgba(s.color, 0.3));
        grad.addColorStop(1, rgba(s.color, 0));
        ctx.beginPath();
        traceSmooth(ctx, coords);
        ctx.lineTo(coords[coords.length - 1].x, padT + plotH);
        ctx.lineTo(coords[0].x, padT + plotH);
        ctx.closePath();
        ctx.fillStyle = grad;
        ctx.fill();
      }

      // Line
      ctx.beginPath();
      traceSmooth(ctx, coords);
      ctx.strokeStyle = s.color;
      ctx.lineWidth = 2.5;
      ctx.lineJoin = "round";
      ctx.lineCap = "round";
      ctx.shadowColor = rgba(s.color, 0.5);
      ctx.shadowBlur = 6;
      ctx.stroke();
      ctx.shadowBlur = 0;

      // End marker
      const last = coords[coords.length - 1];
      ctx.beginPath();
      ctx.fillStyle = s.color;
      ctx.arc(last.x, last.y, 3.2, 0, Math.PI * 2);
      ctx.fill();
      ctx.beginPath();
      ctx.fillStyle = "rgba(255,255,255,0.92)";
      ctx.arc(last.x, last.y, 1.4, 0, Math.PI * 2);
      ctx.fill();
    }
  }, [series, w, height, max, showArea]);

  return (
    <div ref={wrapRef} className="w-full" style={{ height }}>
      <canvas ref={canvasRef} style={{ width: "100%", height }} />
    </div>
  );
}

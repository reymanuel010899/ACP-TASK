"use client";

import { useEffect, useRef } from "react";

/**
 * Canvas rendering of the Ecosystem Network graph:
 * six labeled entity chips connected by curved lines to a central cluster of
 * agent nodes, with soft glows and slowly drifting particles.
 *
 * Theme-aware (reads --ag-* CSS variables, watches data-theme), DPR-crisp,
 * resize-aware, pauses when the tab is hidden, static under reduced motion.
 */

type Entity = {
  title: string;
  sub: string;
  accent: string;
  icon: IconName;
  side: "left" | "right";
  fy: number; // fraction of height (chip center)
  bend: number; // curve bend direction/strength
};

type IconName = "monitor" | "database" | "hash" | "bag" | "phone" | "shield";

const ENTITIES: Entity[] = [
  { title: "Client App", sub: "12 active tasks", accent: "#06B6D4", icon: "monitor", side: "left", fy: 0.16, bend: -14 },
  { title: "Slack Workspace", sub: "8 active tasks", accent: "#22C55E", icon: "hash", side: "left", fy: 0.5, bend: 10 },
  { title: "Mobile App", sub: "5 active tasks", accent: "#9CA3AF", icon: "phone", side: "left", fy: 0.84, bend: 16 },
  { title: "Agent Registry", sub: "128 agents online", accent: "#8B5CF6", icon: "database", side: "right", fy: 0.16, bend: 14 },
  { title: "Marketplace", sub: "342 services", accent: "#F59E0B", icon: "bag", side: "right", fy: 0.55, bend: -10 },
  { title: "Audit Service", sub: "All systems secure", accent: "#9CA3AF", icon: "shield", side: "right", fy: 0.86, bend: -16 },
];

// Central agent nodes: offsets from cluster center + base radius (design-derived)
const CLUSTER = [
  { dx: -44, dy: -16, r: 18, color: "#3B82F6" },
  { dx: 4, dy: -3, r: 16, color: "#F59E0B" },
  { dx: -28, dy: 25, r: 14, color: "#22C55E" },
  { dx: 23, dy: -29, r: 15, color: "#EF4444" },
  { dx: 45, dy: 23, r: 17, color: "#6D3CE0" },
];

// Ambient particle dots (fractions of canvas size)
const AMBIENT = [
  { fx: 0.23, fy: 0.3, r: 3, color: "#06B6D4" },
  { fx: 0.26, fy: 0.43, r: 2, color: "#22C55E" },
  { fx: 0.22, fy: 0.7, r: 2.5, color: "#9CA3AF" },
  { fx: 0.68, fy: 0.2, r: 2.5, color: "#8B5CF6" },
  { fx: 0.71, fy: 0.59, r: 2, color: "#F59E0B" },
  { fx: 0.67, fy: 0.8, r: 2.5, color: "#9CA3AF" },
];

function drawIcon(ctx: CanvasRenderingContext2D, icon: IconName, cx: number, cy: number, s: number) {
  ctx.save();
  ctx.translate(cx, cy);
  ctx.lineWidth = 1.5;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  ctx.beginPath();
  switch (icon) {
    case "monitor": {
      const w = s, h = s * 0.62;
      roundRectPath(ctx, -w / 2, -h / 2 - s * 0.12, w, h, 2);
      ctx.moveTo(0, h / 2 - s * 0.12);
      ctx.lineTo(0, h / 2 + s * 0.12);
      ctx.moveTo(-s * 0.22, h / 2 + s * 0.12);
      ctx.lineTo(s * 0.22, h / 2 + s * 0.12);
      break;
    }
    case "database": {
      const rx = s * 0.42, ry = s * 0.16, top = -s * 0.34, bot = s * 0.34;
      ctx.ellipse(0, top, rx, ry, 0, 0, Math.PI * 2);
      ctx.moveTo(-rx, top);
      ctx.lineTo(-rx, bot);
      ctx.ellipse(0, bot, rx, ry, 0, Math.PI, 0, true);
      ctx.moveTo(rx, bot);
      ctx.lineTo(rx, top);
      ctx.moveTo(-rx, 0);
      ctx.ellipse(0, 0, rx, ry, 0, Math.PI, 0, true);
      break;
    }
    case "hash": {
      const k = s * 0.5, q = s * 0.16;
      ctx.moveTo(-q, -k); ctx.lineTo(-q - s * 0.06, k);
      ctx.moveTo(q + s * 0.06, -k); ctx.lineTo(q, k);
      ctx.moveTo(-k, -q); ctx.lineTo(k, -q);
      ctx.moveTo(-k, q); ctx.lineTo(k, q);
      break;
    }
    case "bag": {
      const w = s * 0.76, h = s * 0.72, top = -s * 0.14;
      roundRectPath(ctx, -w / 2, top, w, h, 2.5);
      ctx.moveTo(-s * 0.2, top);
      ctx.quadraticCurveTo(-s * 0.2, -s * 0.5, 0, -s * 0.5);
      ctx.quadraticCurveTo(s * 0.2, -s * 0.5, s * 0.2, top);
      break;
    }
    case "phone": {
      const w = s * 0.56, h = s;
      roundRectPath(ctx, -w / 2, -h / 2, w, h, 2.5);
      ctx.moveTo(-s * 0.08, h / 2 - s * 0.18);
      ctx.lineTo(s * 0.08, h / 2 - s * 0.18);
      break;
    }
    case "shield": {
      const k = s * 0.5;
      ctx.moveTo(0, -k);
      ctx.lineTo(k * 0.84, -k * 0.55);
      ctx.quadraticCurveTo(k * 0.84, k * 0.35, 0, k);
      ctx.quadraticCurveTo(-k * 0.84, k * 0.35, -k * 0.84, -k * 0.55);
      ctx.closePath();
      break;
    }
  }
  ctx.stroke();
  ctx.restore();
}

function roundRectPath(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + r);
  ctx.lineTo(x + w, y + h - r);
  ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  ctx.lineTo(x + r, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
}

function quadPoint(x0: number, y0: number, cx: number, cy: number, x1: number, y1: number, t: number) {
  const u = 1 - t;
  return {
    x: u * u * x0 + 2 * u * t * cx + t * t * x1,
    y: u * u * y0 + 2 * u * t * cy + t * t * y1,
  };
}

export default function EcosystemNetworkCanvas() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let width = 0;
    let height = 0;
    let raf = 0;
    let running = false;
    const start = performance.now();

    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

    let palette = readPalette();
    function readPalette() {
      const cs = getComputedStyle(document.documentElement);
      const v = (name: string, fallback: string) =>
        cs.getPropertyValue(name).trim() || fallback;
      return {
        bgInner: v("--ag-net-bg-inner", "#1a1640"),
        bgOuter: v("--ag-net-bg-outer", "#0d0b1e"),
        line: v("--ag-net-line", "rgba(109,60,224,0.2)"),
        glow: v("--ag-net-glow", "rgba(109,60,224,0.28)"),
        chipBg: v("--ag-net-chip", "rgba(19,17,42,0.72)"),
        chipBorder: v("--ag-net-chip-border", "rgba(139,92,246,0.2)"),
        text: v("--ag-text", "#ffffff"),
        muted: v("--ag-text-muted", "#6b7280"),
      };
    }

    const fontFamily =
      getComputedStyle(canvas).fontFamily || "Inter, system-ui, sans-serif";

    function resize() {
      if (!canvas) return;
      const dpr = window.devicePixelRatio || 1;
      width = canvas.clientWidth;
      height = canvas.clientHeight;
      canvas.width = Math.max(1, Math.round(width * dpr));
      canvas.height = Math.max(1, Math.round(height * dpr));
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    type Chip = Entity & { x: number; y: number; w: number; h: number; anchorX: number; anchorY: number };

    function layout(): { chips: Chip[]; cx: number; cy: number; scale: number } {
      const pad = Math.max(24, width * 0.03);
      const chipH = 40;
      const chips: Chip[] = ENTITIES.map((e) => {
        ctx!.font = `500 12px ${fontFamily}`;
        const titleW = ctx!.measureText(e.title).width;
        ctx!.font = `400 10px ${fontFamily}`;
        const subW = ctx!.measureText(e.sub).width;
        const w = 8 + 26 + 8 + Math.max(titleW, subW) + 12;
        const y = e.fy * height - chipH / 2;
        const x = e.side === "left" ? pad : width - pad - w;
        return {
          ...e,
          x,
          y,
          w,
          h: chipH,
          anchorX: e.side === "left" ? x + w + 4 : x - 4,
          anchorY: y + chipH / 2,
        };
      });

      // keep the central cluster clear of the chips
      const leftMax = Math.max(...chips.filter((c) => c.side === "left").map((c) => c.x + c.w));
      const rightMin = Math.min(...chips.filter((c) => c.side === "right").map((c) => c.x));
      const clusterHalf = 82;
      const lo = leftMax + 16 + clusterHalf;
      const hi = rightMin - 16 - clusterHalf;
      let cx = width / 2;
      let scale = 1;
      if (lo <= hi) {
        cx = Math.min(Math.max(cx, lo), hi);
      } else {
        cx = (leftMax + rightMin) / 2;
        scale = Math.max(0.55, (rightMin - leftMax - 32) / (2 * clusterHalf));
      }
      return { chips, cx, cy: height * 0.47, scale };
    }

    function draw(now: number) {
      if (!ctx || width === 0 || height === 0) return;
      const t = reduceMotion.matches ? 0 : (now - start) / 1000;
      const p = palette;

      // background
      ctx.clearRect(0, 0, width, height);
      const bg = ctx.createRadialGradient(
        width / 2, height / 2, 0,
        width / 2, height / 2, Math.max(width, height) * 0.55
      );
      bg.addColorStop(0, p.bgInner);
      bg.addColorStop(1, p.bgOuter);
      ctx.fillStyle = bg;
      ctx.fillRect(0, 0, width, height);

      const { chips, cx, cy, scale } = layout();

      // center glow (gently pulsing)
      const glowR = (78 + Math.sin(t * 0.8) * 6) * scale + 42;
      const glow = ctx.createRadialGradient(cx, cy, 0, cx, cy, glowR);
      glow.addColorStop(0, p.glow);
      glow.addColorStop(1, "rgba(109,60,224,0)");
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(cx, cy, glowR, 0, Math.PI * 2);
      ctx.fill();

      // connection curves + drifting particles
      chips.forEach((chip, i) => {
        const tx = cx + (chip.side === "left" ? -52 : 52) * scale;
        const ty = cy + (chip.anchorY - cy) * 0.25;
        const mx = (chip.anchorX + tx) / 2;
        const my = (chip.anchorY + ty) / 2 + chip.bend;

        ctx.strokeStyle = p.line;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(chip.anchorX, chip.anchorY);
        ctx.quadraticCurveTo(mx, my, tx, ty);
        ctx.stroke();

        const pt = (t / 14 + i * 0.17) % 1;
        const pos = quadPoint(chip.anchorX, chip.anchorY, mx, my, tx, ty, chip.side === "left" ? pt : 1 - pt);
        ctx.globalAlpha = 0.45 + 0.25 * Math.sin(t * 2 + i);
        ctx.fillStyle = chip.accent;
        ctx.beginPath();
        ctx.arc(pos.x, pos.y, 2, 0, Math.PI * 2);
        ctx.fill();
        ctx.globalAlpha = 1;
      });

      // ambient dots
      AMBIENT.forEach((d, i) => {
        ctx.globalAlpha = 0.35 + 0.25 * Math.sin(t * 1.2 + i * 1.7);
        ctx.fillStyle = d.color;
        ctx.beginPath();
        ctx.arc(d.fx * width, d.fy * height, d.r * 0.8, 0, Math.PI * 2);
        ctx.fill();
        ctx.globalAlpha = 1;
      });

      // central agent nodes with soft pulsing glows
      CLUSTER.forEach((n, i) => {
        const nx = cx + n.dx * scale;
        const ny = cy + n.dy * scale;
        const pulse = 1 + 0.05 * Math.sin(t * 1.4 + i * 1.3);
        const r = n.r * scale * pulse;
        const halo = ctx.createRadialGradient(nx, ny, r * 0.4, nx, ny, r * 2.2);
        halo.addColorStop(0, n.color + "55");
        halo.addColorStop(1, n.color + "00");
        ctx.fillStyle = halo;
        ctx.beginPath();
        ctx.arc(nx, ny, r * 2.2, 0, Math.PI * 2);
        ctx.fill();
        ctx.globalAlpha = 0.85;
        ctx.fillStyle = n.color;
        ctx.beginPath();
        ctx.arc(nx, ny, r, 0, Math.PI * 2);
        ctx.fill();
        ctx.globalAlpha = 1;
      });

      // entity chips
      chips.forEach((chip) => {
        ctx.fillStyle = p.chipBg;
        ctx.strokeStyle = p.chipBorder;
        ctx.lineWidth = 1;
        ctx.beginPath();
        roundRectPath(ctx, chip.x, chip.y, chip.w, chip.h, 8);
        ctx.fill();
        ctx.stroke();

        // icon tile
        const tileX = chip.x + 8;
        const tileY = chip.y + (chip.h - 26) / 2;
        ctx.fillStyle = chip.accent + "20";
        ctx.beginPath();
        roundRectPath(ctx, tileX, tileY, 26, 26, 7);
        ctx.fill();
        ctx.strokeStyle = chip.accent;
        drawIcon(ctx, chip.icon, tileX + 13, tileY + 13, 14);

        // labels
        const textX = tileX + 26 + 8;
        ctx.textBaseline = "alphabetic";
        ctx.fillStyle = p.text;
        ctx.font = `500 12px ${fontFamily}`;
        ctx.fillText(chip.title, textX, chip.y + 17);
        ctx.fillStyle = p.muted;
        ctx.font = `400 10px ${fontFamily}`;
        ctx.fillText(chip.sub, textX, chip.y + 30);
      });
    }

    function frame(now: number) {
      draw(now);
      if (running && !reduceMotion.matches) raf = requestAnimationFrame(frame);
    }

    function play() {
      if (running) return;
      running = true;
      if (reduceMotion.matches) {
        draw(performance.now());
        running = false;
      } else {
        raf = requestAnimationFrame(frame);
      }
    }

    function pause() {
      running = false;
      cancelAnimationFrame(raf);
    }

    const onVisibility = () => {
      if (document.hidden) pause();
      else play();
    };
    const onMotionChange = () => {
      pause();
      play();
    };

    const ro = new ResizeObserver(() => {
      resize();
      draw(performance.now());
    });
    ro.observe(canvas);

    const mo = new MutationObserver(() => {
      palette = readPalette();
      draw(performance.now());
    });
    mo.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });

    document.addEventListener("visibilitychange", onVisibility);
    reduceMotion.addEventListener("change", onMotionChange);

    resize();
    play();

    return () => {
      pause();
      ro.disconnect();
      mo.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      reduceMotion.removeEventListener("change", onMotionChange);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className="box-border block w-full h-[220px] shrink-0"
      aria-label="Ecosystem network graph: six connected services around a cluster of agents"
      role="img"
    />
  );
}

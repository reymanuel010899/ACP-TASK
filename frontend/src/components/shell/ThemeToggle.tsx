"use client";

import { useSyncExternalStore } from "react";

const STORAGE_KEY = "agentio-theme";

type Theme = "dark" | "light";

let listeners: Array<() => void> = [];

function subscribe(callback: () => void) {
  listeners.push(callback);
  return () => {
    listeners = listeners.filter((l) => l !== callback);
  };
}

function getSnapshot(): Theme {
  return document.documentElement.getAttribute("data-theme") === "light"
    ? "light"
    : "dark";
}

// Server render (and first client render during hydration) always shows the
// design's native dark theme; useSyncExternalStore re-syncs right after mount.
function getServerSnapshot(): Theme {
  return "dark";
}

/** Sun/moon theme switch rendered as a text glyph, matching the top bar design. */
export default function ThemeToggle({ className }: { className?: string }) {
  const theme = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  const toggle = () => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // localStorage unavailable (private mode etc.) — theme still applies
    }
    for (const l of listeners) l();
  };

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={
        theme === "dark" ? "Switch to light theme" : "Switch to dark theme"
      }
      className={`${className ?? ""} shrink-0 p-0 border-0 bg-transparent cursor-pointer`}
    >
      {theme === "dark" ? "☼" : "☾"}
    </button>
  );
}

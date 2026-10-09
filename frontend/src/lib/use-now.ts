import { useSyncExternalStore } from "react";

/**
 * A clock for relative times ("3m ago"). Shared by every component, one timer for all of them.
 *
 * Returns null until the browser has hydrated: reading the current time while Next prerenders a page would bake the
 * build time into the static HTML, so the server (and the first client render) say "unknown" and the real time
 * arrives right after.
 */
let current: number | null = null;
const listeners = new Set<() => void>();
let timer: ReturnType<typeof setInterval> | undefined;

function subscribe(callback: () => void) {
  if (listeners.size === 0) {
    timer = setInterval(() => {
      current = Date.now();
      listeners.forEach((l) => l());
    }, 15_000);
  }
  current = Date.now();
  listeners.add(callback);
  return () => {
    listeners.delete(callback);
    if (listeners.size === 0) clearInterval(timer);
  };
}

export const useNow = (): number | null =>
  useSyncExternalStore(subscribe, () => current, () => null);

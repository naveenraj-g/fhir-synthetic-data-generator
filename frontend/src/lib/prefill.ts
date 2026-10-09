import type { BuilderState } from "./builder-state";

/**
 * Hand-off from other pages ("Edit & re-run", "Use in generator") to the builder. In-memory on purpose: the hand-off
 * always happens during client-side navigation, so a hard reload of the builder starts blank, matching what the
 * server rendered (no hydration mismatch).
 *
 * The builder page may already exist: Next keeps pages you have visited alive in the background, so returning to "/"
 * does not mount a new builder. Every hand-off therefore bumps `version`, and the page keys the builder on it
 * (`useSyncExternalStore(subscribePrefill, prefillVersion)`) so a new hand-off always starts a fresh form.
 *
 * `peekPrefill` does not clear, because React may run a state initializer twice in development; the builder clears it
 * in an effect once it has mounted.
 */
let pending: BuilderState | null = null;
let version = 0;
const listeners = new Set<() => void>();

export const setPrefill = (state: BuilderState) => {
  pending = state;
  version += 1;
  listeners.forEach((l) => l());
};
export const peekPrefill = () => pending;
export const clearPrefill = () => {
  pending = null;
};

export const subscribePrefill = (listener: () => void) => {
  listeners.add(listener);
  return () => void listeners.delete(listener);
};
export const prefillVersion = () => version;

export function formatBytes(n: number | null | undefined): string {
  if (n == null) return "-";
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB"];
  let v = n / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v >= 100 ? v.toFixed(0) : v.toFixed(1)} ${units[i]}`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "-";
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`;
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  const m = Math.floor(seconds / 60);
  return `${m}m ${Math.round(seconds - m * 60)}s`;
}

export const formatNumber = (n: number | null | undefined) => (n == null ? "-" : n.toLocaleString("en-US"));

/**
 * The API stores UTC timestamps; SQLite hands them back without a zone suffix, so treat a bare ISO string
 * as UTC rather than letting the browser read it as local time.
 */
export function parseApiDate(s: string | null | undefined): Date | null {
  if (!s) return null;
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : `${s}Z`);
}

export function timeAgo(date: Date | null, now: number | null): string {
  if (!date) return "-";
  if (now === null) return "";  // clock not available yet (server render): see lib/use-now.ts
  const sec = Math.round((now - date.getTime()) / 1000);
  if (sec < 5) return "just now";
  if (sec < 60) return `${sec}s ago`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 48) return `${hr}h ago`;
  return `${Math.round(hr / 24)}d ago`;
}

/** "in 71h" / "in 2d" / "expired". */
export function timeUntil(date: Date | null, now: number | null): string {
  if (!date) return "-";
  if (now === null) return "";
  const sec = Math.round((date.getTime() - now) / 1000);
  if (sec <= 0) return "expired";
  const hr = Math.round(sec / 3600);
  if (hr < 1) return `in ${Math.max(1, Math.round(sec / 60))}m`;
  if (hr < 48) return `in ${hr}h`;
  return `in ${Math.round(hr / 24)}d`;
}

export const shortId = (id: string) => id.slice(0, 8);

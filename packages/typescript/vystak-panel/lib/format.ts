// SQLite timestamps from the panel store may arrive timezone-naive; they are UTC.
export function relativeTime(iso: string, now: Date = new Date()): string {
  const hasTz = /Z$|[+-]\d{2}:\d{2}$/.test(iso);
  const then = new Date(hasTz ? iso : `${iso}Z`);
  const s = Math.max(0, Math.floor((now.getTime() - then.getTime()) / 1000));
  if (s < 60) return 'just now';
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 7) return `${d}d ago`;
  return then.toLocaleDateString();
}

export function safeParseJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

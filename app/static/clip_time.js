// Reading and writing clip times. parseTime is the browser twin of parse_time_ms in app/services/parsing.py
// (tests compare the two): "75", "75.5", "1:15", "1:15.5" and "1:15,5" (a comma decimal, as some phone keyboards
// type) are all read; anything else is null.

export function parseTime(text) {
  const trimmed = String(text ?? "").trim().replace(/,/g, ".");
  if (!trimmed) return null;
  const parts = trimmed.split(":");
  if (parts.length > 3) return null;
  let total = 0;
  for (const part of parts) {
    // Number() would accept things Python's float() doesn't ("0x10", "1e3" is fine in both, "" is 0), so check the shape first.
    if (!/^\s*(\d+\.?\d*|\.\d+)(e[+-]?\d+)?\s*$/i.test(part)) return null;
    const value = Number(part);
    if (!Number.isFinite(value)) return null;
    total = total * 60 + value;
  }
  return total;
}

/** Seconds as m:ss.t (tenths), the same shape the server writes. */
export function formatTime(seconds) {
  const tenths = Math.round(seconds * 10);
  const minutes = Math.floor(tenths / 600);
  const rest = ((tenths % 600) / 10).toFixed(1).padStart(4, "0");
  return `${minutes}:${rest}`;
}

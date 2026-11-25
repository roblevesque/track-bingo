// Small pure helpers for the host console's audio playback (no DOM, easy to reason about).

/** Number from a text box, kept inside [min, max]; `fallback` if it isn't a number. */
export function clampNumber(value, min, max, fallback) {
  const number = Number(value);
  if (value === "" || !Number.isFinite(number)) return fallback;
  return Math.min(max, Math.max(min, number));
}

/**
 * Volume (0..1) for a point in a clip's play window: ramps up over `fade` seconds
 * from `start` and down over `fade` seconds to `end`. `end` may be unknown (NaN or
 * Infinity), in which case there is no fade-out. If the window is shorter than two
 * fades, each fade shrinks to half the window so they never overlap into silence.
 */
export function fadeVolume(time, start, end, fade) {
  if (!(fade > 0)) return 1;
  const known = Number.isFinite(end);
  const length = known ? Math.max(0, end - start) : Infinity;
  const f = known ? Math.min(fade, length / 2) : fade;
  if (!(f > 0)) return 1;
  const rising = (time - start) / f;
  const falling = known ? (end - time) / f : 1;
  return Math.min(1, Math.max(0, Math.min(rising, falling)));
}

/**
 * Where playback is inside a clip's window, in seconds: { elapsed, length }. `length` is NaN while the file's
 * duration isn't known yet and the clip has no saved end. `elapsed` is kept inside 0..length.
 */
export function clipProgress(currentTime, startMs, endMs, duration) {
  const start = (startMs || 0) / 1000;
  const end = endMs ? endMs / 1000 : duration;
  const length = Number.isFinite(end) ? Math.max(0, end - start) : NaN;
  let elapsed = Math.max(0, (currentTime || 0) - start);
  if (Number.isFinite(length)) elapsed = Math.min(elapsed, length);
  return { elapsed, length };
}

/** 75.4 -> "1:15". Not a number -> "--:--". */
export function formatClock(seconds) {
  if (!Number.isFinite(seconds)) return "--:--";
  const whole = Math.max(0, Math.floor(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

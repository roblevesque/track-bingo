// Measures how loud a clip sounds, so the console can play every song at about the same level.
//
// This is the broadcast standard for loudness (ITU-R BS.1770 / EBU R128, the "LUFS" that streaming services
// use): filter the audio to weight it the way ears do ("K-weighting"), take the power in 400 ms blocks, ignore
// near-silence and the quiet passages well below the rest, and average. Plain functions on numbers, so it runs in
// the browser (after the browser itself has decoded the file) and can be tested in Node.

const BLOCK_SECONDS = 0.4;
const STEP_SECONDS = 0.1; // blocks overlap by 75%
const ABSOLUTE_GATE = -70; // LUFS
const RELATIVE_GATE = -10; // LU below the ungated level
export const SILENT = -70; // what a silent clip measures as

/**
 * Biquad coefficients [b0, b1, b2, a1, a2] (a0 normalised to 1) for the two K-weighting stages at `rate`.
 * At 48 kHz these are exactly the coefficients printed in BS.1770; other rates use the same analogue design.
 */
export function kWeightingFilters(rate) {
  // Stage 1: a high shelf, +4 dB above about 1.7 kHz (the head's effect on sound).
  let K = Math.tan((Math.PI * 1681.974450955533) / rate);
  let Q = 0.7071752369554196;
  const Vh = 10 ** (3.999843853973347 / 20);
  const Vb = Vh ** 0.4996667741545416;
  let a0 = 1 + K / Q + K * K;
  const shelf = [(Vh + (Vb * K) / Q + K * K) / a0, (2 * (K * K - Vh)) / a0, (Vh - (Vb * K) / Q + K * K) / a0,
    (2 * (K * K - 1)) / a0, (1 - K / Q + K * K) / a0];
  // Stage 2: a high pass at about 38 Hz (rumble barely counts).
  K = Math.tan((Math.PI * 38.13547087602444) / rate);
  Q = 0.5003270373238773;
  a0 = 1 + K / Q + K * K;
  const highPass = [1, -2, 1, (2 * (K * K - 1)) / a0, (1 - K / Q + K * K) / a0];
  return [shelf, highPass];
}

function filter(samples, [b0, b1, b2, a1, a2]) {
  const out = new Float64Array(samples.length);
  let x1 = 0, x2 = 0, y1 = 0, y2 = 0;
  for (let i = 0; i < samples.length; i += 1) {
    const x = samples[i];
    const y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2;
    out[i] = y;
    x2 = x1; x1 = x; y2 = y1; y1 = y;
  }
  return out;
}

/**
 * Integrated loudness in LUFS of `channels` (arrays of samples, -1..1) at `rate`, between `startSeconds` and
 * `endSeconds` (the clip window; null end = to the end). Channels are weighted equally (fine for mono and stereo).
 * A silent or very short clip gives SILENT.
 */
export function integratedLoudness(channels, rate, startSeconds = 0, endSeconds = null) {
  const from = Math.max(0, Math.floor(startSeconds * rate));
  const to = Math.min(channels[0].length, endSeconds == null ? Infinity : Math.floor(endSeconds * rate));
  const block = Math.round(BLOCK_SECONDS * rate);
  const step = Math.round(STEP_SECONDS * rate);
  if (to - from < block) return SILENT;
  const [shelf, highPass] = kWeightingFilters(rate);
  // Running sums of squared, weighted samples, so each block's power is a subtraction.
  const count = Math.floor((to - from - block) / step) + 1;
  const power = new Float64Array(count);
  for (const channel of channels) {
    const weighted = filter(filter(channel.subarray(from, to), shelf), highPass);
    const cumulative = new Float64Array(weighted.length + 1);
    for (let i = 0; i < weighted.length; i += 1) cumulative[i + 1] = cumulative[i] + weighted[i] * weighted[i];
    for (let j = 0; j < count; j += 1) power[j] += (cumulative[j * step + block] - cumulative[j * step]) / block;
  }
  const lufs = (z) => -0.691 + 10 * Math.log10(z);
  const mean = (values) => values.reduce((a, b) => a + b, 0) / values.length;
  const audible = [...power].filter((z) => z > 0 && lufs(z) > ABSOLUTE_GATE);
  if (!audible.length) return SILENT;
  const threshold = lufs(mean(audible)) + RELATIVE_GATE;
  const counted = audible.filter((z) => lufs(z) > threshold);
  return Math.max(SILENT, lufs(mean(counted)));
}

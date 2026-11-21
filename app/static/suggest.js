// Suggests clip sections by listening to the song: sections that are loud and that sound like other parts
// of the same song (a chorus repeats) score highest. Everything here is plain functions on numbers, so it
// runs in the browser (after the browser itself has decoded the MP3 or Ogg) and can be tested in Node.

const TARGET_RATE = 11025; // plenty for pitch and rough timbre
const FRAME = 4096; // samples per analysis window (about 0.37 s)
const HOP_SECONDS = 0.5;
const SMOOTH_FRAMES = 4; // vectors are averaged over about two seconds, so small details don't matter
const GUARD_SECONDS = 10; // a frame only "repeats" if a similar one is at least this far away
const BANDS = [100, 200, 400, 800, 1600, 3200, 6000];

// ---- signal helpers

/** Average channels to mono and shrink to about TARGET_RATE by block averaging. */
export function toMono(channels, sampleRate) {
  const factor = Math.max(1, Math.round(sampleRate / TARGET_RATE));
  const length = Math.floor(channels[0].length / factor);
  const out = new Float32Array(length);
  for (let i = 0; i < length; i += 1) {
    let sum = 0;
    for (let c = 0; c < channels.length; c += 1) {
      const data = channels[c];
      for (let k = 0; k < factor; k += 1) sum += data[i * factor + k];
    }
    out[i] = sum / (factor * channels.length);
  }
  return { samples: out, rate: sampleRate / factor };
}

/** In-place radix-2 FFT. */
export function fft(re, im) {
  const n = re.length;
  for (let i = 1, j = 0; i < n; i += 1) {
    let bit = n >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) { [re[i], re[j]] = [re[j], re[i]]; [im[i], im[j]] = [im[j], im[i]]; }
  }
  for (let size = 2; size <= n; size <<= 1) {
    const angle = (-2 * Math.PI) / size;
    const wr = Math.cos(angle), wi = Math.sin(angle);
    for (let start = 0; start < n; start += size) {
      let cr = 1, ci = 0;
      for (let k = 0; k < size / 2; k += 1) {
        const a = start + k, b = a + size / 2;
        const tr = re[b] * cr - im[b] * ci, ti = re[b] * ci + im[b] * cr;
        re[b] = re[a] - tr; im[b] = im[a] - ti;
        re[a] += tr; im[a] += ti;
        const next = cr * wr - ci * wi;
        ci = cr * wi + ci * wr;
        cr = next;
      }
    }
  }
}

function normalise(vector) {
  let sum = 0;
  for (const v of vector) sum += v * v;
  const norm = Math.sqrt(sum) || 1;
  return vector.map((v) => v / norm);
}

/**
 * One feature vector per half second: the strength of each of the 12 notes (so the same chords match) and
 * of a few frequency bands (so the same instruments match), plus the loudness of that moment.
 */
export function extractFeatures(samples, rate) {
  const hop = Math.round(HOP_SECONDS * rate);
  const window = new Float32Array(FRAME).map((_, i) => 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / (FRAME - 1)));
  const binHz = rate / FRAME;
  const chromaOf = new Int8Array(FRAME / 2).fill(-1);
  const bandOf = new Int8Array(FRAME / 2).fill(-1);
  for (let bin = 1; bin < FRAME / 2; bin += 1) {
    const hz = bin * binHz;
    if (hz >= 65 && hz <= 2100) chromaOf[bin] = ((Math.round(12 * Math.log2(hz / 440)) + 69) % 12 + 12) % 12;
    for (let b = 0; b < BANDS.length - 1; b += 1) if (hz >= BANDS[b] && hz < BANDS[b + 1]) bandOf[bin] = b;
  }
  const vectors = [], loudness = [];
  const re = new Float32Array(FRAME), im = new Float32Array(FRAME);
  for (let start = 0; start + FRAME <= samples.length; start += hop) {
    let energy = 0;
    for (let i = 0; i < FRAME; i += 1) {
      const v = samples[start + i];
      energy += v * v;
      re[i] = v * window[i];
      im[i] = 0;
    }
    fft(re, im);
    const chroma = new Array(12).fill(0), bands = new Array(BANDS.length - 1).fill(0);
    for (let bin = 1; bin < FRAME / 2; bin += 1) {
      const magnitude = Math.hypot(re[bin], im[bin]);
      if (chromaOf[bin] >= 0) chroma[chromaOf[bin]] += magnitude;
      if (bandOf[bin] >= 0) bands[bandOf[bin]] += magnitude;
    }
    vectors.push([...normalise(chroma), ...normalise(bands.map((v) => Math.log1p(v)))]);
    loudness.push(Math.sqrt(energy / FRAME));
  }
  return { hop: HOP_SECONDS, vectors, loudness };
}

// ---- choosing sections

function cosine(a, b) {
  let dot = 0, na = 0, nb = 0;
  for (let i = 0; i < a.length; i += 1) { dot += a[i] * b[i]; na += a[i] * a[i]; nb += b[i] * b[i]; }
  return dot / (Math.sqrt(na * nb) || 1);
}

function smooth(vectors, width) {
  return vectors.map((_, i) => {
    const from = Math.max(0, i - Math.floor(width / 2)), to = Math.min(vectors.length, from + width);
    const out = new Array(vectors[0].length).fill(0);
    for (let k = from; k < to; k += 1) for (let d = 0; d < out.length; d += 1) out[d] += vectors[k][d];
    return out.map((v) => v / (to - from));
  });
}

function scale01(values) {
  let lo = Infinity, hi = -Infinity;
  for (const v of values) { if (v < lo) lo = v; if (v > hi) hi = v; }
  return values.map((v) => (hi > lo ? (v - lo) / (hi - lo) : 0));
}

/**
 * Up to `count` non-overlapping sections of `lengthSeconds`, best first. Each is
 * { start, end, score (0 to 1), repeat (0 to 1), loud (0 to 1) } in seconds.
 */
export function suggestWindows(features, lengthSeconds, count = 3) {
  const { hop, vectors, loudness } = features;
  const span = Math.max(1, Math.round(lengthSeconds / hop));
  if (vectors.length < span + 2) return [];
  const smoothed = smooth(vectors, SMOOTH_FRAMES);
  const guard = Math.round(GUARD_SECONDS / hop);

  // How much each moment sounds like some other, distant part of the song.
  const repeat = smoothed.map((v, i) => {
    const best = [0, 0, 0];
    for (let j = 0; j < smoothed.length; j += 1) {
      if (Math.abs(i - j) < guard) continue;
      const s = cosine(v, smoothed[j]);
      if (s > best[2]) { best[2] = s; best.sort((a, b) => a - b); }
    }
    return (best[0] + best[1] + best[2]) / 3;
  });
  const sorted = [...loudness].sort((a, b) => a - b);
  const reference = sorted[Math.floor(sorted.length * 0.9)] || 1;
  const loud = loudness.map((v) => Math.min(1.5, v / reference));

  const starts = [];
  for (let s = 0; s + span <= vectors.length; s += 1) starts.push(s);
  const mean = (values, s) => { let t = 0; for (let k = s; k < s + span; k += 1) t += values[k]; return t / span; };
  const repeatScores = scale01(starts.map((s) => mean(repeat, s)));
  const loudScores = scale01(starts.map((s) => mean(loud, s)));
  const candidates = starts.map((s, i) => {
    let score = 0.6 * repeatScores[i] + 0.4 * loudScores[i];
    if (s * hop < 8) score *= 0.85; // an intro is rarely the part everyone knows
    return { frame: s, score, repeat: repeatScores[i], loud: loudScores[i] };
  }).sort((a, b) => b.score - a.score);

  const picked = [];
  for (const candidate of candidates) {
    if (picked.length >= count || (picked.length && candidate.score < 0.4)) break; // weak runners-up aren't worth offering
    if (picked.some((p) => Math.abs(p.frame - candidate.frame) < span + 8)) continue; // room for the start nudge below
    picked.push(candidate);
  }
  return picked.map((p) => {
    // Line the start up with the nearest sudden rise in volume (where a section kicks in), within 2 seconds.
    let frame = p.frame, rise = -Infinity;
    for (let f = Math.max(2, p.frame - 4); f <= Math.min(vectors.length - span, p.frame + 4); f += 1) {
      const jump = loudness[f] - loudness[f - 2];
      if (jump > rise) { rise = jump; frame = f; }
    }
    return { start: frame * hop, end: (frame + span) * hop, score: p.score, repeat: p.repeat, loud: p.loud };
  });
}

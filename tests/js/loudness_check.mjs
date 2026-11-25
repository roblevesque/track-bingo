import { integratedLoudness, SILENT } from "../../app/static/loudness.js";
const sine = (rate, seconds, freq, amp) => Float32Array.from({ length: rate * seconds }, (_, i) => amp * Math.sin(2 * Math.PI * freq * i / rate));
const rate = 48000;
const full = sine(rate, 5, 997, 1);
const half = sine(rate, 5, 997, 0.5);
// A quiet first half and a loud second half, to check the clip window is what gets measured.
const mixed = new Float32Array(rate * 10); mixed.set(sine(rate, 5, 997, 0.1)); mixed.set(full, rate * 5);
console.log(JSON.stringify({
  monoFull: integratedLoudness([full], rate),
  stereoFull: integratedLoudness([full, full], rate),
  stereoHalf: integratedLoudness([half, half], rate),
  at44k: integratedLoudness([sine(44100, 5, 997, 1)], 44100),
  quietWindow: integratedLoudness([mixed], rate, 0, 5),
  loudWindow: integratedLoudness([mixed], rate, 5, null),
  silent: integratedLoudness([new Float32Array(rate * 3)], rate),
  tooShort: integratedLoudness([full], rate, 0, 0.2),
  SILENT,
}));

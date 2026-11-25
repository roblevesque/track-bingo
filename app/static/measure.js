// "Measure volumes": the browser fetches each clip, decodes it, measures the loudness of its clip window
// (loudness.js) and saves the number. Used on the game page (every song in the game that needs it) and on a song's
// edit page (that one song).
//
// Markup: <div data-measure data-csrf="..."> holding <script type="application/json" data-measure-songs> with
// [{id, title, audio_url, start_ms, end_ms}], a [data-measure-start] button and a [data-measure-status] line.
// A [data-measure-summary] next to the box (one song only) is replaced by the server's new description.

import { integratedLoudness } from "./loudness.js";

async function measureOne(context, song, csrf) {
  const response = await fetch(song.audio_url);
  if (!response.ok) throw new Error("couldn't load the file");
  const decoded = await context.decodeAudioData(await response.arrayBuffer());
  const channels = Array.from({ length: decoded.numberOfChannels }, (_, c) => decoded.getChannelData(c));
  const lufs = integratedLoudness(channels, decoded.sampleRate, (song.start_ms || 0) / 1000,
    song.end_ms ? song.end_ms / 1000 : null);
  const body = new FormData();
  body.set("csrf_token", csrf);
  body.set("loudness", lufs.toFixed(2));
  body.set("start_ms", String(song.start_ms || 0));
  body.set("end_ms", song.end_ms == null ? "" : String(song.end_ms));
  const saved = await fetch(`/library/${song.id}/loudness`, { method: "POST", body });
  const data = await saved.json().catch(() => ({}));
  if (!saved.ok) throw new Error(typeof data.detail === "string" ? data.detail : "couldn't save");
  return data;
}

for (const box of document.querySelectorAll("[data-measure]")) {
  const button = box.querySelector("[data-measure-start]");
  const status = box.querySelector("[data-measure-status]");
  const songs = JSON.parse(box.querySelector("[data-measure-songs]").textContent);
  button.addEventListener("click", async () => {
    const Context = window.AudioContext || window.webkitAudioContext;
    if (!Context) { status.textContent = "This browser can't measure audio."; return; }
    button.disabled = true;
    const context = new Context();
    const failed = [];
    let last = null;
    try {
      for (const [i, song] of songs.entries()) {
        status.textContent = songs.length > 1 ? `Measuring ${i + 1} of ${songs.length}: ${song.title}…` : "Measuring…";
        try { last = await measureOne(context, song, box.dataset.csrf); }
        catch (error) { failed.push(`${song.title} (${error.message})`); }
      }
    } finally {
      context.close?.();
    }
    const done = songs.length - failed.length;
    const summary = box.parentElement.querySelector("[data-measure-summary]");
    if (songs.length === 1 && last && summary) { summary.textContent = last.text; status.textContent = "Measured."; }
    else if (songs.length === 1 && last) status.textContent = `Done. ${last.text}`;
    else status.textContent = `Measured ${done} of ${songs.length}.` + (failed.length ? ` Not measured: ${failed.join("; ")}.` : "");
    button.disabled = false;
    if (!failed.length && songs.length > 1) button.hidden = true; // every song is done (one song can be measured again)
  });
}

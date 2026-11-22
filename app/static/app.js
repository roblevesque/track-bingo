// Small progressive enhancements. No build step: this file is served as-is.

// Confirm before destructive form submits: <form data-confirm="Are you sure?">
document.addEventListener("submit", (event) => {
  const message = event.target.dataset?.confirm;
  if (message && !window.confirm(message)) event.preventDefault();
});

// Coming back to the library after an edit: the song just edited (or the song list) is brought to the middle
// of the screen and briefly highlighted, so the next song is right there without scrolling.
(function focusLibraryTarget() {
  const match = /^#(song-\d+|songs)$/.exec(window.location.hash);
  if (!match || !document.querySelector("#songs")) return;
  // If the song isn't on this page any more (an edit moved it under the current sort), show the top of the list.
  const found = document.getElementById(match[1]);
  const target = found || document.getElementById("songs");
  const isSong = Boolean(found) && match[1] !== "songs";
  requestAnimationFrame(() => {
    target.scrollIntoView({ block: isSong ? "center" : "start" });
    if (isSong) target.classList.add("just-edited");
  });
})();

// Tabs: <div data-tabs> holding role=tab buttons (data-tab="panel-id") and role=tabpanel panels. Without
// scripting every panel simply shows.
document.querySelectorAll("[data-tabs]").forEach((box) => {
  const tabs = [...box.querySelectorAll("[role=tab]")];
  const select = (chosen, focus) => {
    tabs.forEach((tab) => {
      const on = tab === chosen;
      tab.setAttribute("aria-selected", on ? "true" : "false");
      tab.tabIndex = on ? 0 : -1;
      const panel = document.getElementById(tab.dataset.tab);
      if (panel) panel.hidden = !on;
    });
    if (focus) chosen.focus();
  };
  tabs.forEach((tab, i) => {
    tab.addEventListener("click", () => select(tab, false));
    tab.addEventListener("keydown", (event) => {
      const step = { ArrowRight: 1, ArrowLeft: -1 }[event.key];
      if (step) { event.preventDefault(); select(tabs[(i + step + tabs.length) % tabs.length], true); }
    });
  });
  // A link like #panel-ready opens that tab (the plan page uses this to stay on the tab you were working in).
  const linked = tabs.find((t) => `#${t.dataset.tab}` === window.location.hash);
  select(linked || tabs.find((t) => t.getAttribute("aria-selected") === "true") || tabs[0], false);
});

// Copy buttons: <button data-copy="#id"> copies the text of that element.
document.addEventListener("click", async (event) => {
  const button = event.target.closest?.("[data-copy]");
  if (!button) return;
  const source = document.querySelector(button.dataset.copy);
  if (!source) return;
  const original = button.textContent;
  try {
    await navigator.clipboard.writeText(source.textContent.trim());
    button.textContent = "Copied";
  } catch {
    const range = document.createRange();  // no clipboard access (plain http): select it so Ctrl+C works
    range.selectNodeContents(source);
    window.getSelection().removeAllRanges();
    window.getSelection().addRange(range);
    button.textContent = "Selected: press Ctrl+C";
  }
  setTimeout(() => { button.textContent = original; }, 2500);
});

// Clip editor: capture start/end from the player and preview the selected window.
function setupClipEditor() {
  const player = document.querySelector("#clip-player");
  if (!player) return;
  const startInput = document.querySelector("#start");
  const endInput = document.querySelector("#end");

  const format = (seconds) => {
    const tenths = Math.round(seconds * 10);
    const minutes = Math.floor(tenths / 600);
    const rest = ((tenths % 600) / 10).toFixed(1).padStart(4, "0");
    return `${minutes}:${rest}`;
  };

  const parse = (text) => {
    const trimmed = text.trim();
    if (!trimmed) return null;
    const parts = trimmed.split(":").map(Number);
    if (parts.length > 3 || parts.some((n) => !Number.isFinite(n) || n < 0)) return null;
    return parts.reduce((total, n) => total * 60 + n, 0);
  };

  const autoFill = document.querySelector("#auto-fill");
  const lengthInput = document.querySelector("#clip-length");
  const duration = Number(player.dataset.duration || 0) / 1000; // 0 when unknown

  // Setting one end (by capturing it or typing it) fills in the other end a clip-length away, kept
  // inside the track. A value filled in this way is marked data-auto, so it is replaced when the first end
  // changes again but a value you typed yourself is never overwritten.
  function fillOther(isStart, seconds, overwrite) {
    const length = Number(lengthInput?.value);
    if (!autoFill?.checked || !Number.isFinite(length) || length <= 0 || !Number.isFinite(seconds)) return;
    const other = isStart ? endInput : startInput;
    if (!overwrite && other.value.trim() !== "" && other.dataset.auto !== "1") return;
    if (isStart) {
      const end = seconds + length;
      other.value = duration > 0 && end >= duration ? "" : format(end); // blank = play to the end
    } else {
      other.value = format(Math.max(0, seconds - length));
    }
    other.dataset.auto = "1";
  }

  document.querySelectorAll("[data-capture]").forEach((button) => {
    button.addEventListener("click", () => {
      const here = player.currentTime;
      const isStart = button.dataset.capture === "start";
      const target = isStart ? startInput : endInput;
      target.value = format(here);
      delete target.dataset.auto;
      fillOther(isStart, here, true);
      showPosition();
    });
  });

  // Typing a time: your own entry is yours; the other end is filled in only if it is empty or was filled in
  // automatically. "change" fires when you leave the box, so half-typed times aren't acted on.
  [[startInput, true], [endInput, false]].forEach(([input, isStart]) => {
    input.addEventListener("input", () => { delete input.dataset.auto; });
    input.addEventListener("change", () => {
      const seconds = parse(input.value);
      if (seconds === null) return;
      fillOther(isStart, seconds, false);
      showPosition();
    });
  });

  // Live readout: where the player is, how far into the clip that is, and how long is left.
  const position = document.querySelector("#position");
  function showPosition() {
    if (!position) return;
    const now = player.currentTime;
    const start = parse(startInput.value) ?? 0;
    const end = parse(endInput.value);
    let text = `Position ${format(now)}`;
    if (now >= start) text += ` \u00b7 ${format(now - start)} into the clip`;
    else text += ` \u00b7 ${format(start - now)} before the clip starts`;
    if (end !== null && now <= end) text += ` \u00b7 ${format(end - now)} left`;
    else if (end !== null) text += " \u00b7 past the clip end";
    position.textContent = text;
  }
  let ticking = false;
  function tick() {
    showPosition();
    if (!player.paused && !player.ended) requestAnimationFrame(tick);
    else ticking = false;
  }
  player.addEventListener("play", () => { if (!ticking) { ticking = true; requestAnimationFrame(tick); } });
  ["timeupdate", "seeked", "seeking", "pause", "loadedmetadata"].forEach((name) => player.addEventListener(name, showPosition));
  startInput.addEventListener("input", showPosition);
  endInput.addEventListener("input", showPosition);
  showPosition();

  let windowEnd = null;
  player.addEventListener("timeupdate", () => {
    if (windowEnd !== null && player.currentTime >= windowEnd) {
      player.pause();
      windowEnd = null;
    }
  });
  player.addEventListener("pause", () => {
    // A manual pause cancels the preview auto-stop.
    if (windowEnd !== null && player.currentTime < windowEnd) windowEnd = null;
  });

  document.querySelector("#preview")?.addEventListener("click", () => {
    player.currentTime = parse(startInput.value) ?? 0;
    windowEnd = parse(endInput.value);
    player.play();
  });

  // Suggest sections: the browser decodes the audio, suggest.js finds loud parts that repeat (usually the chorus).
  const suggestButton = document.querySelector("#suggest");
  suggestButton?.addEventListener("click", async () => {
    const status = document.querySelector("#suggest-status");
    const list = document.querySelector("#suggestions");
    suggestButton.disabled = true;
    list.replaceChildren();
    status.textContent = "Listening to the song\u2026";
    try {
      const { toMono, extractFeatures, suggestWindows } = await import("./suggest.js");
      const response = await fetch(player.currentSrc || player.src);
      if (!response.ok) throw new Error("download");
      const Context = window.AudioContext || window.webkitAudioContext;
      const context = new Context();
      let decoded;
      try { decoded = await context.decodeAudioData(await response.arrayBuffer()); } finally { context.close?.(); }
      const channels = Array.from({ length: decoded.numberOfChannels }, (_, c) => decoded.getChannelData(c));
      await new Promise((resolve) => setTimeout(resolve, 0)); // let "Listening" paint before the number crunching
      const mono = toMono(channels, decoded.sampleRate);
      const length = Number(lengthInput?.value) > 0 ? Number(lengthInput.value) : 30;
      const found = suggestWindows(extractFeatures(mono.samples, mono.rate), length, 3);
      if (!found.length) {
        status.textContent = `This song is too short for a ${length}-second clip. Lower the clip length and try again.`;
        return;
      }
      status.textContent = "";
      found.forEach((section, index) => {
        const likely = section.loud >= 0.6 && section.repeat >= 0.6;
        const note = likely ? "loud and repeated, likely a chorus" : section.loud < 0.4 ? "repeated, but quiet" : "worth a listen";
        const item = document.createElement("li");
        item.append(`${index + 1}. ${format(section.start)} \u2013 ${format(section.end)} \u00b7 ${note} `);
        const use = document.createElement("button");
        use.type = "button"; use.textContent = "Use"; use.className = "secondary";
        use.addEventListener("click", () => {
          startInput.value = format(section.start);
          endInput.value = duration > 0 && section.end >= duration ? "" : format(section.end);
          delete startInput.dataset.auto; delete endInput.dataset.auto;
          showPosition();
        });
        const listen = document.createElement("button");
        listen.type = "button"; listen.textContent = "Listen"; listen.className = "secondary";
        listen.addEventListener("click", () => { player.currentTime = section.start; windowEnd = section.end; player.play(); });
        item.append(use, " ", listen);
        list.append(item);
      });
    } catch (error) {
      status.textContent = "Couldn't analyse this song in your browser. You can still set the start and end by hand.";
    } finally {
      suggestButton.disabled = false;
    }
  });
}

setupClipEditor();

// New-game page: filter the song list, bulk select, and show how many songs are chosen.
function setupSongPicker() {
  const picker = document.querySelector("[data-song-picker]");
  if (!picker) return;
  const rows = [...picker.querySelectorAll("tbody tr")];
  const filter = picker.querySelector("[data-filter]");
  const counter = picker.querySelector("#selected-count");
  const gridInput = document.querySelector("#grid_size");
  const checkbox = (row) => row.querySelector("input[type=checkbox]");

  const update = () => {
    const chosen = rows.filter((row) => checkbox(row).checked).length;
    const size = parseInt(gridInput?.value, 10);
    const needed = Number.isFinite(size) ? size * size : null;
    let text = `${chosen} song${chosen === 1 ? "" : "s"} selected`;
    if (needed !== null) text += ` \u2014 a ${size}\u00d7${size} card needs at least ${needed}`;
    counter.textContent = text;
  };

  // Same rules as the library search (app/services/search.py): words must all match, !tag leaves a tag out,
  // "quotes" keep a phrase together, and no:tags finds songs with no tags.
  const parseQuery = (text) => {
    const words = [], excluded = [];
    let untagged = false;
    for (const m of text.slice(0, 100).matchAll(/(!?)(?:"([^"]*)"?|(\S+))/g)) {
      const token = (m[2] ?? m[3] ?? "").trim().replace(/\s+/g, " ").toLowerCase();
      if (!token || (token === "!" && !m[1])) continue;  // a lone "!" means nothing
      if (m[1]) { if (!excluded.includes(token)) excluded.push(token); }
      else if (token === "no:tags") untagged = true;
      else words.push(token);
    }
    return { words, excluded, untagged };
  };
  const rowMatches = (row, query) => {
    const tags = (row.dataset.tags || "").split(",").filter(Boolean);
    if (query.untagged && tags.length) return false;
    if (query.excluded.some((tag) => tags.includes(tag))) return false;
    return query.words.every((word) => row.dataset.text.includes(word));
  };
  filter?.addEventListener("input", () => {
    const query = parseQuery(filter.value);
    rows.forEach((row) => { row.hidden = !rowMatches(row, query); });
  });
  picker.querySelector("[data-select=visible]")?.addEventListener("click", () => {
    rows.filter((row) => !row.hidden).forEach((row) => { checkbox(row).checked = true; });
    update();
  });
  picker.querySelector("[data-select=none]")?.addEventListener("click", () => {
    rows.forEach((row) => { checkbox(row).checked = false; });
    update();
  });
  picker.addEventListener("change", update);
  gridInput?.addEventListener("input", update);
  update();
}

setupSongPicker();

// Error pages: <a href="/" data-back>Go back</a> returns to the previous page when there is one.
document.addEventListener("click", (event) => {
  const link = event.target.closest?.("[data-back]");
  if (link && window.history.length > 1) {
    event.preventDefault();
    window.history.back();
  }
});

// Library upload: show real progress while the files travel, with something to read while you wait.
const BAR_LINES = [
  "Tuning the jukebox\u2026",
  "Wiping down the bar\u2026",
  "Polishing the mirror ball\u2026",
  "Asking the drummer to count us in\u2026",
  "Restocking the pretzels\u2026",
  "Checking the songs are in tune\u2026",
  "Pulling the pints, one track at a time\u2026",
  "Sweeping up the dance floor\u2026",
  "Last call for uploads\u2026",
  "Sound check, one, two\u2026",
];

function setupUploadForm() {
  const form = document.querySelector("form[data-upload]");
  if (!form || !window.XMLHttpRequest || !window.FormData) return; // the plain form still works
  const box = form.querySelector(".upload-progress");
  const bar = box.querySelector("progress");
  const text = box.querySelector("[data-upload-text]");
  const button = form.querySelector("button[type=submit]");
  let lines = null;

  const megabytes = (n) => (n / (1024 * 1024)).toFixed(1);
  const stop = () => { clearInterval(lines); lines = null; button.disabled = false; };

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const request = new XMLHttpRequest();
    request.open("POST", form.action);
    request.setRequestHeader("X-Requested-With", "xhr");
    request.responseType = "json";
    box.hidden = false;
    bar.value = 0;
    button.disabled = true;
    let line = Math.floor(Math.random() * BAR_LINES.length);
    let status = "";
    const show = () => { text.textContent = status ? `${status} ${BAR_LINES[line]}` : BAR_LINES[line]; };
    lines = setInterval(() => { line = (line + 1) % BAR_LINES.length; show(); }, 2500);
    show();

    request.upload.addEventListener("progress", (e) => {
      if (!e.lengthComputable) return;
      bar.value = Math.round((e.loaded / e.total) * 100);
      status = `${bar.value}% (${megabytes(e.loaded)} of ${megabytes(e.total)} MB).`;
      show();
    });
    request.upload.addEventListener("load", () => {
      bar.removeAttribute("value"); // sent; the server is now reading each file's tags
      status = "Uploaded. Filing the tracks away.";
      show();
    });
    request.addEventListener("load", () => {
      stop();
      const target = request.response && request.response.redirect;
      if (request.status >= 200 && request.status < 300 && target) window.location.href = target;
      else { box.hidden = false; bar.value = 0; text.textContent = "The upload didn't go through. Reload the page and try again."; }
    });
    const failed = () => { stop(); bar.value = 0; text.textContent = "The upload was interrupted. Check your connection and try again."; };
    request.addEventListener("error", failed);
    request.addEventListener("abort", failed);
    request.send(new FormData(form));
  });
}

setupUploadForm();

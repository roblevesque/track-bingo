// Small progressive enhancements. No build step: this file is served as-is.

// Confirm before destructive form submits: <form data-confirm="Are you sure?">
document.addEventListener("submit", (event) => {
  const message = event.target.dataset?.confirm;
  if (message && !window.confirm(message)) event.preventDefault();
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

  document.querySelectorAll("[data-capture]").forEach((button) => {
    button.addEventListener("click", () => {
      const here = player.currentTime;
      const isStart = button.dataset.capture === "start";
      (isStart ? startInput : endInput).value = format(here);
      const length = Number(lengthInput?.value);
      if (autoFill?.checked && Number.isFinite(length) && length > 0) {
        // Capturing one end sets the other end a clip-length away, kept inside the track.
        if (isStart) {
          const end = here + length;
          endInput.value = duration > 0 && end >= duration ? "" : format(end); // blank = play to the end
        } else {
          startInput.value = format(Math.max(0, here - length));
        }
      }
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

  filter?.addEventListener("input", () => {
    const needle = filter.value.trim().toLowerCase();
    rows.forEach((row) => { row.hidden = needle !== "" && !row.dataset.text.includes(needle); });
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

// The phone remote: shows the game and sends button presses to the host console, which plays the audio.
import { connectLive, statusText } from "./live.js";
import { renderCardCheck } from "./card_view.js";
import { formatClock } from "./playback.js";

const root = document.querySelector("#remote");

if (root) {
  const id = root.dataset.id;
  const csrf = root.dataset.csrf;
  const $ = (selector) => root.querySelector(selector);
  const el = (tag, text, className) => {
    const node = document.createElement(tag);
    node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  let state = JSON.parse(document.querySelector("#initial-state").textContent);
  let effectsSignature = "";
  const recent = new Set(); // buttons pressed in the last moment: a double tap on one button can't send twice,
  // while a quick tap on a different button still goes straight through
  let toastTimer = null;

  function toast(message) {
    $("#r-toast").textContent = message;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { $("#r-toast").textContent = ""; }, 2500);
  }

  function render(next) {
    state = next;
    const offline = !state.console_online;
    const active = state.status === "active";
    const draft = state.status === "draft";

    $("#r-title").textContent = state.name;
    $("#r-offline").hidden = !offline;
    $("#r-round").textContent = state.round ? `${state.round.name}: ${state.round.text}` : "";
    $("#r-now").textContent = state.current ? state.current.title : "Nothing yet";
    $("#r-now-artist").textContent = state.current && state.current.artist ? `\u2014 ${state.current.artist}` : "";
    const fact = state.current && state.current.fun_fact && active ? state.current.fun_fact : "";
    $("#r-fact").textContent = fact ? `Fun fact: ${fact}` : "";
    $("#r-fact").hidden = !fact;
    $("#r-next-song").textContent = state.next ? `${state.next.title}${state.next.artist ? " \u2014 " + state.next.artist : ""}` : "\u2014";
    const nextFact = state.next && state.next.fun_fact && active ? state.next.fun_fact : "";
    $("#r-next-fact").textContent = nextFact ? `Fun fact: ${nextFact}` : "";
    $("#r-next-fact").hidden = !nextFact;
    $("#r-progress").textContent = draft ? "Game not started." : state.status === "finished" ? "The game has ended." : `${state.songs_played} of ${state.total_songs} songs played`;

    $("#r-start").hidden = !draft;
    $("#r-start").disabled = offline;
    $("#r-next").disabled = offline || !active || !state.next;
    $("#r-skip").disabled = offline || !active || !state.next;
    $("#r-pause").disabled = offline;
    $("#r-replay").disabled = offline || !state.current;
    $("#r-next-round").hidden = !state.has_next_round;
    $("#r-next-round").disabled = offline || !active;
    $("#r-stop-effect").disabled = offline;

    const banner = $("#r-win");
    banner.hidden = state.wins.length === 0;
    banner.textContent = state.wins.length
      ? "Bingo called! " + state.wins.map((w) => `${w.team} (card ${w.ticket}, ${w.detail})`).join(" \u2022 ")
      : "";

    const played = state.played || [];
    $("#r-played-count").textContent = played.length ? `(${played.length})` : "";
    $("#r-played").replaceChildren(...(played.length
      ? played.map((p, i) => {
        const li = el("li", `${p.title}${p.artist ? " \u2014 " + p.artist : ""}`, i === 0 && active ? "current" : "");
        li.value = p.n; // newest first, but keep each song's real number
        return li;
      })
      : [el("li", "Nothing has been played yet.", "muted")]));
    recheckCard();
    showClip();

    const signature = JSON.stringify(state.effects);
    if (signature !== effectsSignature) { // rebuild only when the list changes, so taps aren't interrupted
      effectsSignature = signature;
      $("#r-effects").replaceChildren(...state.effects.map((effect) => {
        const button = el("button", effect.label, "remote-btn secondary");
        button.type = "button";
        button.dataset.effect = effect.id;
        button.addEventListener("click", () => send("effect", { effect: effect.id }));
        return button;
      }));
    }
    [...$("#r-effects").children].forEach((button) => { button.disabled = offline; });
  }

  async function send(action, extra = {}) {
    const key = action + (extra.effect || "");
    if (recent.has(key)) return;
    recent.add(key);
    setTimeout(() => recent.delete(key), 350);
    if (navigator.vibrate) navigator.vibrate(25);
    const body = new FormData();
    body.set("csrf_token", csrf);
    body.set("action", action);
    Object.entries(extra).forEach(([key, value]) => body.set(key, value));
    try {
      const response = await fetch(`/remote/${id}/command`, { method: "POST", body });
      if (response.ok) { toast("Sent"); return; }
      const data = await response.json().catch(() => ({}));
      toast(typeof data.detail === "string" ? data.detail : "That didn't work.");
    } catch {
      toast("No connection. Check your signal.");
    }
  }

  // ---- check a printed card: the card stays on screen and is checked again as songs play
  let checkedCard = null; // { number, at (the game moment it was last checked at) }
  async function recheckCard() {
    if (!checkedCard) return;
    const at = `${state.songs_played}/${state.status}/${state.round && state.round.number}`;
    if (checkedCard.at === at) return;
    const card = checkedCard;
    card.at = at;
    const box = $("#r-check-result");
    const body = new FormData();
    body.set("csrf_token", csrf);
    body.set("ticket_number", card.number);
    let data = null;
    let problem = "No connection. Check your signal.";
    try {
      const response = await fetch(`/remote/${id}/check`, { method: "POST", body });
      data = await response.json().catch(() => ({}));
      if (!response.ok) { problem = typeof data.detail === "string" ? data.detail : "That didn't work."; data = null; }
    } catch { /* keep the connection message */ }
    if (card !== checkedCard) return; // another card was checked meanwhile
    if (!data) {
      checkedCard = null;
      box.replaceChildren(el("p", problem, "flash error"));
      box.hidden = false;
      return;
    }
    renderCardCheck(box, data, { compact: true });
  }
  $("#r-check").addEventListener("submit", (event) => {
    event.preventDefault();
    checkedCard = { number: event.target.elements.ticket_number.value, at: "" };
    event.target.elements.ticket_number.blur(); // put the phone keyboard away so the card is visible
    recheckCard();
  });

  // ---- clip progress: the console reports when a clip starts, stops or jumps, and we count on from there
  let playback = null;
  let playbackAt = 0;
  function showClip() {
    const box = $("#r-clip");
    const live = playback && state.status === "active" && state.current && state.current.id === playback.song_id;
    box.hidden = !live;
    if (!live) return;
    let elapsed = playback.elapsed + (playback.paused ? 0 : (performance.now() - playbackAt) / 1000);
    const length = playback.length === null ? NaN : playback.length;
    if (Number.isFinite(length)) elapsed = Math.min(elapsed, length);
    $("#r-clip-fill").style.width = length > 0 ? `${((elapsed / length) * 100).toFixed(1)}%` : "0%";
    $("#r-clip-time").textContent = `${playback.paused ? "Paused \u00b7 " : ""}${formatClock(elapsed)} / ${formatClock(length)}`;
    const bar = $("#r-clip-bar");
    bar.setAttribute("aria-valuemax", String(Math.round(length) || 0));
    bar.setAttribute("aria-valuenow", String(Math.round(elapsed)));
  }
  setInterval(showClip, 250);

  $("#r-start").addEventListener("click", () => send("start"));
  $("#r-next").addEventListener("click", () => send("next", { expect: state.songs_played }));
  $("#r-pause").addEventListener("click", () => send("pause"));
  $("#r-replay").addEventListener("click", () => send("replay"));
  $("#r-skip").addEventListener("click", () => send("skip", { expect_next: state.next ? state.next.id : "" }));
  $("#r-next-round").addEventListener("click", () => send("next_round"));
  $("#r-stop-effect").addEventListener("click", () => send("stop_effect"));

  // Keep the screen on while the remote is open (not every browser supports this).
  let wakeLock = null;
  async function keepAwake() {
    try { if (navigator.wakeLock && document.visibilityState === "visible") wakeLock = await navigator.wakeLock.request("screen"); }
    catch { /* not allowed: the screen may dim, which is fine */ }
  }
  document.addEventListener("visibilitychange", keepAwake);
  keepAwake();

  render(state);
  connectLive(`/remote/${id}/events`, {
    onState: render,
    onStatus: (name) => {
      $("#r-connection").textContent = name === "live" ? "" : statusText(name);
    },
    events: {
      playback: (report) => { playback = report; playbackAt = performance.now(); showClip(); },
      presence: (info) => render({ ...state, console_online: info.console_online }),
      revoked: () => { window.location.href = "/remote"; }, // the host changed the code or turned the remote off
    },
  });
}

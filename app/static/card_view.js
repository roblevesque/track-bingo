// Draws the result of checking a printed card: the verdict, then the card itself with the played squares crossed
// out, so the host can hold the paper next to the screen. Used by the host console and the phone remote.

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  if (className) node.className = className;
  return node;
}

/** One line summing up the check, e.g. "Card 12 WINS Round 1: row 2." */
export function verdictText(d) {
  if (d.status === "win") return `Card ${d.ticket} WINS ${d.round}: ${d.lines.join(", ") || "full house"}.`;
  const need = d.missing.length ? ` Still needs: ${d.missing.join("; ")}.` : "";
  return `Card ${d.ticket} does not win ${d.round} yet (${d.squares_needed} short).${need}`;
}

/** Fill `box` with the verdict and the card. `compact` (the phone) leaves out artists and the "still needs" list. */
export function renderCardCheck(box, d, { compact = false } = {}) {
  const win = d.status === "win";
  const verdict = el("p", compact && !win ? `Card ${d.ticket} does not win ${d.round} yet (${d.squares_needed} short).` : verdictText(d),
    `flash ${win ? "success" : "error"}`);
  const grid = el("div", "", `check-card${compact ? " compact" : ""}`);
  grid.dataset.size = d.size;
  grid.style.gridTemplateColumns = `repeat(${d.size}, minmax(0, 1fr))`;
  const played = d.squares.filter((s) => s.played).length;
  grid.setAttribute("role", "img");
  grid.setAttribute("aria-label", `Card ${d.ticket}: ${played} of ${d.squares.length} squares played`);
  grid.replaceChildren(...d.squares.map((s) => {
    const classes = ["cc-square"];
    if (s.played) classes.push("played");
    if (s.winning) classes.push("winning");
    if (s.needed) classes.push("needed");
    const square = el("div", "", classes.join(" "));
    square.title = `${s.title}${s.artist ? " — " + s.artist : ""}${s.played ? " (played)" : ""}`;
    square.append(el("strong", s.title));
    if (!compact && s.artist) square.append(el("span", s.artist));
    return square;
  }));
  const legend = el("p", "", "check-legend muted");
  legend.append(el("span", "✕", "key played"), " played ");
  if (win) legend.append(el("span", "", "key winning"), " winning squares");
  else if (d.squares.some((s) => s.needed)) legend.append(el("span", "", "key needed"), " still needed");
  box.replaceChildren(verdict, grid, legend);
  box.hidden = false;
}

// The card footer editor: up to four lines with **bold** and *italic*. The server (and the PDF) is the source of
// truth; this parser is a port of app/services/branding.py (tests compare the two) used for the live preview.

export const MAX_LINES = 4;
export const MAX_CHARS = 400;

export function cleanFooter(text) {
  return String(text || "").replace(/\r\n?/g, "\n").split("\n")
    .map((line) => line.split(/\s+/).filter(Boolean).join(" ")).filter(Boolean).join("\n");
}

/** One line as runs of [text, bold, italic]. A marker with no partner, or with a space on its inside edge, is text. */
export function parseInline(line) {
  const tokens = [...line.matchAll(/\*\*|\*/g)].map((m) => [m.index, m[0]]);
  const space = (ch) => /\s/.test(ch);
  const opens = (i) => {
    const [pos, kind] = tokens[i];
    const after = line.slice(pos + kind.length, pos + kind.length + 1);
    if (!after || space(after)) return false;
    return tokens.slice(i + 1).some(([p, t]) => t === kind && p > pos + kind.length && !space(line[p - 1]));
  };
  const closes = (i) => tokens[i][0] > 0 && !space(line[tokens[i][0] - 1]);

  const runs = [];
  let bold = false, italic = false, cursor = 0;
  const add = (end) => { if (end > cursor) runs.push([line.slice(cursor, end), bold, italic]); };
  tokens.forEach(([pos, kind], i) => {
    if (pos < cursor) return;
    const isBold = kind === "**";
    const active = isBold ? bold : italic;
    if (active ? closes(i) : opens(i)) add(pos); else return;
    cursor = pos + kind.length;
    if (isBold) bold = !bold; else italic = !italic;
  });
  add(line.length);
  const merged = [];
  for (const [text, b, it] of runs) {
    const last = merged[merged.length - 1];
    if (last && last[1] === b && last[2] === it) last[0] += text; else merged.push([text, b, it]);
  }
  return merged;
}

export function parseFooter(text) {
  return cleanFooter(text).split("\n").filter(Boolean).map(parseInline);
}

/** Fill in ${GAME.NAME} and ${GAME.DATE} (only the ones given); anything else is left as typed. */
export function expandVariables(text, vars) {
  return text.replace(/\$\{\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\}/g, (all, key) => vars[key.toUpperCase()] ?? all);
}

/** Draw the footer into an element using text nodes only, so nothing typed can become markup. */
export function renderFooter(element, text, vars = {}) {
  element.replaceChildren();
  for (const runs of parseFooter(text)) {
    const line = document.createElement("div");
    for (const [chunk, bold, italic] of runs) {
      let node = document.createTextNode(expandVariables(chunk, vars));
      if (italic) { const em = document.createElement("em"); em.append(node); node = em; }
      if (bold) { const strong = document.createElement("strong"); strong.append(node); node = strong; }
      line.append(node);
    }
    element.append(line);
  }
}

function today() {
  return new Date().toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" });
}

function wrapSelection(textarea, mark) {
  const { selectionStart: start, selectionEnd: end, value } = textarea;
  textarea.focus();
  textarea.setRangeText(mark + value.slice(start, end) + mark, start, end, "preserve");
  textarea.setSelectionRange(start + mark.length, end + mark.length);
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
}

function setUp(root) {
  const textarea = root.querySelector("textarea");
  const preview = document.querySelector(root.dataset.preview || "[data-preview]");
  const count = root.querySelector("[data-count]");
  const vars = { "GAME.DATE": today() };
  if (root.dataset.gameName) vars["GAME.NAME"] = root.dataset.gameName;

  const update = () => {
    const clean = cleanFooter(textarea.value);
    const lines = clean ? clean.split("\n").length : 0;
    if (preview) {
      renderFooter(preview, textarea.value, vars);
      preview.hidden = !clean;
    }
    if (count) {
      count.textContent = `${lines} of ${MAX_LINES} lines · ${clean.length} of ${MAX_CHARS} characters`;
      count.classList.toggle("over", lines > MAX_LINES || clean.length > MAX_CHARS);
    }
  };
  root.querySelectorAll("[data-md]").forEach((button) => {
    button.addEventListener("click", () => wrapSelection(textarea, button.dataset.md));
  });
  textarea.addEventListener("keydown", (event) => {
    if (!(event.ctrlKey || event.metaKey) || event.altKey) return;
    const mark = { b: "**", i: "*" }[event.key.toLowerCase()];
    if (mark) { event.preventDefault(); wrapSelection(textarea, mark); }
  });
  textarea.addEventListener("input", update);
  update();
}

if (typeof document !== "undefined") document.querySelectorAll("[data-footer-editor]").forEach(setUp);

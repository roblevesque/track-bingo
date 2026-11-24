// Live preview for the branding form. The server is the source of truth; this is only a mock-up.
const form = document.querySelector("#branding-form");

if (form) {
  const $ = (selector) => document.querySelector(selector);
  const preview = $("#preview");
  const header = $("#pv-header");
  const logo = $("#pv-logo");
  const title = $("#pv-title");

  // Same rule as the server: black or white text, whichever is more readable on the colour.
  function readableOn(hex) {
    const channel = (i) => {
      const c = parseInt(hex.slice(1 + 2 * i, 3 + 2 * i), 16) / 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    };
    return 0.2126 * channel(0) + 0.7152 * channel(1) + 0.0722 * channel(2) > 0.179 ? "#000" : "#fff";
  }

  // The preview approximates the print: the same font family, style and colour, and the size scaled to the mock-up.
  const FAMILY = { sans: "Helvetica, Arial, sans-serif", serif: "'Times New Roman', Times, serif", mono: "'Courier New', monospace" };
  function look(selector, key, fallbackSize) {
    const size = parseFloat($(`#${key}_size`).value);
    const style = $(`#${key}_style`).value;
    for (const el of document.querySelectorAll(selector)) {
      el.style.fontFamily = FAMILY[$(`#${key}_font`).value] || FAMILY.sans;
      el.style.fontWeight = style.includes("bold") ? "700" : "400";
      el.style.fontStyle = style.includes("italic") ? "italic" : "normal";
      el.style.color = $(`#${key}_color`).value;
      el.style.fontSize = `${Math.min(22, Math.max(8, (Number.isFinite(size) && size > 0 ? size : fallbackSize) * 0.85))}px`;
    }
  }

  let logoUrl = preview.dataset.logo || "";
  function update() {
    title.textContent = $("#header_text").value.trim() || "Your game name";
    look(".pv-song", "title", 12);
    look(".pv-artist", "artist", 10);
    const accent = $("#use_accent").checked ? $("#accent_color").value : "";
    header.style.background = accent || "transparent";
    header.style.color = accent ? readableOn(accent) : "inherit";
    logo.hidden = !logoUrl;
    if (logoUrl) logo.src = logoUrl;
  }

  $("#logo").addEventListener("change", (event) => {
    const file = event.target.files[0];
    if (logoUrl.startsWith("blob:")) URL.revokeObjectURL(logoUrl);
    logoUrl = file ? URL.createObjectURL(file) : preview.dataset.logo || "";
    update();
  });
  form.addEventListener("input", update);
  update();
}

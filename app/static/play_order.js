// The game page's play order: drag a song by its handle (mouse or touch), or use the arrow buttons, then save.
// The list is a form of hidden inputs in play order, so what is saved is simply the order of the rows.
const form = document.querySelector("#order-form");
const list = document.querySelector("#order-list");

if (form && list) {
  const status = document.querySelector("#order-status");
  const reset = document.querySelector("#order-reset");
  const scroller = list.closest(".order-scroll");
  const rows = () => [...list.children];
  const original = rows();
  let dirty = false;

  const markChanged = (row) => {
    dirty = rows().some((r, i) => r !== original[i]);
    status.textContent = dirty ? "Unsaved changes" : "";
    reset.disabled = !dirty;
    if (row) {
      row.classList.remove("moved");
      void row.offsetWidth; // restart the highlight if the same row moves again
      row.classList.add("moved");
      setTimeout(() => row.classList.remove("moved"), 700);
    }
  };

  // Arrow buttons: to the top, up one, down one. Focus stays on the button pressed so it can be pressed again.
  list.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-move]");
    if (!button) return;
    const row = button.closest("li");
    const move = button.dataset.move;
    if (move === "top") list.prepend(row);
    else if (move === "up" && row.previousElementSibling) row.previousElementSibling.before(row);
    else if (move === "down" && row.nextElementSibling) row.nextElementSibling.after(row);
    else return;
    button.focus();
    row.scrollIntoView({ block: "nearest" });
    markChanged(row);
  });

  // Dragging by the handle. Pointer events work the same for a mouse and a finger; the handle has
  // touch-action: none so a drag doesn't scroll the page instead.
  let dragged = null;
  let autoScroll = 0;
  let pointerY = 0;

  const placeAt = (y) => {
    const target = rows().find((r) => r !== dragged && y < r.getBoundingClientRect().top + r.offsetHeight / 2);
    if (target) { if (target !== dragged.nextElementSibling) target.before(dragged); }
    else if (list.lastElementChild !== dragged) list.append(dragged);
  };

  const scrollStep = () => { // keep scrolling the list while the finger rests near its top or bottom edge
    if (!dragged) return;
    const box = scroller.getBoundingClientRect();
    const edge = 40;
    const speed = pointerY < box.top + edge ? -8 : pointerY > box.bottom - edge ? 8 : 0;
    if (speed) { scroller.scrollTop += speed; placeAt(pointerY); }
    autoScroll = requestAnimationFrame(scrollStep);
  };

  list.addEventListener("pointerdown", (event) => {
    const handle = event.target.closest(".order-handle");
    if (!handle || event.button > 0) return;
    event.preventDefault();
    dragged = handle.closest("li");
    dragged.classList.add("dragging");
    handle.setPointerCapture(event.pointerId);
    pointerY = event.clientY;
    autoScroll = requestAnimationFrame(scrollStep);
  });

  list.addEventListener("pointermove", (event) => {
    if (!dragged) return;
    pointerY = event.clientY;
    placeAt(pointerY);
  });

  const endDrag = () => {
    if (!dragged) return;
    cancelAnimationFrame(autoScroll);
    dragged.classList.remove("dragging");
    const row = dragged;
    dragged = null;
    markChanged(row);
  };
  list.addEventListener("pointerup", endDrag);
  list.addEventListener("pointercancel", endDrag);

  document.querySelector("#order-shuffle").addEventListener("click", () => {
    const shuffled = rows();
    for (let i = shuffled.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
    }
    list.append(...shuffled);
    scroller.scrollTop = 0;
    markChanged();
  });

  reset.addEventListener("click", () => {
    list.append(...original);
    markChanged();
  });

  // Don't lose an arrangement by navigating away before saving it.
  window.addEventListener("beforeunload", (event) => { if (dirty) event.preventDefault(); });
  form.addEventListener("submit", () => { dirty = false; });
}

# Changelog

The longer story behind each change. Commit messages stay short; the detail lives here.
Newest first. Earlier history is in `git log` and in PLAN.md.

## 2026-11-24

### Changed
- **Shape picker is a dropdown.** On the game page a round's custom shapes are chosen from a dropdown of checkboxes
  instead of a long list. When closed it names the ticked shapes (or how many, past three). It is a plain `<details>`
  element, so it works without JavaScript; `app.js` keeps the label up to date and closes it on Esc or a click outside
  (`details[data-multi-select]`, reusable elsewhere).
- **Printed card layout.** The header text is larger (22pt on a one-per-page card, 14pt on smaller ones). The card
  number drops the word "Card" and sits larger in a circle at the right of the header. The logo moves from the header
  to the bottom left, sized to the footer band (up to 50pt tall, or 30pt on smaller cards). The footer text is
  right-aligned on a band filled with the accent colour (no band without an accent). Its text is black, or white
  when the accent is too dark for black to read, using the same rule as the header. The Branding page
  preview and the game page footer preview follow the new look. Cards keep the same songs, so printed ones stay valid.
- Change the meaning of 'ready' for songs on a game edit screen to reflect clipped status. 

### Fixed
- **Saved shapes showed unticked on the game page.** Matching a round's shapes to the saved ones compared the stored
  text of the squares ("0,2,6,8") character by character, so nothing ever matched. Saving such a round from the game
  page then sent it with no shapes. It now compares the squares properly (`matching_shape_ids`), with a test.
- **Card borders didn't print.** The grid on printed cards was drawn in the branding accent colour at 0.6pt, which
  a pale accent turns into a near-invisible line on a grayscale or toner-saving printer (it looked fine in the PDF).
  The grid now always prints in black: 1pt between squares and a 1.5pt frame round the whole grid. The accent colour
  still fills the header band. The Branding page preview shows black squares to match. Only the styling changed, so
  cards already printed stay valid.

## 2026-11-23

### Added
- **Play order on the game page.** A *Play order* list where songs are dragged by their handle (mouse or finger) or
  moved with the top/up/down buttons, then saved. Before the start, **Start game** keeps the saved order instead of
  shuffling (*Forget this order* goes back to the shuffle). During a game only the songs still to come can move, and
  the console updates on save. Each save carries the song count the page saw, so a stale page is refused rather than
  replaying or dropping a song. Shuffle, Undo changes and an unsaved-changes warning are on the page too.
  (`POST /games/{id}/playlist/order` and `/order/clear`, `reorder_remaining` and `planned_order` in
  `app/services/playlist.py`, `app/static/play_order.js`, `tests/test_play_order.py`.)
- `CLAUDE.md` with project notes for Claude Code.

### Changed
- README and PLAN brought up to date: four sound effects (Suspense), effects are now WAV files you replace rather
  than generate, the layout sections list the newer modules, Upgrading lists every additive column, Possible next
  steps lists only what is left, and the two console items already delivered are ticked.
- `scripts/generate_effects.py` is reference only: running it overwrites the current Thinking, Win and Lose sounds.
- Makefile defaults point at the real image name (`roblevesque/track-bingo`).
- Changed order and location of cards on host console.

### Removed
- `app/static/effects/backups/` (old WAVs that were unused but publicly served).

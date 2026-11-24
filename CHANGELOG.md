# Changelog

The longer story behind each change. Commit messages stay short; the detail lives here.
Newest first. Earlier history is in `git log` and in PLAN.md.

## 2026-11-24

### Fixed
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

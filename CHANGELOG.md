# Changelog

The longer story behind each change. Commit messages stay short; the detail lives here.
Newest first. Earlier history is in `git log` and in PLAN.md.

## 2026-11-25

Changes from the notes taken at the first real game night.

### Added
- **Checking a card shows the card.** *Check a printed card* on the console now draws the card under the verdict:
  played squares are crossed out with a thin green X, a winning line or shape is filled green (every square for a
  full house), and when the card doesn't win yet the squares on its closest route to a win get a dashed outline. The
  card stays on screen and is checked again as each song plays, until another card is checked. The check moved into
  `app/services/card_check.py` so the console and the phone share it; the response gained `size` and `squares`.
- **Check a card from the phone.** The phone remote has a folded *Check a card* section with a smaller version
  of the same card (titles only). It is read-only, so it works even while the console is closed
  (`POST /remote/{id}/check`, paired phones only).
- **Clip progress.** The console shows the current song above the buttons with a progress bar and the time into
  the clip window against its length. The phone remote shows the same bar under the song title. The console posts
  its position to `POST /games/{id}/run/playback` whenever the clip starts, pauses or jumps; the server passes it to
  the phones and keeps the latest one, so a phone that connects mid-clip catches up. Phones count on between reports.
- **Even out song volumes.** The game page has a *Volume levels* section: **Measure** has the browser download
  each of the game's songs, measure its clip window's loudness (`app/static/loudness.js`: ITU-R BS.1770 / EBU R128
  integrated loudness with K-weighting and gating; at 48 kHz its filters are exactly the standard's coefficients)
  and save it (`POST /library/{id}/loudness`). The console's new *Even out song volumes* setting (on by default)
  plays each measured clip at about -16 LUFS (at most 10 dB up or 20 dB down), through a Web Audio gain and a
  limiter; the fade in/out now goes through the same gain when Web Audio is running. A song's edit page shows its
  measurement, can measure that one clip, and has a *Volume adjustment* in dB (up to 12 either way). New `song`
  columns `loudness_db`, `loudness_for` (the clip window measured, so moving the start or end makes it out of
  date) and `volume_adjust_db`; the console snapshot gained each song's `gain_db` and an `unmeasured` count.
  Checked against ffmpeg's EBU R128 meter on test tones: the same to 0.1 LU.
- **The game ends itself after the last song.** When the last clip finishes, the console waits the usual
  *Wait (seconds) after each clip* and then ends the game (and starts background music if that's ticked), whether
  or not automatic next song is on. A valid bingo on the last song, or **Cancel**, keeps the game open.
- **Played songs on the phone.** A folded *Played so far* list on the remote, newest first. The phone's view
  gained `played` and the current song's `id`; it still gets nothing about songs after the next one.

### Fixed
- **Cancelling the automatic next song.** The countdown said "Press Pause to stop auto-play", but once a clip had
  ended the button read Resume and pressing it replayed past the clip's end, which started the countdown again.
  The countdown now has its own **Cancel** button.

## 2026-11-24

### Changed
- **Un-Ready clips are now color on game page** Like the library, clipped and unclipped songs are now highlighted for quicker recognition. 
- **Shape picker is a dropdown.** On the game page a round's custom shapes are chosen from a dropdown of checkboxes
  instead of a long list. When closed it names the ticked shapes (or how many, past three). It is a plain `<details>`
  element, so it works without JavaScript; `app.js` keeps the label up to date and closes it on Esc or a click outside
  (`details[data-multi-select]`, reusable elsewhere). The host console's *Change what counts as a win* form uses the
  same dropdown.
- *Change the meaning of 'ready'**  Ready in the game edit screen now means song has been clipped. Not ready means they haven't been clipped.
- **Printed card layout.** The header text is larger (22pt on a one-per-page card, 14pt on smaller ones). The card
  number drops the word "Card" and sits larger in a circle at the right of the header. The logo moves from the header
  to the bottom left, sized to the footer band (up to 50pt tall, or 30pt on smaller cards). The footer text is
  right-aligned on a band filled with the accent colour (no band without an accent). Its text is black, or white
  when the accent is too dark for black to read, using the same rule as the header. The Branding page
  preview and the game page footer preview follow the new look. Cards keep the same songs, so printed ones stay valid. 

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

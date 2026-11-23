# Track Bingo: notes for Claude

Track Bingo is a music bingo app for a bar called Iron Horse, run by the owner's wife on game nights. Python, FastAPI,
SQLModel/SQLite, Jinja2 templates, vanilla JavaScript. **No Node.js in the app** and no front-end build step.
`README.md` describes every feature and how to run it; `PLAN.md` is the work plan and what has been delivered. Read both
before changing anything, and keep both up to date with each change.

## Commands
- `uv run uvicorn app.main:create_app --factory --reload` serves the app on http://127.0.0.1:8000
- `uv run pytest` runs the tests. Use uv, not pip.
- Some tests compare Python and JavaScript behaviour through Node (`tests/js/*.mjs`). They skip themselves when Node
  isn't installed. Node is a test-time extra only.
- ~~`uv run python scripts/generate_effects.py` regenerates the built-in sound effects (a test checks they match).~~ This still exists but has been superceeded by non-generated files. The tests can probably go away at some point.

## Layout
- `app/main.py` creates the app. `app/routes/` has one module per area (library, games, play, run, remote, planner, plans,
  branding, transfer, users...). `app/services/` holds the logic as plain functions that don't touch the web layer, so
  they're easy to test (checker, ticket_gen, pdf, planner, merge, duplicates, cardtext, branding...).
- `app/models.py` has the tables. `app/db.py` creates them and applies additive migrations: a new column on an
  existing table goes in `ADDITIVE_COLUMNS` with a default, a new table needs nothing beyond `create_all`.
- `app/templates/` is server-rendered Jinja. Pages never use `url_for` or absolute URLs; use the `static_url()` helper
  (`app/web.py`) for assets so the app works behind a reverse proxy with a path prefix.
- `app/static/` is plain ES modules. `app.js` loads on every page (`type="module"` in `base.html`); page-specific scripts
  go in `{% block scripts %}`.

## Conventions that matter
- Every POST form carries a `csrf_token` and the route calls `check_csrf`. Use `flash()` and `render()` from `app/web.py`.
- Destructive forms use the `data-confirm` attribute (handled in `app.js`) instead of custom confirm code.
- Users share one workspace (games, song library, branding). Deleting is allowed for administrators and the owner only
  (`can_delete`).
- A song's id is stored in several places: `GameSong` rows, `Ticket.cells` (JSON list), `Game.play_order` (JSON list) and
  `Plan.choices_json` (values). Anything that deletes or merges songs must update all of them (see `app/services/merge.py`
  and `_merge_songs` in `app/routes/library.py`).
- A card can't hold the same song twice, so a game pool must never contain two copies of one song.
- Printed cards must stay valid: don't change which songs are on a card when only labels or styling change.
- Python and JavaScript share a few parsers (clip times: `app/static/clip_time.js` and `app/services/parsing.py`; footer
  markdown: `footer_md.js` and `branding.py`). Change both sides together and keep the parity tests passing.
- PDF output uses reportlab with built-in fonts unless the user supplies a font file (then italic prints upright).

## Testing habits
- Route tests use the fixtures in `tests/conftest.py` (`app`, `logged_in`, `seed_songs`, `create_game`...). Note that
  `seed_songs` uploads identical audio bytes, so all its songs count as byte-identical duplicates. Tests that need
  distinct songs must upload different bytes. Game creation also refuses pools too small to make distinct cards
  (a 3x3 grid needs roughly a dozen songs for several cards).
- A draft game has an empty `play_order` until it is started, unless the host saved a planned order on the game page
  (Start then keeps it; see `planned_order` in `app/services/playlist.py`).
- When you change a page, check it at desktop width and at phone width (about 390px), and look for horizontal overflow.

## How the owner likes to work
- Changes arrive as zip patches that keep the folder paths, so they can be unzipped over the repo. Say what was changed. (Owner note: This process can likely be tweaked now that there is direct access to files.)
- Update `README.md` and `PLAN.md` with each feature.
- Be honest about what was verified and what wasn't. Say plainly when something could only be compiled or mocked, and
  never claim a real-device or real-data check that wasn't done.
- The owner runs `uv run pytest` and reports failures; a failure is often a wrong test expectation rather than an app
  bug, so read the test before changing the app.
- Merging duplicate songs and deleting are irreversible; make that clear in the UI and in the README.
- After every change, commit it to git so rollback is easy and possible. Push only after it's been tested.
- Keep commit messages short and sweet (a one-line summary, no long body). Put the longer, changelog-style detail in
  `CHANGELOG.md` (newest first, dated sections with Added / Changed / Fixed / Removed) in the same commit.

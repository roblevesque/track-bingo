# Track Bingo

A web-based music bingo game. The host plays short clips from their own song library through
their own speakers; players mark the matching songs on their cards, on their phones or on
paper. Pure Python: no Node.js and no front-end build step.

Inspired by [asrashley/music-bingo](https://github.com/asrashley/music-bingo). See
[PLAN.md](PLAN.md) for the roadmap and [DECISIONS.md](DECISIONS.md) for the design decisions.

## Features

- **Song library:** upload MP3 or Ogg clips, edit title, artist and tags (optionally written back into
  the file's own tags), and set a start and end point for each clip. Trimming is non-destructive: the
  file is never re-encoded and no ffmpeg is needed. You can tag a whole upload at once, and a progress
  bar shows how it is going. On a song's edit page a live readout shows how far into the clip the player is,
  and capturing one end of the clip fills in the other end from a default clip length.
- **Cards, not tickets:** the printable sheets and player screens are called cards everywhere. Old
  `/games/…/tickets/…` and `tickets.pdf` addresses redirect to the new `cards` ones, so bookmarks still work.
- **Games:** pick a song pool, a grid size (N×N, default 5×5) and a number of cards. Cards are
  unique and use every song about equally often.
- **Rounds with host-chosen patterns:** for each round the host decides what wins: rows, columns,
  diagonals, how many lines, or full house. The rules can be changed at any time, including mid-game.
- **Custom win shapes:** draw a shape once on the **Shapes** page (or add the common ones: four corners, X,
  L, T, frame, plus, diamond) and tick it for any round. A round set to *Custom shape* is won by the first
  card that completes any ticked shape. Rounds keep their own copy, so deleting a shape never breaks a game.
- **Editable playlist:** after a game is created, songs can be added, removed (if on no card) or replaced
  (swapped on every card) from the game page, even mid-game. Songs already played can't be changed.
- **Live play:** players join with a game code and a team name (no accounts), tap squares to mark
  them, and call Bingo. The server checks each claim against the songs actually played.
- **Host console:** start, next song, replay, pause, skip, reshuffle the songs not yet played, move
  to the next round, end the game. It lists every song still to come, in play order, beside the ones
  already played, and shows a banner the moment a team calls a valid bingo. On a wide screen the
  controls and claims sit on the left and the playlist and teams on the right. Optional automatic next
  song and fade in/out.
- **Phone remote:** run the game from your phone: next song, pause, replay, sound effects, and a bingo alert.
  The console shows a QR code: scan it and the pairing code is filled in, so you only tap Connect.
- **Suggested clip sections:** on a song's edit page, **Suggest sections** listens to the song in your browser
  (nothing is uploaded, no ffmpeg) and offers up to three clip-length sections that are loud and repeat elsewhere
  in the song, which is usually the chorus. **Use** fills in the start and end, and **Listen** plays the section.
  It is a starting point, not magic.
- **Fun facts:** add a note to any song (on its edit page). While that song plays, only you see it, on the
  console and on the phone remote. Notes travel with exported games.
- **Searching songs:** the library search and the new-game filter match every word. `!tag` leaves out songs
  with that exact tag (`!"classic rock"` for a tag with a space) and `no:tags` finds songs with no tags.
- **Sound effects:** one-click (or number-key) *Thinking*, *Win* and *Lose* sounds from the host console, for
  the moments around checking a claim.
- **Background music:** play your whole library, shuffled and quiet, before and after the game.
- **Printed cards:** download every card as one numbered PDF (one landscape card per page by
  default), hand them out, and check a paper card by number from the console. Each game can have its
  own footer line, for example to announce next week's game. Header and footer text can use
  `${GAME.NAME}` and `${GAME.DATE}`, e.g. `Iron Horse - ${GAME.NAME}`.
- **Card branding:** add your logo, an accent colour, and header and footer text from the web
  interface. They appear on the printed PDF and on the cards players see.
- **Users and permissions:** administrators add accounts (with a generated one-time password) and choose
  who can create games. Passwords are changed from the Account page.
- **Move a game between installs:** export a game, with its audio if you like, as one file and import it
  elsewhere. The cards stay identical, so printed ones still work.
- **Run again:** re-run a finished game under a new join code, keeping the same cards so printed
  copies stay valid (or regenerating them).
- **Phone friendly:** layouts tested at 375 px wide, with live updates that reconnect after a dropped
  connection or a phone waking up.

## Quick start

Requires [uv](https://docs.astral.sh/uv/) and Python 3.11 or newer.

```bash
uv sync                                                  # creates .venv and uv.lock
uv run uvicorn app.main:create_app --factory --reload   # http://127.0.0.1:8000
uv run pytest                                            # run the tests
```

On first visit you are sent to `/setup` to create the host account. That page closes as soon as one
host exists.

### Letting phones join

For a real game, players' phones must be able to reach the host's computer:

```bash
uv run uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
```

Then open the console using the computer's network address (for example
`http://192.168.1.20:8000`), **not** `localhost`. The join link shown in the console is built from the
address you used, so this is what makes it work on phones. Keep `MUSICBINGO_HTTPS_ONLY` at `0`
unless you serve the app over HTTPS, otherwise browsers won't send the login cookie. Some public
Wi-Fi networks isolate devices from each other; if phones can't connect, use your own hotspot or
router.

## Configuration

All optional, set as environment variables.

| Variable | Default | Purpose |
|---|---|---|
| `MUSICBINGO_APP_NAME` | `Track Bingo` | The name shown in the page header and browser tab titles |
| `MUSICBINGO_TAGLINE` | `All aboard!` | The line above "Join a game" on the page players open. Set it to empty to hide it |
| `MUSICBINGO_DATA_DIR` | `./data` | SQLite database (`bingo.db3`), uploaded clips, generated secret key |
| `MUSICBINGO_SECRET_KEY` | generated into `data/secret_key` | Signs session cookies |
| `MUSICBINGO_MAX_UPLOAD_MB` | `50` | Per-file upload limit |
| `MUSICBINGO_MAX_IMPORT_MB` | `300` | Largest game file (with audio) that can be imported |
| `MUSICBINGO_HTTPS_ONLY` | `0` | Set to `1` when served over HTTPS so cookies are marked Secure |
| `MUSICBINGO_PUBLIC_URL` | derived from the request | The address players use, e.g. `https://bingo.example.com`. Pins the join links shown in the console, which matters behind a proxy |
| `MUSICBINGO_PDF_FONT` | built-in font | Path to a `.ttf` so printed cards can show titles in other alphabets |
| `MUSICBINGO_PDF_FONT_BOLD` | same as above | Optional bold `.ttf` to go with it |

See [Backups](#backups) for how to back up safely.

The `MUSICBINGO_` prefix, the `.musicbingo.zip` game-file extension and the `musicbingo-backup-` file names
keep their original spelling on purpose, so existing settings, exported games and backups keep working
whatever the app is called.

## Running a game

1. **Library:** upload clips (type tags such as `80s, rock` in the upload form to tag every file in that
   upload) and set each song's start and end point. On the edit page, press play, watch the readout
   (position, time into the clip, time left), and use *Use current position* for the start or the end. With
   *Fill in the other end automatically* ticked (the default), capturing the start sets the end one clip
   length later, and capturing the end sets the start one clip length earlier. The default length is set on
   the Library page (30 seconds to begin with); the length box on the edit page is for that visit only, and
   the tick box is remembered per song, so a song that needs a different shape can opt out.
   The same fill-in happens when you type a time: type a start and the end appears one clip length later
   (or type an end and the start appears before it). A time you typed yourself is never overwritten; only a
   value that was filled in automatically follows when you change the other end.
2. **Games → New game:** choose the song pool, grid size and number of cards. Make at least as
   many cards as you expect teams. A pool of roughly twice the number of squares per card gives
   more varied cards, and the app tells you when cards end up closer than the 80% rule.
3. **Rounds:** the game starts with one round (one line, rows only). Add more on the game page, or
   from the console during play.
4. **Branding (optional):** open **Branding** in the menu to add a logo, an accent colour and your own
   header and footer wording. Use *Preview as a PDF* to see how it prints. It applies to all your games.
5. **Printed cards (optional):** on the game page choose paper size, orientation and cards per page
   (the default is one card per page, landscape), then download the PDF. Each card is numbered.
   Type a **footer line for this game's cards** (for example *Next week: 90s Night, Thursday 7pm*) and
   save it before downloading. It replaces the footer from your Branding page for this game only; leave it
   empty to use the Branding footer. A game started with *Run again* begins with an empty footer, so last
   week's announcement is never reprinted by accident. The footer is included in game exports.
6. **Console:** open the host console and share the join code or the `/join/CODE` link. Players
   enter a team name and get a card.
7. **Play:** press **Start game**, then **Next song** for each clip. The clip plays in the host's
   browser; players never see song titles, only their own card.
   The right-hand side of the console shows **Now playing and coming up** as one list, with the song on the
   speakers highlighted at the top, and a separate **Played** box beneath it.
8. **Claims:** when a team taps **Bingo!** the server checks it. The console lists every claim with
   the song count at the time, so ties are visible. A rejected claim has a short cooldown.
9. **Rounds:** after a win, press **Next round**, or change what counts as a win ("Change what
   counts as a win"). The same team can win several rounds.
10. **Paper cards:** type the card number into **Check a printed card** to see whether it wins the
   current round, and what it is still missing.
11. **Afterwards:** **End game**, then **Run this game again** from the game page.

### Phone remote

Open **Phone remote** on the console and press **Turn on the remote**. It shows a six-character code and
an address. On your phone, open that address (it ends in `/remote`), type the code, and you get a page
with a big **Next song** button, **Pause / Resume**, **Replay**, **Skip next**, **Start game**, **Next round**,
the sound effects, the current and next song, and a banner when a team calls a valid bingo.

How it works: the songs play on the host computer, so the phone can't play anything itself. It sends
each button press to the server, which passes it to the console window, and the console acts exactly as
if you had clicked. That means:

- **Keep the console window open** on the host computer. If it isn't, the phone says so and its buttons
  pause instead of silently doing nothing. Use only one console window.
- Browsers only allow sound after you have clicked something in the page. If a song doesn't start from the
  phone, click anywhere in the console window once.
- A tap that arrives late can't skip a song: **Next song** carries the song count the phone saw, and the
  server ignores it if the game has already moved on. Double taps on one button send once.
- The phone only gets what it needs: no playlist, team names or codes. Ending the game, rules and
  settings stay on the console.

Security: the code lets a phone drive *that one game's* console, nothing else; there is no access to your
account. Wrong guesses are limited (8 in 5 minutes per client address, so behind a reverse proxy make sure
`FORWARDED_ALLOW_IPS` is set, or every phone looks like the same client). **New code** or **Turn off**
disconnects every phone at once. The remote is off until you turn it on, for each game.

### Sound effects

The console has a **Sound effects** card with three built-in effects: **Thinking** (a ticking loop to play
while you check a claim), **Win** and **Lose**. Click one, or press its number key (1, 2, 3). Esc, or
pressing **Thinking** again, stops it. An effect pauses the current song and cancels any pending automatic
next song, so press Resume or Next song when you are ready to carry on. Effects play from the host's
computer, like the songs, so players hear them in the room.

The effects are original sounds synthesised by `scripts/generate_effects.py` (standard library only).
To change them, edit the notes there and run `uv run python scripts/generate_effects.py`; a test checks
that the committed files match the script. The console builds its buttons from the list in
`app/services/effects.py`, so offering more effects, or your own uploads, later means changing that list
rather than the page.

### Background music

Open **Background music** on the console (it starts collapsed) to play your library, shuffled (leaving out the songs in the current game), as
background music before the game or once it has ended. Tracks play in full, one after another, and the
list goes round again if it runs out. **Pause**, **Next track**, **Stop** and a volume slider (remembered
in that browser, 40% to start) are there too. Tick **Start background music when I end the game** if you
want it to begin by itself after **End game**.

Songs in the current game's playlist are left out, so you never spoil the game.

It is only available while a game is not running: when you press **Start game** the music eases out over
about a second and the controls lock, and starting a sound effect pauses it. Like everything else it plays
from the host's computer.

### Starting the game

**Start game** also plays the first song by default. Untick *Start game also plays the first song* on the
console (remembered in that browser) to start silently and press **Next song** yourself.

### Automatic next song and fades

In the console, tick **Play the next song automatically** and set how many seconds to wait after each
clip. Pressing Pause or Replay cancels the countdown, and a valid bingo holds auto-play until you
press **Next song**. **Fade in and out** ramps the volume over the clip's start and end points
(0 turns it off). These settings are remembered in that browser.

### Running a game again

A finished game's page has **Run this game again**: a new join code, the same songs and rounds, and
fresh teams. By default the cards are kept, so cards you printed earlier still work. Tick the box
to generate new cards instead. The games list shows each game once, as its latest run (with a
badge such as "run 3 of 3"); earlier runs are listed on the game page. Deleting the newest run
brings the previous one back to the list.

## Docker

```bash
docker compose up --build        # http://localhost:8000
```

The compose file keeps the database, clips and session key in a named volume (`bingo-data`) so they
survive rebuilds and upgrades. The image needs your `uv.lock` (run `uv sync` once and commit it) and
runs a single worker as an unprivileged user. For HTTPS behind a reverse proxy, set
`MUSICBINGO_HTTPS_ONLY=1` and `MUSICBINGO_PUBLIC_URL`, and set `FORWARDED_ALLOW_IPS` to the proxy's
address; see [Behind a reverse proxy](#behind-a-reverse-proxy). If you mount a folder from the host instead of the volume, make it writable by
uid 10001.

## Behind a reverse proxy

The app expects to be served at the **root** of its own host name (`https://bingo.example.com/`, not
`https://example.com/bingo/`), as a **single worker**. Everything else is about the proxy passing the
browser's view of the request through.

**What the proxy must do**

- Pass the original `Host` header, and send `X-Forwarded-For` and `X-Forwarded-Proto`.
- Not buffer responses: live updates are Server-Sent Events, and a buffering proxy stalls them.
- Allow large request bodies: song clips and game files can be tens of megabytes, and nginx's default
  limit (1 MB) rejects them.

**What to set on the app**

```bash
MUSICBINGO_HTTPS_ONLY=1                         # when the public address is https://
MUSICBINGO_PUBLIC_URL=https://bingo.example.com # so join links show the public address
FORWARDED_ALLOW_IPS=127.0.0.1                   # the proxy's address (uvicorn only trusts X-Forwarded-* from here)
```

`FORWARDED_ALLOW_IPS` defaults to `127.0.0.1`, which is right when the proxy runs on the same machine.
In Docker the proxy is a different address, so list it (`*` is acceptable only if the app's port is
reachable from the proxy alone and never from the internet).

**nginx**

```nginx
server {
    listen 443 ssl;
    server_name bingo.example.com;
    # ssl_certificate ...; ssl_certificate_key ...;

    client_max_body_size 300m;           # clips and game files; the default of 1m rejects uploads

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;                      # without this the app sees the upstream's name
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;                              # live updates are Server-Sent Events
        proxy_read_timeout 1h;
    }
}
```

**Caddy** (it sets the forwarding headers itself)

```
bingo.example.com {
    request_body {
        max_size 300MB
    }
    reverse_proxy 127.0.0.1:8000 {
        flush_interval -1
    }
}
```

**If something is wrong**, open the browser's developer tools (Console and Network tabs):

| Symptom | Cause and fix |
|---|---|
| CORS errors, or "blocked" requests, for `/static/*.js` or the stylesheet | The page is pointing at a different origin than the one you opened. Versions before this fix built asset URLs from the request's `Host` header, which breaks when the proxy doesn't pass the real one. Update; the app now uses plain paths. Also check `proxy_set_header Host $host` |
| "Mixed content" warnings | The proxy isn't sending `X-Forwarded-Proto: https`, or `FORWARDED_ALLOW_IPS` doesn't include the proxy's address |
| Join links show an internal address | Set `MUSICBINGO_PUBLIC_URL` |
| Live updates freeze, or the console says "Reconnecting" | The proxy is buffering. Turn buffering off for the app (`proxy_buffering off`) and lengthen the read timeout |
| "413 Request Entity Too Large" on upload or import | Raise the proxy's body limit (`client_max_body_size`) |
| You can log in on plain HTTP but not on HTTPS (or the reverse) | `MUSICBINGO_HTTPS_ONLY` must match how the site is really served |

## Backups

Don't just copy `bingo.db3` while the app is running: recent changes can still be in a side file.
Use the built-in tool, which is safe to run mid-game:

```bash
uv run python -m app.backup create --out backups --keep 14   # timestamped .tar.gz, newest 14 kept
uv run python -m app.backup restore backups/musicbingo-backup-<time>.tar.gz --data-dir data
```

A backup holds the database, the uploaded clips, card logos and the session key (so everyone stays logged in
after a restore). Treat it as sensitive and copy it off the machine. Restoring into a folder that
already has data needs `--force`, which moves the old data into a `before-restore-<time>` folder
instead of deleting it. In Docker:

```bash
docker compose exec musicbingo python -m app.backup create --out /data/backups --keep 14
docker compose cp musicbingo:/data/backups ./backups
```

To restore into a fresh container, copy the archive in with `docker compose cp` and run
`python -m app.backup restore <archive> --data-dir /data --force` inside it, then restart.

## Users and permissions

The first account, made on the `/setup` page, is an administrator. Administrators open **Users** in the
menu to:

- **Add an account.** A random password is generated and shown once, for you to pass on. The new user
  must choose their own at first login.
- **Set permissions.** *Can create games* covers creating, importing and running a game again;
  without it a user can still use the library and branding and run any existing game.
  *Administrator* lets a user manage accounts.
- **Reset a password** (a new temporary one is shown once and the user is signed out everywhere), or
  **disable** an account (it can't log in, and open sessions end). Accounts can't be deleted, so that the
  songs and games they own are never lost.

**Everything is shared.** Every account sees the same games, song library and branding, and can open,
run, print and edit any of them, so a second person can take over a game the first one set up. The one
restriction is deleting: a game or a song can be deleted only by the account that created it or by an
administrator.

The last active administrator can't be demoted or disabled, which keeps you from locking everyone out.
Anyone can change their own password from **Account** (their name in the header); that signs out their
other browsers. There is no email, so a forgotten password is reset by an administrator.

## Moving a game between installs

Open a game and use **Export this game**. You get one `.musicbingo.zip` file holding the songs'
details (title, artist, tags, start and end points), the rounds and the exact cards, with the audio
too if you choose. Teams and results are not included.

On the other install, use **Import a game** on the Games page. Songs already in that library are
recognised by their audio checksum and reused; the rest come from the file. The result is a new game
with a new join code and the same cards. If the file was exported without audio and a song is
missing from the library, the import stops with a message and creates nothing. Files are validated
strictly, so a damaged or hostile file is refused.

## Game night checklist

Before:

- [ ] Clips uploaded and their start/end points checked by ear
- [ ] Game created with enough cards; rounds set up (add a spare round or two)
- [ ] Cards printed from the PDF, if you are using paper
- [ ] Computer and phones on the same network; console opened by network address; join link tried on a phone
- [ ] Speakers connected and volume tested; one click on the console page done so the browser allows audio

During:

- [ ] Start game, then Next song (or turn on automatic next song)
- [ ] Valid bingo: check the claim, announce, then Next round (or change the rules)
- [ ] Paper claims: check the card number in the console
- [ ] If a clip doesn't start, press Replay

After:

- [ ] End game; run it again next time instead of building a new one

## Layout

```
app/
  main.py            app factory, error pages
  config.py          settings from environment variables
  backup.py          backup and restore (python -m app.backup)
  db.py, models.py   SQLite engine, tables, additive migrations
  security.py        password hashing, CSRF, safe redirects
  deps.py            require_user dependency
  web.py             template rendering, flash messages, error page
  routes/
    auth.py          first-run setup, login, logout, home page
    library.py       song library
    games.py         games, rounds, cards, PDF download, run again
    branding.py      card branding page, logo files, PDF preview
    users.py         user management and the Account page
    transfer.py      game export and import
    run.py           host console and its actions
    play.py          joining, marking, claiming (player side)
    remote.py        the phone remote: pairing and relaying commands
  services/          pure Python where possible (no web framework)
    patterns.py      what counts as a win
    checker.py       claim verification
    ticket_gen.py    card generation
    playlist.py      play order
    series.py        runs of the same game
    permissions.py   account rules
    effects.py       the list of sound effects offered in the console
    remote.py        pairing codes, command checking, the phone's view of the game
    gameio.py        the game export file format
    events.py        live-update hub (Server-Sent Events)
    snapshots.py     state sent to players and to the host
    pdf.py           printable cards (reportlab)
    branding.py      colours and logo processing (Pillow)
    brand_store.py   loads a host's branding for PDFs and pages
    clips.py         audio files and tags (mutagen)
    parsing.py       tags and time values
  templates/         Jinja pages
  static/            styles.css, plain ES modules (app, play, console, live, playback, branding),
                     effects/ (the built-in WAV sounds)
scripts/              generate_effects.py (rebuilds the built-in sounds)
tests/
Dockerfile, compose.yaml, .dockerignore
```

## Design notes

- **In-room audio:** only the host's browser plays audio. Players see cards, never titles.
- **One worker:** live updates are held in memory, and game actions rely on being handled one at a
  time by a single event loop. Run one `uvicorn` worker.
- **Live updates:** Server-Sent Events carry full state snapshots, so reconnecting always re-syncs.
- **Rules per round:** a win is decided by the round's rules at the moment of the claim, so changing
  them mid-game takes effect immediately.
- **Cards are data:** a card is a list of song ids, so reusing a game can keep printed cards valid.

## Deployment notes

- Behind a reverse proxy, set the request body limit at least as high as
  `MUSICBINGO_MAX_UPLOAD_MB`, and cap it so unauthenticated clients cannot send huge bodies.
- Run it in Docker with the included `Dockerfile` and `compose.yaml` (see above).
- See [Behind a reverse proxy](#behind-a-reverse-proxy) for working nginx and Caddy settings.
- There is no login rate limiting yet; put the app behind something that provides it if it is exposed
  to the internet.
- Join links use `MUSICBINGO_PUBLIC_URL` if set, otherwise the address the console was opened from.

## Upgrading

New tables are created on start-up. Columns added to existing tables since the first release
(`game.current_round`, `game.series_id`, `game.run_number`, `game.remote_code`, the account flags on `user`, `song.sha256`) are added by a small built-in migration,
so an existing `data/bingo.db3` keeps working. Add Alembic before real users depend on the data.

## Known limitations

- A team is tied to the browser it joined from (a signed cookie). Reopening the join link in the same
  browser resumes the team; another browser joins as a new team.
- Fades use the browser's volume control, which iPhones and iPads ignore. Use a laptop as the host.
- Browsers may block audio until the page has been clicked. If a clip doesn't start, press Replay.
- Printed cards use a built-in font that covers Western European text. Other alphabets print as `?`
  unless you set `MUSICBINGO_PDF_FONT`.
- The phone remote needs the console window to stay open on the host computer, and its pairing is per game.
- Accounts can be disabled but not deleted, and there is no email-based password recovery.
- A song that is in a game's pool can't be deleted from the library until that game is deleted.
  Rounds that have been played, or are in play, can't be deleted.
- Branding is shared by every account and applies to all games. Logos are shrunk to
  at most 600 pixels, and the PDF header and footer text use the same built-in font as the cards.
- Grids larger than about 6×6 are cramped on a phone.

## Possible next steps

From the "Later" list in PLAN.md: game import/export, a permissions model for multiple hosts,
sound effects the host can trigger (thinking music, win and lose sounds), music before and after
the game, and a phone remote for the host.

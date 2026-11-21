"""Playlist planner: check a spreadsheet of songs against the library, tag the ones already there, and
list the ones still to get. Nothing is saved except the tags the person chooses to add."""

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlmodel import Session, select

from app.db import get_session
from app.deps import require_user
from app.models import Game, GameSong, Song, User
from app.security import check_csrf
from app.services.planner import (
    DEFAULT_OVERUSE, HAVE, MAYBE, NEED, ROLES, LibSong, add_tag, build_rows, guess_mapping, match_rows,
    owned_list, shopping_list, summarize,
)
from app.services.sheets import (
    MAX_COLUMNS, MAX_UPLOAD_BYTES, SheetError, rows_from_text, rows_from_upload, template_csv, template_xlsx,
)
from app.web import flash, render

router = APIRouter(prefix="/planner")


def _library(session: Session) -> list[LibSong]:
    """Every song, with how many games it has been in and the most recent one."""
    used: dict[int, list[tuple]] = {}
    for song_id, game_id, name, created in session.exec(
        select(GameSong.song_id, Game.id, Game.name, Game.created_at)
        .select_from(GameSong).join(Game, Game.id == GameSong.game_id)
    ).all():
        used.setdefault(song_id, []).append((created, game_id, name))
    songs = []
    for song in session.exec(select(Song).order_by(Song.id)).all():
        games = sorted(used.get(song.id, []), key=lambda g: g[0])
        entry = LibSong(song.id, song.title, song.artist, song.tags, uses=len(games))
        if games:
            entry.last_used, entry.last_game = games[-1][0], games[-1][2]
        songs.append(entry)
    return songs


def _usage_text(song: LibSong) -> str:
    if not song.uses:
        return "not used in a game yet"
    when = f"{song.last_used:%b} {song.last_used.day}, {song.last_used.year}" if song.last_used else ""
    return f"used in {song.uses} game{'s' if song.uses != 1 else ''}, last “{song.last_game}” {when}".strip()


label = {HAVE: "In library", MAYBE: "Close match", ARTIST: "By the artist"}


def _csv(items: list[tuple], header=("Artist", "Song", "Note"), filename="songs-to-get.csv") -> Response:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows(items)
    return Response("\ufeff" + out.getvalue(), media_type="text/csv; charset=utf-8",  # the BOM makes Excel read accents correctly
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("")
def planner_page(request: Request, user: User = Depends(require_user)):
    return render(request, "planner.html", user=user, results=None, overuse=DEFAULT_OVERUSE, tag="")


@router.get("/template.csv")
def template_csv_file(user: User = Depends(require_user)):
    return Response(template_csv(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="playlist-template.csv"'})


@router.get("/template.xlsx")
def template_xlsx_file(user: User = Depends(require_user)):
    return Response(template_xlsx(), headers={
        "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "Content-Disposition": 'attachment; filename="playlist-template.xlsx"'})


def _int(text: object, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(str(text))))
    except ValueError:
        return default


@router.post("")
async def check(request: Request, user: User = Depends(require_user), session: Session = Depends(get_session)):
    form = await request.form()
    check_csrf(request, str(form.get("csrf_token", "")))
    action = str(form.get("action", "check"))
    if action not in ("check", "tag", "csv", "csv_library"):
        raise HTTPException(status_code=400, detail="Unknown action")
    overuse = _int(form.get("overuse"), DEFAULT_OVERUSE, 1, 99)
    tag = " ".join(str(form.get("tag", "")).split())[:40]

    # The sheet: a newly pasted or uploaded one replaces the one carried along from the last check.
    fresh = True
    rows: list[list[str]] = []
    try:
        upload = form.get("sheet")
        pasted = str(form.get("pasted", ""))
        if upload is not None and getattr(upload, "filename", "") and action == "check":
            data = await upload.read(MAX_UPLOAD_BYTES + 1)
            rows = rows_from_upload(upload.filename, data)
        elif pasted.strip() and action == "check":
            rows = rows_from_text(pasted[:200_000])
        else:
            fresh = False
            rows = rows_from_text(str(form.get("raw", ""))[:400_000])
    except SheetError as exc:
        flash(request, str(exc), "error")
        return render(request, "planner.html", user=user, results=None, overuse=overuse, tag=tag, status_code=400)
    if not rows:
        flash(request, "Paste your songs, or choose a file, to check them against the library.", "error")
        return render(request, "planner.html", user=user, results=None, overuse=overuse, tag=tag, status_code=400)

    library = _library(session)
    guessed_roles, guessed_header = guess_mapping(rows, library)
    width = len(rows[0])
    if fresh:
        roles, header = guessed_roles, guessed_header
    else:
        roles = [str(form.get(f"role_{i}", guessed_roles[i])) for i in range(width)]
        roles = [r if r in ROLES else "ignore" for r in roles]
        header = form.get("has_header") == "1"

    if action == "tag":
        known = {s.id: s for s in session.exec(select(Song)).all()}
        ids = {int(i) for i in form.getlist("song_ids") if str(i).isdigit()}
        changed = full = 0
        for song_id in ids & set(known):
            song = known[song_id]
            updated = add_tag(song.tags, tag)
            if updated is None:
                full += 1 if tag else 0
            elif updated != song.tags:
                song.tags = updated
                session.add(song)
                changed += 1
        if not tag:
            flash(request, "Type the tag to add first.", "error")
        elif not ids:
            flash(request, "Tick the songs to tag first.", "error")
        else:
            session.commit()
            msg = f"Added the tag “{tag.lower()}” to {changed} song{'s' if changed != 1 else ''}."
            if full:
                msg += f" {full} already had the maximum number of tags."
            flash(request, msg, "success")
        library = _library(session)

    results = match_rows(build_rows(rows, roles, header), library, overuse)
    if action == "csv":
        return _csv(shopping_list(results))
    owned = owned_list(results)
    if action == "csv_library":
        return _csv([(s.artist, s.title, ", ".join(s.tag_list), s.uses, label[status]) for s, status in owned],
                    header=("Artist", "Song", "Tags", "Games used", "Status"), filename="songs-in-library.csv")

    columns = [
        {"index": i, "letter": chr(65 + i), "role": roles[i],
         "sample": [r[i] for r in rows[(1 if header else 0):] if r[i]][:3]}
        for i in range(width)
    ]
    return render(
        request, "planner.html", user=user, results=results, summary=summarize(results), columns=columns,
        header=header, raw="\n".join("\t".join(r) for r in rows), overuse=overuse, tag=tag,
        usage={s.id: _usage_text(s) for r in results for s in [m.song for m in r.matches] + r.alternatives},
        needs=shopping_list(results), owned=owned, guessed=fresh, row_count=len(rows),
    )

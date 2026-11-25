"""Song library: upload, search, edit metadata and play window, delete, stream audio."""

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from sqlalchemy import func, or_
from sqlmodel import Session, select
from starlette.concurrency import run_in_threadpool

from app.db import get_session
from app.deps import require_user
from app.models import Game, GameSong, Plan, Song, Ticket, User, utcnow
from app.security import check_csrf
from app.services.clips import (
    ALLOWED_TYPES,
    InvalidAudio,
    UploadTooLarge,
    extension_of,
    new_stored_name,
    probe,
    save_upload,
    write_tags,
)
from app.services.duplicates import SAME_FILE, Entry, describe, duplicate_groups, find_duplicate
from app.services.merge import Info, blocking_games, choose_keeper, merged_values, remap_choices, remap_ids
from app.services.gameio import sha256_file
from app.services.loudness import describe as describe_volume, parse_adjust, parse_loudness, playback_gain_db, window_key
from app.services.paging import PER_PAGE_OPTIONS, clean_page, clean_per_page, page_links, paginate
from app.services.search import SHOWS, SORTS, filter_show, has_window, matches, parse_query, sort_songs
from app.services.parsing import MAX_FUN_FACT, clean_fun_fact, format_time_ms, normalize_tags, parse_time_ms
from app.services.settings_store import (
    get_clip_seconds, get_library_view, parse_clip_seconds, set_clip_seconds, set_library_view,
)
from app.web import flash, render

router = APIRouter(prefix="/library")

MAX_TEXT = 200
DURATION_SLACK_MS = 1000  # VBR MP3 durations are estimates


def _library_url(q: str, song_id: int | None = None, page: object = 1) -> str:
    """The library page as the person left it (their search and page; only ever those, never a free-form address),
    scrolled to the song just edited, or to the song list when there is no such song."""
    q, page = q.strip()[:100], clean_page(page)
    params = ([f"q={quote(q)}"] if q else []) + ([f"page={page}"] if page > 1 else [])
    anchor = f"#song-{song_id}" if song_id else "#songs"
    return "/library" + (f"?{'&'.join(params)}" if params else "") + anchor


def _carry(q: str, page: object) -> str:
    """The query-string part that lets an edit page find its way back: the search and the page."""
    q, page = q.strip()[:100], clean_page(page)
    return "&".join(([f"q={quote(q)}"] if q else []) + ([f"page={page}"] if page > 1 else []))


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def owned_song(session: Session, user: User, song_id: int) -> Song:
    """Any signed-in host can use and edit any song: the library is shared."""
    song = session.get(Song, song_id)
    if song is None:
        raise HTTPException(status_code=404, detail="Song not found")
    return song


def _clip_path(request: Request, song: Song) -> Path:
    return request.app.state.settings.clips_dir / song.filename


@router.get("")
def library(
    request: Request,
    q: str = "",
    sort: str = "",
    show: str = "",
    page: str = "",
    per_page: str = "",
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    # The order, the play-window filter and the page size are remembered per person: choosing one saves it, and a
    # visit with nothing chosen (after an edit, say) uses what was chosen last.
    saved_sort, saved_show, saved_per = get_library_view(session, user.id)
    chosen_sort = sort if sort in SORTS else saved_sort
    chosen_show = show if show in SHOWS else saved_show
    chosen_per = clean_per_page(per_page, saved_per)
    if (chosen_sort, chosen_show, chosen_per) != (saved_sort, saved_show, saved_per):
        set_library_view(session, user.id, chosen_sort, chosen_show, chosen_per)
    everything = session.exec(select(Song)).all()
    songs = everything
    query = parse_query(q)
    if not query.empty:  # filtered here rather than in SQL: a library is a few thousand rows at most
        songs = [song for song in songs if matches(query, song.title, song.artist, song.tags)]
    songs = sort_songs(filter_show(songs, chosen_show), chosen_sort)
    pg = paginate(len(songs), clean_page(page), chosen_per)

    def page_url(n: int) -> str:
        return "/library" + (f"?{_carry(q, n)}" if _carry(q, n) else "") + "#songs"

    return render(
        request, "library.html", user=user, songs=songs[pg.start:pg.stop], q=q.strip(), clip_seconds=get_clip_seconds(session),
        sorts=SORTS, shows=SHOWS, sort=chosen_sort, show=chosen_show, has_window=has_window,
        total=len(everything), with_window=sum(has_window(s) for s in everything),
        pg=pg, links=page_links(pg.page, pg.pages), page_url=page_url, per_pages=PER_PAGE_OPTIONS,
        per_page=chosen_per, carry=_carry(q, pg.page), page_no=pg.page, matching=pg.total,
    )


@router.post("/clip-length")
def set_default_clip_length(
    request: Request,
    clip_seconds: str = Form(""),
    csrf_token: str = Form(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    """The default clip length used to fill in the other end of a song's play window."""
    check_csrf(request, csrf_token)
    try:
        seconds = parse_clip_seconds(clip_seconds)
    except ValueError as exc:
        flash(request, str(exc), "error")
        return _redirect("/library")
    set_clip_seconds(session, seconds)
    flash(request, f"Default clip length set to {seconds} seconds.", "success")
    return _redirect("/library")


@router.post("/upload")
async def upload(
    request: Request,
    files: list[UploadFile] = File(default=[]),
    tags: str = Form(""),
    plan_id: str = Form(""),
    csrf_token: str = Form(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    check_csrf(request, csrf_token)
    settings = request.app.state.settings
    plan = session.get(Plan, int(plan_id)) if plan_id.strip().isdigit() else None  # an upload made from a saved plan
    upload_tags = normalize_tags(f"{tags},{plan.tag}" if plan and plan.tag else tags)  # applied to every song in this upload
    back = f"/planner/plans/{plan.id}" if plan else "/library"
    added = 0
    problems: list[str] = []
    warnings: list[str] = []
    known = [Entry(i, t, a, h) for i, t, a, h in session.exec(select(Song.id, Song.title, Song.artist, Song.sha256)).all()]
    for upload_file in files:
        name = Path(upload_file.filename or "").name
        if not name:  # browsers send an empty part when no file was chosen
            continue
        ext = extension_of(name)
        if ext not in ALLOWED_TYPES:
            problems.append(f"{name}: only MP3 and Ogg files are supported")
            continue
        stored = new_stored_name(ext)
        dest = settings.clips_dir / stored
        try:
            await save_upload(upload_file, dest, settings.max_upload_bytes)
            info = await run_in_threadpool(probe, dest)
        except UploadTooLarge:
            problems.append(f"{name}: larger than {settings.max_upload_bytes // (1024 * 1024)} MB")
            continue
        except InvalidAudio as exc:
            dest.unlink(missing_ok=True)
            problems.append(f"{name}: {exc}")
            continue
        digest = await run_in_threadpool(sha256_file, dest)
        title = (info.title or Path(name).stem)[:MAX_TEXT]
        artist = info.artist[:MAX_TEXT]
        found = find_duplicate(title, artist, digest, known)
        if found:  # still added (it might be a different recording), but say so
            warnings.append(f"{name} {describe(*found)}, which is already in the library.")
        known.append(Entry(0, title, artist, digest))
        session.add(
            Song(
                owner_id=user.id,
                filename=stored,
                original_name=name,
                title=title,
                artist=artist,
                tags=upload_tags,
                duration_ms=info.duration_ms,
                sha256=digest,
            )
        )
        added += 1
    session.commit()
    if added:
        flash(request, f"Added {added} song{'s' if added != 1 else ''}.", "success")
    for problem in problems[:4]:
        flash(request, problem, "error")
    for warning in warnings[:4]:
        flash(request, warning, "info")
    if len(warnings) > 4:
        flash(request, f"{len(warnings) - 4} more possible duplicates. See Find duplicates on the Library page.", "info")
    elif warnings:
        flash(request, "Added anyway. Use Find duplicates on the Library page to review or delete copies.", "info")
    if not added and not problems:
        flash(request, "Choose at least one file to upload.", "error")
    if request.headers.get("x-requested-with") == "xhr":  # the progress-bar upload; the messages above show on the next page
        return JSONResponse({"redirect": back})
    return _redirect(back)


def _form_values(song: Song) -> dict[str, str]:
    return {
        "title": song.title,
        "artist": song.artist,
        "tags": ", ".join(song.tag_list),
        "fun_fact": song.fun_fact,
        "start": format_time_ms(song.start_ms) if song.start_ms else "",
        "end": format_time_ms(song.end_ms),
        "auto_fill": song.auto_fill,
        "volume_adjust": f"{song.volume_adjust_db:g}" if song.volume_adjust_db else "",
    }


@router.post("/{song_id}/loudness")
def save_loudness(request: Request, song_id: int, loudness: str = Form(""), start_ms: str = Form(""), end_ms: str = Form(""),
                  csrf_token: str = Form(""), user: User = Depends(require_user), session: Session = Depends(get_session)):
    """Store a loudness measurement made in the browser, for the clip window it was made over."""
    check_csrf(request, csrf_token)
    song = owned_song(session, user, song_id)
    try:
        value = parse_loudness(loudness)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if f"{start_ms}:{end_ms}" != window_key(song.start_ms, song.end_ms):
        raise HTTPException(status_code=409, detail="The clip times changed while it was being measured. Measure it again.")
    song.loudness_db, song.loudness_for = value, window_key(song.start_ms, song.end_ms)
    session.add(song)
    session.commit()
    return {"loudness_db": value, "gain_db": playback_gain_db(song), "text": describe_volume(song)}


@router.get("/{song_id}/edit")
def edit_form(
    request: Request,
    song_id: int,
    q: str = "",
    page: str = "",
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    song = owned_song(session, user, song_id)
    return render(request, "edit_song.html", user=user, song=song, form=_form_values(song), errors=[],
                  clip_seconds=get_clip_seconds(session), q=q.strip()[:100], page=clean_page(page), volume_text=describe_volume(song),
                  back_url=_library_url(q, song.id, page))


@router.post("/{song_id}/edit")
async def edit_submit(
    request: Request,
    song_id: int,
    title: str = Form(""),
    artist: str = Form(""),
    tags: str = Form(""),
    start: str = Form(""),
    end: str = Form(""),
    write_tags_to_file: bool = Form(False),
    auto_fill: bool = Form(False),
    fun_fact: str = Form(""),
    volume_adjust: str = Form(""),
    q: str = Form(""),
    page: str = Form(""),
    csrf_token: str = Form(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    check_csrf(request, csrf_token)
    song = owned_song(session, user, song_id)
    title, artist = title.strip(), artist.strip()
    fun_fact = clean_fun_fact(fun_fact)
    errors: list[str] = []
    if len(fun_fact) > MAX_FUN_FACT:
        errors.append(f"The fun fact can be at most {MAX_FUN_FACT} characters.")
    if not title:
        errors.append("Title is required.")
    if len(title) > MAX_TEXT or len(artist) > MAX_TEXT:
        errors.append(f"Title and artist must be at most {MAX_TEXT} characters.")

    adjust_db = 0.0
    try:
        adjust_db = parse_adjust(volume_adjust)
    except ValueError as exc:
        errors.append(str(exc))

    start_ms: int | None = 0
    end_ms: int | None = None
    try:
        start_ms = parse_time_ms(start) or 0
    except ValueError as exc:
        errors.append(f"Start: {exc}.")
    try:
        end_ms = parse_time_ms(end)
    except ValueError as exc:
        errors.append(f"End: {exc}.")
    if not errors:
        if end_ms is not None and end_ms <= start_ms:
            errors.append("End must be after start.")
        if song.duration_ms is not None:
            if start_ms >= song.duration_ms:
                errors.append("Start is beyond the end of the track.")
            if end_ms is not None and end_ms > song.duration_ms + DURATION_SLACK_MS:
                errors.append("End is beyond the end of the track.")

    if errors:
        form = {"title": title, "artist": artist, "tags": tags, "start": start, "end": end, "auto_fill": auto_fill,
                "fun_fact": fun_fact, "volume_adjust": volume_adjust}
        return render(
            request, "edit_song.html", status_code=400, user=user, song=song, form=form, errors=errors,
            clip_seconds=get_clip_seconds(session), q=q.strip()[:100], page=clean_page(page), volume_text=describe_volume(song),
            back_url=_library_url(q, song.id, page),
        )

    if write_tags_to_file:
        try:
            await run_in_threadpool(write_tags, _clip_path(request, song), title, artist)
        except Exception:  # keep the database edit even if the file can't be retagged
            flash(request, "Saved, but the tags inside the audio file could not be updated.", "error")

    if write_tags_to_file:
        song.sha256 = ""  # the file's bytes changed; the checksum is refreshed when next needed
    song.title, song.artist = title, artist
    song.tags = normalize_tags(tags)
    song.start_ms, song.end_ms = start_ms, end_ms
    song.auto_fill = auto_fill
    song.fun_fact = fun_fact
    song.volume_adjust_db = adjust_db
    song.updated_at = utcnow()
    session.add(song)
    session.commit()
    flash(request, f"Saved \u201c{song.title}\u201d.", "success")
    return _redirect(_library_url(q, song.id, page))


def _pools(session: Session) -> dict[int, set[int]]:
    pools: dict[int, set[int]] = {}
    for game_id, song_id in session.exec(select(GameSong.game_id, GameSong.song_id)).all():
        pools.setdefault(game_id, set()).add(song_id)
    return pools


def _infos(songs, pools: dict[int, set[int]]) -> list[Info]:
    used: dict[int, int] = {}
    for pool in pools.values():
        for song_id in pool:
            used[song_id] = used.get(song_id, 0) + 1
    return [Info(s.id, s.tags, s.artist, s.fun_fact, s.start_ms, s.end_ms, used.get(s.id, 0)) for s in songs]


def _combined(songs, keeper_id: int, pools: dict[int, set[int]]) -> dict:
    """What the kept song would hold after the others are folded into it."""
    infos = _infos(songs, pools)
    return merged_values(next(i for i in infos if i.id == keeper_id), [i for i in infos if i.id != keeper_id])


def _merge_problem(session: Session, user: User, songs: list[Song], pools: dict[int, set[int]]) -> str | None:
    """Why these songs can't be merged right now, or None."""
    blocked = blocking_games(pools, {s.id for s in songs})
    if blocked:
        names = [g.name for g in session.exec(select(Game).where(Game.id.in_(blocked[:3]))).all()]
        listed = ", ".join(f"\u201c{n}\u201d" for n in names) + (f" and {len(blocked) - 3} more" if len(blocked) > 3 else "")
        return f"Two of these songs are in the same game ({listed}), and a card can't hold a song twice. Take one out of that game first."
    return None


def _merge_songs(request: Request, session: Session, user: User, ids: list[int], keeper_id: int) -> tuple[bool, str]:
    """Fold the other songs into the keeper. Returns (done, message). Nothing changes unless it all can."""
    songs = session.exec(select(Song).where(Song.id.in_(ids))).all()
    by_id = {s.id: s for s in songs}
    if len(by_id) < 2 or keeper_id not in by_id:
        return False, "Choose the songs to merge, and which one to keep."
    keeper = by_id[keeper_id]
    others = [s for s in songs if s.id != keeper_id]
    for song in others:
        if not (user.is_admin or song.owner_id == user.id):
            return False, f"Only the person who uploaded \u201c{song.title}\u201d, or an administrator, can merge it away."
    pools = _pools(session)
    problem = _merge_problem(session, user, songs, pools)
    if problem:
        return False, problem

    mapping = {o.id: keeper.id for o in others}
    games_touched = [g for g, pool in pools.items() if pool & set(mapping)]
    for row in session.exec(select(GameSong).where(GameSong.song_id.in_(list(mapping)))).all():
        session.delete(row)
        session.add(GameSong(game_id=row.game_id, song_id=keeper.id))
    if games_touched:
        for ticket in session.exec(select(Ticket).where(Ticket.game_id.in_(games_touched))).all():
            new_cells = remap_ids(list(ticket.cells), mapping)
            if new_cells != list(ticket.cells):
                ticket.cells = new_cells
                session.add(ticket)
        for game in session.exec(select(Game).where(Game.id.in_(games_touched))).all():
            new_order = remap_ids(list(game.play_order), mapping)
            if new_order != list(game.play_order):
                game.play_order = new_order
                session.add(game)
    for plan in session.exec(select(Plan)).all():
        updated = remap_choices(plan.choices_json, mapping)
        if updated != plan.choices_json:
            plan.choices_json = updated
            session.add(plan)

    values = _combined([keeper] + others, keeper.id, pools)
    keeper.tags, keeper.artist, keeper.fun_fact = values["tags"], values["artist"], values["fun_fact"]
    keeper.start_ms, keeper.end_ms = values["start_ms"], values["end_ms"]
    keeper.updated_at = utcnow()
    session.add(keeper)
    files = [_clip_path(request, o) for o in others]
    for song in others:
        session.delete(song)
    session.commit()
    for path in files:
        path.unlink(missing_ok=True)
    detail = f" {len(games_touched)} game{'s' if len(games_touched) != 1 else ''} now use{'s' if len(games_touched) == 1 else ''} it." if games_touched else ""
    return True, f"Merged {len(others) + 1} songs into \u201c{keeper.title}\u201d.{detail}"


@router.get("/duplicates")
def duplicates_page(request: Request, user: User = Depends(require_user), session: Session = Depends(get_session)):
    songs = {s.id: s for s in session.exec(select(Song)).all()}
    entries = [Entry(s.id, s.title, s.artist, s.sha256) for s in songs.values()]
    pools = _pools(session)
    used = {sid: n for sid, n in session.exec(select(GameSong.song_id, func.count()).group_by(GameSong.song_id)).all()}
    groups = []
    for g in duplicate_groups(entries):
        members = [songs[e.id] for e in g.entries]
        keeper = choose_keeper(_infos(members, pools))
        problem = _merge_problem(session, user, members, pools)
        if not problem:
            lacking = [s.title for s in members if s.id != keeper and not (user.is_admin or s.owner_id == user.id)]
            problem = f"You can only merge songs you uploaded (or be an administrator): {lacking[0]}." if lacking else None
        groups.append({"kind": g.kind, "songs": members, "keeper": keeper, "problem": problem,
                       "tags": _combined(members, keeper, pools)["tags"]})
    mergeable_files = sum(1 for g in groups if g["kind"] == SAME_FILE and not g["problem"])
    return render(request, "duplicates.html", user=user, groups=groups, used=used, mergeable_files=mergeable_files)


@router.post("/duplicates/merge")
async def merge_group(request: Request, user: User = Depends(require_user), session: Session = Depends(get_session)):
    form = await request.form()
    check_csrf(request, str(form.get("csrf_token", "")))
    try:
        ids = [int(v) for v in form.getlist("ids")]
        keeper_id = int(str(form.get("keeper_id", "")))
    except ValueError:
        flash(request, "Choose the song to keep.", "error")
        return _redirect("/library/duplicates")
    done, message = _merge_songs(request, session, user, list(dict.fromkeys(ids)), keeper_id)
    flash(request, message, "success" if done else "error")
    return _redirect("/library/duplicates")


@router.post("/duplicates/merge-all")
async def merge_all_identical(request: Request, user: User = Depends(require_user), session: Session = Depends(get_session)):
    """Merge every group of byte-for-byte identical files into the song that is best to keep. Groups that can't be
    merged (a game holds two of them, or the songs belong to someone else) are left alone and counted."""
    form = await request.form()
    check_csrf(request, str(form.get("csrf_token", "")))
    songs = {s.id: s for s in session.exec(select(Song)).all()}
    entries = [Entry(s.id, s.title, s.artist, s.sha256) for s in songs.values()]
    merged = skipped = 0
    for group in duplicate_groups(entries):
        if group.kind != SAME_FILE:
            continue
        pools = _pools(session)
        ids = [e.id for e in group.entries]
        keeper = choose_keeper(_infos([songs[i] for i in ids], pools))
        done, _ = _merge_songs(request, session, user, ids, keeper)
        merged, skipped = merged + done, skipped + (not done)
    if not merged and not skipped:
        flash(request, "There were no identical files to merge.", "info")
    else:
        text = f"Merged {merged} group{'s' if merged != 1 else ''} of identical files."
        if skipped:
            text += f" Left {skipped} alone (a game holds two of the copies, or they belong to someone else)."
        flash(request, text, "success" if merged else "error")
    return _redirect("/library/duplicates")


@router.post("/{song_id}/delete")
def delete_song(
    request: Request,
    song_id: int,
    q: str = Form(""),
    page: str = Form(""),
    back: str = Form(""),
    csrf_token: str = Form(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    check_csrf(request, csrf_token)
    song = owned_song(session, user, song_id)
    target = "/library/duplicates" if back == "duplicates" else _library_url(q, page=page)  # the page the delete was made from
    if not (user.is_admin or song.owner_id == user.id):
        flash(request, "Only the person who uploaded a song, or an administrator, can delete it.", "error")
        return _redirect(target)
    used_in = session.exec(
        select(Game.name).join(GameSong, GameSong.game_id == Game.id).where(GameSong.song_id == song.id)
    ).all()
    if used_in:
        names = ", ".join(f"\u201c{name}\u201d" for name in list(dict.fromkeys(used_in))[:3])
        flash(request, f"Can't delete \u201c{song.title}\u201d: it is in the song pool of {names}. Delete those games first.", "error")
        return _redirect(target)
    _clip_path(request, song).unlink(missing_ok=True)
    session.delete(song)
    session.commit()
    flash(request, "Song deleted.", "success")
    return _redirect(target)


@router.get("/{song_id}/audio")
def audio(
    request: Request,
    song_id: int,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    """Stream the clip. FileResponse handles HTTP Range, so seeking and preload work."""
    song = owned_song(session, user, song_id)
    path = _clip_path(request, song)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Audio file is missing")
    return FileResponse(path, media_type=ALLOWED_TYPES[path.suffix.lower()])

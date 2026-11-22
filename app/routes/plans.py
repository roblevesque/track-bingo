"""Saved playlist plans: a sheet kept in the app that checks itself against the library every time it is opened,
so songs uploaded later tick themselves off, and that can turn the finished list into a game."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlmodel import Session, select
from starlette.concurrency import run_in_threadpool

from app.db import get_session
from app.deps import require_game_creator, require_user
from app.models import Game, GameSong, Plan, Round, Song, Ticket, User, utcnow
from app.routes.games import (
    DEFAULT_GRID, DEFAULT_TICKETS, MAX_GRID, MAX_TICKETS, MIN_GRID, _new_code, can_delete,
)
from app.routes.planner import _csv, _int, _library
from app.security import check_csrf
from app.services.parsing import normalize_tags
from app.services.plans import (
    NEED, NONE_CHOICE, PICK, dump_choices, dump_skipped, load_choices, load_skipped, plan_rows_of,
    progress, ready_songs, resolve, to_get,
)
from app.services.planner import DEFAULT_OVERUSE, ROLES, add_tag, guess_mapping
from app.services.sheets import MAX_UPLOAD_BYTES, SheetError, rows_from_text, rows_from_upload
from app.services.ticket_gen import TicketGenerationError, generate_tickets, variety_warning
from app.web import flash, render

router = APIRouter(prefix="/planner/plans")


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def _plan(session: Session, plan_id: int) -> Plan:
    plan = session.get(Plan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan


def _theme_tag(text: object) -> str:
    return normalize_tags(str(text or "")[:60]).split(",")[0][:40]


def _items(plan: Plan, library):
    rows = plan_rows_of(plan.raw, plan.roles, plan.has_header, rows_from_text)
    return resolve(rows, library, plan.overuse, load_choices(plan.choices_json), load_skipped(plan.skipped_json))


def _tab(form) -> str:
    """Where to land after changing a line: the tab the person was working in."""
    tab = str(form.get("tab", ""))
    return f"#panel-{tab}" if tab in ("get", "confirm", "ready", "dropped") else ""


def _touch(session: Session, plan: Plan) -> None:
    plan.updated_at = utcnow()
    session.add(plan)
    session.commit()


@router.get("")
def plan_list(request: Request, user: User = Depends(require_user), session: Session = Depends(get_session)):
    library = _library(session)
    plans = session.exec(select(Plan).order_by(Plan.updated_at.desc())).all()
    rows = [{"plan": p, "progress": progress(_items(p, library))} for p in plans]
    return render(request, "plans.html", user=user, plans=rows)


@router.post("/save")
async def save_plan(request: Request, user: User = Depends(require_user), session: Session = Depends(get_session)):
    """Keep the sheet just checked (carried in the planner form) as a plan."""
    form = await request.form()
    check_csrf(request, str(form.get("csrf_token", "")))
    name = " ".join(str(form.get("plan_name", "")).split())[:100]
    raw = str(form.get("raw", ""))[:400_000]
    try:
        rows = rows_from_text(raw)
    except SheetError as exc:
        flash(request, str(exc), "error")
        return _redirect("/planner")
    if not name:
        flash(request, "Give the plan a name to save it.", "error")
        return _redirect("/planner")
    if not rows:
        flash(request, "There is nothing on the sheet to save.", "error")
        return _redirect("/planner")
    width = len(rows[0])
    roles = [str(form.get(f"role_{i}", "ignore")) for i in range(width)]
    roles = [r if r in ROLES else "ignore" for r in roles]
    plan = Plan(
        owner_id=user.id, name=name, tag=_theme_tag(form.get("tag", "")), raw=raw, roles=",".join(roles),
        has_header=form.get("has_header") == "1", overuse=_int(form.get("overuse"), DEFAULT_OVERUSE, 1, 99),
    )
    session.add(plan)
    session.commit()
    flash(request, f"Saved the plan “{name}”. It will keep itself up to date as you add songs.", "success")
    return _redirect(f"/planner/plans/{plan.id}")


@router.get("/{plan_id}")
def plan_detail(request: Request, plan_id: int, user: User = Depends(require_user), session: Session = Depends(get_session)):
    plan = _plan(session, plan_id)
    library = _library(session)
    items = _items(plan, library)
    game = session.get(Game, plan.game_id) if plan.game_id else None
    ready = ready_songs(items)
    return render(
        request, "plan.html", user=user, plan=plan, items=items, progress=progress(items), ready=ready,
        needs=to_get(items), game=game, can_remove=can_delete(user, plan.owner_id),
        default_grid=DEFAULT_GRID, default_cards=DEFAULT_TICKETS, min_grid=MIN_GRID, max_grid=MAX_GRID,
        max_cards=MAX_TICKETS, tagged_count=sum(plan.tag in s.tag_list for s in ready) if plan.tag else 0,
        usage_note={s.id: (f"used in {s.uses} game{'s' if s.uses != 1 else ''}" if s.uses else "not used yet")
                    for i in items for s in i.candidates + ([i.song] if i.song else [])},
    )


@router.get("/{plan_id}/songs-to-get.csv")
def to_get_csv(plan_id: int, user: User = Depends(require_user), session: Session = Depends(get_session)):
    plan = _plan(session, plan_id)
    items = _items(plan, _library(session))
    return _csv(to_get(items), filename="songs-to-get.csv")


@router.post("/{plan_id}/row")
async def change_row(request: Request, plan_id: int, user: User = Depends(require_user), session: Session = Depends(get_session)):
    """Decide a line: use a library song, use none of them, go back to the planner's choice, drop it or bring it back."""
    form = await request.form()
    check_csrf(request, str(form.get("csrf_token", "")))
    plan = _plan(session, plan_id)
    key = str(form.get("key", ""))[:400]
    action = str(form.get("action", ""))
    choices, skipped = load_choices(plan.choices_json), load_skipped(plan.skipped_json)
    if action == "use":
        song_id = _int(form.get("song_id"), -1, -1, 10**9)
        if session.get(Song, song_id) is None:
            flash(request, "That song is no longer in the library.", "error")
            return _redirect(f"/planner/plans/{plan.id}{_tab(form)}")
        choices[key] = song_id
    elif action == "none":
        choices[key] = NONE_CHOICE
    elif action == "reset":
        choices.pop(key, None)
    elif action == "skip":
        skipped.add(key)
    elif action == "restore":
        skipped.discard(key)
    else:
        raise HTTPException(status_code=400, detail="Unknown action")
    plan.choices_json, plan.skipped_json = dump_choices(choices), dump_skipped(skipped)
    _touch(session, plan)
    return _redirect(f"/planner/plans/{plan.id}{_tab(form)}")


@router.post("/{plan_id}/settings")
async def settings(request: Request, plan_id: int, user: User = Depends(require_user), session: Session = Depends(get_session)):
    form = await request.form()
    check_csrf(request, str(form.get("csrf_token", "")))
    plan = _plan(session, plan_id)
    name = " ".join(str(form.get("plan_name", "")).split())[:100]
    if not name:
        flash(request, "A plan needs a name.", "error")
        return _redirect(f"/planner/plans/{plan.id}")
    plan.name, plan.tag = name, _theme_tag(form.get("tag", ""))
    plan.overuse = _int(form.get("overuse"), plan.overuse, 1, 99)
    _touch(session, plan)
    flash(request, "Saved the plan's settings.", "success")
    return _redirect(f"/planner/plans/{plan.id}")


@router.post("/{plan_id}/sheet")
async def replace_sheet(request: Request, plan_id: int, user: User = Depends(require_user), session: Session = Depends(get_session)):
    """Swap in a newer version of the sheet. The decisions already made carry over to lines that are still there."""
    form = await request.form()
    check_csrf(request, str(form.get("csrf_token", "")))
    plan = _plan(session, plan_id)
    try:
        upload = form.get("sheet")
        pasted = str(form.get("pasted", ""))
        if upload is not None and getattr(upload, "filename", ""):
            rows = rows_from_upload(upload.filename, await upload.read(MAX_UPLOAD_BYTES + 1))
        elif pasted.strip():
            rows = rows_from_text(pasted[:200_000])
        else:
            raise SheetError("Paste the new sheet, or choose a file.")
    except SheetError as exc:
        flash(request, str(exc), "error")
        return _redirect(f"/planner/plans/{plan.id}")
    if not rows:
        flash(request, "The new sheet is empty.", "error")
        return _redirect(f"/planner/plans/{plan.id}")
    roles, header = guess_mapping(rows, _library(session))
    plan.raw = "\n".join("\t".join(r) for r in rows)
    plan.roles, plan.has_header = ",".join(roles), header
    _touch(session, plan)
    flash(request, "Replaced the sheet. Your choices were kept for lines that are still on it.", "success")
    return _redirect(f"/planner/plans/{plan.id}")


@router.post("/{plan_id}/tag")
async def tag_ready(request: Request, plan_id: int, user: User = Depends(require_user), session: Session = Depends(get_session)):
    """Add the plan's theme tag to every song that is ready."""
    form = await request.form()
    check_csrf(request, str(form.get("csrf_token", "")))
    plan = _plan(session, plan_id)
    if not plan.tag:
        flash(request, "Give the plan a theme tag first.", "error")
        return _redirect(f"/planner/plans/{plan.id}")
    ids = {s.id for s in ready_songs(_items(plan, _library(session)))}
    changed = full = 0
    for song in session.exec(select(Song).where(Song.id.in_(ids))).all() if ids else []:
        updated = add_tag(song.tags, plan.tag)
        if updated is None:
            full += 1
        elif updated != song.tags:
            song.tags = updated
            session.add(song)
            changed += 1
    session.commit()
    msg = f"Added the tag “{plan.tag}” to {changed} song{'s' if changed != 1 else ''}."
    if full:
        msg += f" {full} already had the maximum number of tags."
    flash(request, msg, "success")
    return _redirect(f"/planner/plans/{plan.id}")


@router.post("/{plan_id}/game")
async def make_game(
    request: Request, plan_id: int, user: User = Depends(require_game_creator), session: Session = Depends(get_session),
):
    """Create a game whose song pool is the plan's ready songs."""
    form = await request.form()
    check_csrf(request, str(form.get("csrf_token", "")))
    plan = _plan(session, plan_id)
    back = f"/planner/plans/{plan.id}"
    name = " ".join(str(form.get("game_name", "")).split())
    try:
        size, count = int(str(form.get("grid_size", ""))), int(str(form.get("ticket_count", "")))
    except ValueError:
        size = count = 0
    errors = []
    if not 1 <= len(name) <= 100:
        errors.append("Give the game a name (up to 100 characters).")
    if not MIN_GRID <= size <= MAX_GRID:
        errors.append(f"Grid size must be a whole number from {MIN_GRID} to {MAX_GRID}.")
    if not 1 <= count <= MAX_TICKETS:
        errors.append(f"Number of cards must be a whole number from 1 to {MAX_TICKETS}.")
    items = _items(plan, _library(session))
    pool = [s.id for s in ready_songs(items)]
    waiting = sum(1 for i in items if i.state in (NEED, PICK))
    if not errors and len(pool) < size * size:
        errors.append(
            f"A {size}×{size} card needs at least {size * size} different songs and only {len(pool)} are ready"
            + (f" ({waiting} line{'s' if waiting != 1 else ''} still waiting)." if waiting else ".")
        )
    generated = None
    if not errors:
        try:
            generated = await run_in_threadpool(generate_tickets, pool, size, count)
        except TicketGenerationError as exc:
            errors.append(str(exc))
    if errors:
        for error in errors:
            flash(request, error, "error")
        return _redirect(back + "#make-game")

    game = Game(owner_id=user.id, name=name, code=_new_code(session), grid_size=size)
    session.add(game)
    session.flush()
    session.add_all(GameSong(game_id=game.id, song_id=sid) for sid in pool)
    session.add(Round(game_id=game.id, number=1, name="Round 1"))
    session.add_all(Ticket(game_id=game.id, number=n, cells=cells) for n, cells in enumerate(generated.tickets, start=1))
    plan.game_id = game.id
    plan.updated_at = utcnow()
    session.add(plan)
    session.commit()
    flash(request, f"Created “{name}” from the plan with {len(pool)} songs and {count} cards.", "success")
    warning = variety_warning(generated.min_difference, size)
    if warning:
        flash(request, warning, "info")
    return _redirect(f"/games/{game.id}")


@router.post("/{plan_id}/delete")
async def delete_plan(request: Request, plan_id: int, user: User = Depends(require_user), session: Session = Depends(get_session)):
    form = await request.form()
    check_csrf(request, str(form.get("csrf_token", "")))
    plan = _plan(session, plan_id)
    if not can_delete(user, plan.owner_id):
        raise HTTPException(status_code=403, detail="Only the plan's creator or an administrator can delete it")
    name = plan.name
    session.delete(plan)
    session.commit()
    flash(request, f"Deleted the plan “{name}”. Its songs and games are untouched.", "success")
    return _redirect("/planner/plans")

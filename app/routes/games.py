"""Games: create from a song pool, generate tickets, manage rounds, view tickets."""

import re
import secrets

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import delete, func, or_
from sqlmodel import Session, select
from starlette.concurrency import run_in_threadpool

from app.db import get_session
from app.deps import require_game_creator, require_user
from app.models import Claim, Game, GameSong, Round, Song, Team, Ticket, User
from app.security import check_csrf
from app.services.series import latest_runs, series_key
from app.services.brand_store import brand_context, brand_style
from app.services.cardtext import CONTENTS, card_text, clean_content
from app.services.branding import VARIABLE_HELP, clean_footer, footer_problem, unknown_variables
from app.services.pdf import (
    DEFAULT_ORIENTATION, DEFAULT_PER_PAGE, ORIENTATIONS, PAPER_SIZES, TICKETS_PER_PAGE,
    build_tickets_pdf, fonts_from_settings, with_footer,
)
from app.services.patterns import (
    MODE_FULL_HOUSE, MODE_LINES, MODE_SHAPES, RoundRules, describe_rules, shapes_to_json, validate_rules,
)
from app.services.shapes_store import resolve_shapes, selected_ids, shapes_for_size
from app.services.ticket_gen import TicketGenerationError, generate_tickets, variety_warning
from app.web import flash, render

router = APIRouter(prefix="/games")

DEFAULT_GRID = 5
MIN_GRID, MAX_GRID = 3, 9
DEFAULT_TICKETS = 30
MAX_TICKETS = 500
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I to avoid mix-ups when typing


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def can_delete(user: User, owner_id: int) -> bool:
    """Games and songs are shared by every host account, but only their creator or an administrator may delete them."""
    return bool(user.is_admin) or owner_id == user.id


def owned_game(session: Session, user: User, game_id: int) -> Game:
    """Any signed-in host can open and run any game (the name is historical: games used to be per-host)."""
    game = session.get(Game, game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="Game not found")
    return game


def _new_code(session: Session) -> str:
    for _ in range(20):
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
        if session.exec(select(Game.id).where(Game.code == code)).first() is None:
            return code
    raise RuntimeError("could not allocate a unique game code")


def _library(session: Session, user: User) -> list[Song]:
    return session.exec(select(Song).order_by(func.lower(Song.title), Song.id)).all()


# ---------------------------------------------------------------- list / create


@router.get("")
def games_list(request: Request, user: User = Depends(require_user), session: Session = Depends(get_session)):
    every_run = session.exec(select(Game).order_by(Game.created_at.desc())).all()
    games, run_counts = latest_runs(every_run)  # re-running a game doesn't add rows to the list
    ids = [game.id for game in games]
    tickets = dict(
        session.exec(
            select(Ticket.game_id, func.count(Ticket.id)).where(Ticket.game_id.in_(ids)).group_by(Ticket.game_id)
        ).all()
    )
    songs = dict(
        session.exec(
            select(GameSong.game_id, func.count(GameSong.song_id))
            .where(GameSong.game_id.in_(ids))
            .group_by(GameSong.game_id)
        ).all()
    )
    return render(request, "games.html", user=user, games=games, ticket_counts=tickets, song_counts=songs, run_counts=run_counts)


def _new_game_page(request, user, session, *, status_code=200, form=None, selected=(), errors=()):
    form = form or {"name": "", "grid_size": str(DEFAULT_GRID), "ticket_count": str(DEFAULT_TICKETS)}
    return render(
        request,
        "new_game.html",
        status_code=status_code,
        user=user,
        songs=_library(session, user),
        form=form,
        selected=set(selected),
        errors=list(errors),
        min_grid=MIN_GRID,
        max_grid=MAX_GRID,
        max_tickets=MAX_TICKETS,
    )


@router.get("/new")
def new_game_form(request: Request, user: User = Depends(require_game_creator), session: Session = Depends(get_session)):
    return _new_game_page(request, user, session)


@router.post("/new")
async def new_game_submit(
    request: Request,
    name: str = Form(""),
    grid_size: str = Form(str(DEFAULT_GRID)),
    ticket_count: str = Form(str(DEFAULT_TICKETS)),
    song_ids: list[int] = Form(default=[]),
    csrf_token: str = Form(""),
    user: User = Depends(require_game_creator),
    session: Session = Depends(get_session),
):
    check_csrf(request, csrf_token)
    name = name.strip()
    form = {"name": name, "grid_size": grid_size, "ticket_count": ticket_count}
    errors: list[str] = []
    if not 1 <= len(name) <= 100:
        errors.append("Give the game a name (up to 100 characters).")
    try:
        size = int(grid_size)
        if not MIN_GRID <= size <= MAX_GRID:
            raise ValueError
    except ValueError:
        size = DEFAULT_GRID
        errors.append(f"Grid size must be a whole number from {MIN_GRID} to {MAX_GRID}.")
    try:
        count = int(ticket_count)
        if not 1 <= count <= MAX_TICKETS:
            raise ValueError
    except ValueError:
        count = DEFAULT_TICKETS
        errors.append(f"Number of cards must be a whole number from 1 to {MAX_TICKETS}.")

    # Only songs that exist in the (shared) library can go in the pool.
    owned = {sid for sid in session.exec(select(Song.id)).all()}
    pool = [sid for sid in dict.fromkeys(song_ids) if sid in owned]

    generated = None
    if not errors:
        try:
            generated = await run_in_threadpool(generate_tickets, pool, size, count)
        except TicketGenerationError as exc:
            errors.append(str(exc))
    if errors:
        return _new_game_page(request, user, session, status_code=400, form=form, selected=pool, errors=errors)

    game = Game(owner_id=user.id, name=name, code=_new_code(session), grid_size=size)
    session.add(game)
    session.flush()  # assigns game.id
    session.add_all(GameSong(game_id=game.id, song_id=sid) for sid in pool)
    session.add(Round(game_id=game.id, number=1, name="Round 1"))  # default: one line, rows only
    session.add_all(
        Ticket(game_id=game.id, number=n, cells=cells) for n, cells in enumerate(generated.tickets, start=1)
    )
    session.commit()

    message = f"Created \u201c{name}\u201d with {count} cards. Any two cards differ by at least {generated.min_difference} song(s)."
    flash(request, message, "success")
    warning = variety_warning(generated.min_difference, size)
    if warning:
        flash(request, warning, "info")
    return _redirect(f"/games/{game.id}")


# ---------------------------------------------------------------- detail


@router.get("/{game_id}")
def game_detail(
    request: Request, game_id: int, user: User = Depends(require_user), session: Session = Depends(get_session)
):
    game = owned_game(session, user, game_id)
    rounds = session.exec(select(Round).where(Round.game_id == game.id).order_by(Round.number)).all()
    available_shapes = shapes_for_size(session, game.grid_size)
    pool_ids = set(session.exec(select(GameSong.song_id).where(GameSong.game_id == game.id)).all())
    library = session.exec(select(Song).order_by(func.lower(Song.title), Song.id)).all()
    card_counts: dict[int, int] = {}
    for cells in session.exec(select(Ticket.cells).where(Ticket.game_id == game.id)).all():
        for song_id in set(cells):
            card_counts[song_id] = card_counts.get(song_id, 0) + 1
    already_played = set(game.play_order[: game.current_index])
    playlist = [
        {"song": s, "cards": card_counts.get(s.id, 0), "played": s.id in already_played}
        for s in library if s.id in pool_ids
    ]
    spare_songs = [s for s in library if s.id not in pool_ids]
    # The play order section: songs already played (fixed), then the ones still to come, which the host can arrange.
    # A draft game with no planned order lists its songs alphabetically; Start shuffles them unless an order is saved.
    by_id = {s.id: s for s in library if s.id in pool_ids}
    order = [sid for sid in game.play_order if sid in by_id]
    order_played = [by_id[sid] for sid in order[: game.current_index]]
    order_upcoming = [by_id[sid] for sid in order[game.current_index:]]
    if game.status == "draft" and not order:
        order_upcoming = list(by_id.values())
    ticket_numbers = session.exec(select(Ticket.number).where(Ticket.game_id == game.id).order_by(Ticket.number)).all()
    song_count = session.exec(select(func.count(GameSong.song_id)).where(GameSong.game_id == game.id)).one()
    team_count = session.exec(select(func.count(Team.id)).where(Team.game_id == game.id)).one()
    key = series_key(game)
    other_runs = session.exec(
        select(Game)
        .where(or_(Game.id == key, Game.series_id == key), Game.id != game.id)
        .order_by(Game.run_number.desc())
    ).all()
    return render(
        request,
        "game.html",
        user=user,
        game=game,
        rounds=[(r, describe_rules(r.rules(), game.grid_size), selected_ids(r, available_shapes)) for r in rounds],
        shapes=available_shapes,
        playlist=playlist,
        spare_songs=spare_songs,
        order_played=order_played,
        order_upcoming=order_upcoming,
        order_planned=bool(game.play_order),
        ticket_numbers=ticket_numbers,
        song_count=song_count,
        team_count=team_count,
        other_runs=other_runs,
        max_lines=2 * game.grid_size + 2,
        can_delete=can_delete(user, game.owner_id),
    )


@router.post("/{game_id}/delete")
def delete_game(
    request: Request,
    game_id: int,
    csrf_token: str = Form(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    check_csrf(request, csrf_token)
    game = owned_game(session, user, game_id)
    if not can_delete(user, game.owner_id):
        flash(request, "Only the person who created a game, or an administrator, can delete it.", "error")
        return _redirect(f"/games/{game.id}")
    for model in (Claim, Team, Ticket, Round, GameSong):  # children first
        session.execute(delete(model).where(model.game_id == game.id))
    session.delete(game)
    session.commit()
    flash(request, "Game deleted.", "success")
    return _redirect("/games")


# ---------------------------------------------------------------- rounds


def parse_rules(game: Game, mode: str, lines_required: str, rows: bool, columns: bool, diagonals: bool, shapes=()):
    errors: list[str] = []
    try:
        required = int(lines_required)
    except ValueError:
        required = 1
        errors.append("Lines required must be a whole number.")
    if mode not in (MODE_LINES, MODE_FULL_HOUSE, MODE_SHAPES):
        errors.append("Unknown pattern type.")
    rules = RoundRules(mode=mode, lines_required=required, rows=rows, columns=columns, diagonals=diagonals, shapes=tuple(shapes))
    if not errors:
        errors.extend(validate_rules(rules, game.grid_size))
    return rules, errors


@router.post("/{game_id}/rounds")
def add_round(
    request: Request,
    game_id: int,
    name: str = Form(""),
    mode: str = Form(MODE_LINES),
    lines_required: str = Form("1"),
    rows: bool = Form(False),
    columns: bool = Form(False),
    diagonals: bool = Form(False),
    shape_ids: list[int] = Form(default=[]),
    csrf_token: str = Form(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    check_csrf(request, csrf_token)
    game = owned_game(session, user, game_id)
    rules, errors = parse_rules(game, mode, lines_required, rows, columns, diagonals, resolve_shapes(session, game, shape_ids))
    if errors:
        flash(request, errors[0], "error")
        return _redirect(f"/games/{game.id}")
    last = session.exec(select(func.max(Round.number)).where(Round.game_id == game.id)).one() or 0
    number = last + 1
    session.add(
        Round(
            game_id=game.id,
            number=number,
            name=(name.strip() or f"Round {number}")[:60],
            mode=rules.mode,
            lines_required=rules.lines_required,
            rows=rules.rows,
            columns=rules.columns,
            diagonals=rules.diagonals,
            shapes_json=shapes_to_json(rules.shapes),
        )
    )
    session.commit()
    flash(request, "Round added.", "success")
    return _redirect(f"/games/{game.id}")


def _owned_round(session: Session, game: Game, round_id: int) -> Round:
    found = session.get(Round, round_id)
    if found is None or found.game_id != game.id:
        raise HTTPException(status_code=404, detail="Round not found")
    return found


@router.post("/{game_id}/rounds/{round_id}")
def update_round(
    request: Request,
    game_id: int,
    round_id: int,
    name: str = Form(""),
    mode: str = Form(MODE_LINES),
    lines_required: str = Form("1"),
    rows: bool = Form(False),
    columns: bool = Form(False),
    diagonals: bool = Form(False),
    shape_ids: list[int] = Form(default=[]),
    csrf_token: str = Form(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    check_csrf(request, csrf_token)
    game = owned_game(session, user, game_id)
    target = _owned_round(session, game, round_id)
    rules, errors = parse_rules(game, mode, lines_required, rows, columns, diagonals, resolve_shapes(session, game, shape_ids))
    if errors:
        flash(request, errors[0], "error")
        return _redirect(f"/games/{game.id}")
    target.name = (name.strip() or f"Round {target.number}")[:60]
    target.mode = rules.mode
    target.lines_required = rules.lines_required
    target.rows, target.columns, target.diagonals = rules.rows, rules.columns, rules.diagonals
    target.shapes_json = shapes_to_json(rules.shapes)
    session.add(target)
    session.commit()
    flash(request, f"Saved {target.name}.", "success")
    return _redirect(f"/games/{game.id}")


@router.post("/{game_id}/rounds/{round_id}/delete")
def delete_round(
    request: Request,
    game_id: int,
    round_id: int,
    csrf_token: str = Form(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    check_csrf(request, csrf_token)
    game = owned_game(session, user, game_id)
    target = _owned_round(session, game, round_id)
    if game.status != "draft" and target.number <= game.current_round:
        flash(request, "Rounds that have been played, or are being played, can't be deleted.", "error")
        return _redirect(f"/games/{game.id}")
    rounds = session.exec(select(Round).where(Round.game_id == game.id).order_by(Round.number)).all()
    if len(rounds) <= 1:
        flash(request, "A game needs at least one round.", "error")
        return _redirect(f"/games/{game.id}")
    session.delete(target)
    session.flush()
    for position, remaining in enumerate((r for r in rounds if r.id != target.id), start=1):
        if remaining.number != position:  # close the gap, in ascending order
            remaining.number = position
            session.add(remaining)
    session.commit()
    flash(request, "Round deleted.", "success")
    return _redirect(f"/games/{game.id}")


# ---------------------------------------------------------------- tickets


@router.get("/{game_id}/cards/{number}")
def ticket_view(
    request: Request,
    game_id: int,
    number: int,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    game = owned_game(session, user, game_id)
    ticket = session.exec(select(Ticket).where(Ticket.game_id == game.id, Ticket.number == number)).first()
    if ticket is None:
        raise HTTPException(status_code=404, detail="Card not found")
    songs = {s.id: s for s in session.exec(select(Song).where(Song.id.in_(ticket.cells))).all()}
    size = game.grid_size
    grid = [[songs.get(sid) for sid in ticket.cells[r * size:(r + 1) * size]] for r in range(size)]
    total = session.exec(select(func.count(Ticket.id)).where(Ticket.game_id == game.id)).one()
    return render(
        request,
        "ticket.html",
        user=user,
        game=game,
        number=number,
        grid=grid,
        size=size,
        total=total,
        brand=brand_context(session, request.app.state.settings, game.owner_id, game.code),
    )


@router.post("/{game_id}/card-footer")
def set_ticket_footer(
    request: Request,
    game_id: int,
    ticket_footer: str = Form(""),
    csrf_token: str = Form(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    """The line printed at the foot of this game's tickets (say, next week's game). Empty means
    the host's branding footer is used instead."""
    check_csrf(request, csrf_token)
    game = owned_game(session, user, game_id)
    text = clean_footer(ticket_footer)
    problem = footer_problem(text)
    if problem:
        flash(request, problem, "error")
        return _redirect(f"/games/{game.id}")
    bad = unknown_variables(text)
    if bad:
        flash(request, f"{bad[0]} isn't a known variable. You can use {VARIABLE_HELP}.", "error")
        return _redirect(f"/games/{game.id}")
    game.ticket_footer = text
    session.add(game)
    session.commit()
    flash(request, "Card footer saved." if text else "Card footer cleared: the branding footer will be used.", "success")
    return _redirect(f"/games/{game.id}")


@router.post("/{game_id}/card-content")
def set_card_content(
    request: Request,
    game_id: int,
    card_content: str = Form("both"),
    csrf_token: str = Form(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    """What each square of this game's cards shows: song and band, band only, or song only. It changes how the
    cards print and how they look on players' phones; the song pool and the cards themselves are untouched."""
    check_csrf(request, csrf_token)
    game = owned_game(session, user, game_id)
    if card_content not in CONTENTS:
        flash(request, "Choose one of the listed options.", "error")
        return _redirect(f"/games/{game.id}")
    game.card_content = card_content
    session.add(game)
    session.commit()
    flash(request, f"Cards will show: {CONTENTS[card_content].lower()}.", "success")
    return _redirect(f"/games/{game.id}")


@router.get("/{game_id}/tickets/{number}")
def old_card_url(game_id: int, number: int):
    """Cards used to be called tickets; keep bookmarks to the old address working."""
    return RedirectResponse(f"/games/{game_id}/cards/{number}", status_code=307)


@router.get("/{game_id}/tickets.pdf")
def old_cards_pdf_url(request: Request, game_id: int):
    query = f"?{request.url.query}" if request.url.query else ""
    return RedirectResponse(f"/games/{game_id}/cards.pdf{query}", status_code=307)


@router.get("/{game_id}/cards.pdf")
def tickets_pdf(
    request: Request,
    game_id: int,
    paper: str = "letter",
    per_page: int = DEFAULT_PER_PAGE,
    orientation: str = DEFAULT_ORIENTATION,
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    """Every ticket in one PDF, numbered, ready to print and hand out."""
    game = owned_game(session, user, game_id)
    if paper not in PAPER_SIZES or per_page not in TICKETS_PER_PAGE or orientation not in ORIENTATIONS:
        raise HTTPException(status_code=400, detail="Unsupported paper size, orientation or cards-per-page value")
    tickets = session.exec(select(Ticket).where(Ticket.game_id == game.id).order_by(Ticket.number)).all()
    if not tickets:
        raise HTTPException(status_code=404, detail="This game has no cards")
    wanted = {song_id for ticket in tickets for song_id in ticket.cells}
    songs = {s.id: s for s in session.exec(select(Song).where(Song.id.in_(wanted))).all()}
    sheets = [
        (ticket.number, [card_text(songs[sid].title, songs[sid].artist, game.card_content) if sid in songs else ("(song removed)", "")
                         for sid in ticket.cells])
        for ticket in tickets
    ]
    settings = request.app.state.settings
    fonts = fonts_from_settings(settings)  # falls back to the built-in font if the configured one fails
    brand = with_footer(brand_style(session, settings, game.owner_id), game.ticket_footer)
    data = build_tickets_pdf(
        game.name, game.grid_size, sheets, paper=paper, per_page=per_page, orientation=orientation, fonts=fonts, brand=brand,
    )
    filename = re.sub(r"[^A-Za-z0-9_-]+", "-", game.name).strip("-") or "game"
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}-cards.pdf"', "Cache-Control": "no-store"},
    )


@router.post("/{game_id}/rerun")
def rerun_game(
    request: Request,
    game_id: int,
    regenerate: bool = Form(False),
    csrf_token: str = Form(""),
    user: User = Depends(require_game_creator),
    session: Session = Depends(get_session),
):
    """Run a finished game again: same song pool, rounds and (by default) the same tickets,
    so printed tickets stay valid, under a new join code. Teams and claims start fresh."""
    check_csrf(request, csrf_token)
    source = owned_game(session, user, game_id)
    if source.status != "finished":
        flash(request, "Only a finished game can be run again.", "error")
        return _redirect(f"/games/{source.id}")

    key = series_key(source)
    latest = session.exec(
        select(func.max(Game.run_number)).where(or_(Game.id == key, Game.series_id == key))
    ).one() or 1
    pool = list(session.exec(select(GameSong.song_id).where(GameSong.game_id == source.id)).all())
    old_tickets = session.exec(select(Ticket).where(Ticket.game_id == source.id).order_by(Ticket.number)).all()
    warning = None
    if regenerate:
        try:
            generated = generate_tickets(pool, source.grid_size, len(old_tickets))
        except TicketGenerationError as exc:
            flash(request, str(exc), "error")
            return _redirect(f"/games/{source.id}")
        tickets = list(enumerate(generated.tickets, start=1))
        warning = variety_warning(generated.min_difference, source.grid_size)
    else:
        tickets = [(t.number, list(t.cells)) for t in old_tickets]

    game = Game(
        owner_id=user.id, name=source.name, code=_new_code(session), grid_size=source.grid_size,
        series_id=key, run_number=latest + 1, card_content=source.card_content,
    )
    session.add(game)
    session.flush()
    session.add_all(GameSong(game_id=game.id, song_id=song_id) for song_id in pool)
    for r in session.exec(select(Round).where(Round.game_id == source.id).order_by(Round.number)).all():
        session.add(Round(
            game_id=game.id, number=r.number, name=r.name, mode=r.mode, lines_required=r.lines_required,
            rows=r.rows, columns=r.columns, diagonals=r.diagonals, shapes_json=r.shapes_json,
        ))
    session.add_all(Ticket(game_id=game.id, number=number, cells=cells) for number, cells in tickets)
    session.commit()

    how = "with new cards" if regenerate else "with the same cards, so printed copies still work"
    if warning:
        flash(request, warning, "info")
    flash(request, f"Run {game.run_number} of \u201c{game.name}\u201d is ready {how}. New join code: {game.code}", "success")
    return _redirect(f"/games/{game.id}")

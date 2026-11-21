"""Change a game's song pool after it has been created: add songs, remove songs, or swap one for another.

The cards are fixed once made (so printed cards stay valid), which shapes the rules:
- a song that has already been played is never changed, so earlier claims stay valid;
- a song on any card can only be *replaced* (the new song takes its place on those cards), not removed;
- songs added to the pool are on no existing card: they just give the game more tracks to play.
"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import delete
from sqlmodel import Session, select

from app.db import get_session
from app.deps import require_user
from app.models import Game, GameSong, Song, Team, Ticket, User
from app.routes.games import owned_game
from app.routes.play import join_url
from app.security import check_csrf
from app.services.playlist import (
    insert_into_remaining, played_ids, remove_from_remaining, replace_in_remaining,
)
from app.services.snapshots import broadcast
from app.web import flash

router = APIRouter(prefix="/games/{game_id}/playlist")


def _back(game: Game) -> RedirectResponse:
    return RedirectResponse(f"/games/{game.id}#playlist", status_code=303)


def _problem(request: Request, game: Game, message: str) -> RedirectResponse:
    flash(request, message, "error")
    return _back(game)


def _pool(session: Session, game: Game) -> set[int]:
    return set(session.exec(select(GameSong.song_id).where(GameSong.game_id == game.id)).all())


def _commit(request: Request, session: Session, game: Game) -> None:
    session.add(game)
    session.commit()
    if game.status == "active":  # the console, players and phone remote all see the change at once
        broadcast(request.app.state.hub, session, game, join_url(request, game))


def _unplayed(game: Game, song_id: int) -> bool:
    return song_id not in set(played_ids(list(game.play_order), game.current_index))


def _on_cards(session: Session, game: Game, song_id: int) -> int:
    return sum(1 for cells in session.exec(select(Ticket.cells).where(Ticket.game_id == game.id)).all() if song_id in cells)


@router.post("/add")
def add_songs(
    request: Request, game_id: int, song_ids: list[int] = Form(default=[]), csrf_token: str = Form(""),
    user: User = Depends(require_user), session: Session = Depends(get_session),
):
    check_csrf(request, csrf_token)
    game = owned_game(session, user, game_id)
    if game.status == "finished":
        return _problem(request, game, "This game has finished. Run it again to change its songs.")
    have = _pool(session, game)
    wanted = [i for i in dict.fromkeys(song_ids) if i not in have]
    found = set(session.exec(select(Song.id).where(Song.id.in_(wanted))).all()) if wanted else set()
    wanted = [i for i in wanted if i in found]
    if not wanted:
        return _problem(request, game, "Choose at least one song that isn't already in the game.")
    session.add_all(GameSong(game_id=game.id, song_id=i) for i in wanted)
    if game.play_order:  # a running game: slot them in among the songs still to come
        game.play_order = insert_into_remaining(list(game.play_order), game.current_index, wanted)
    _commit(request, session, game)
    flash(request, f"Added {len(wanted)} song{'s' if len(wanted) != 1 else ''} to the playlist. They are on no card yet, "
                   "so they just give you extra tracks to play.", "success")
    return _back(game)


@router.post("/remove")
def remove_song(
    request: Request, game_id: int, song_id: int = Form(...), csrf_token: str = Form(""),
    user: User = Depends(require_user), session: Session = Depends(get_session),
):
    check_csrf(request, csrf_token)
    game = owned_game(session, user, game_id)
    if game.status == "finished":
        return _problem(request, game, "This game has finished. Run it again to change its songs.")
    pool = _pool(session, game)
    if song_id not in pool:
        return _problem(request, game, "That song isn't in this game.")
    if not _unplayed(game, song_id):
        return _problem(request, game, "That song has already been played, so it can't be removed.")
    count = _on_cards(session, game, song_id)
    if count:
        return _problem(request, game, f"That song is on {count} card{'s' if count != 1 else ''}, so it can't simply be removed. "
                                       "Replace it with another song instead.")
    if len(pool) - 1 < game.grid_size ** 2:
        return _problem(request, game, f"A {game.grid_size}×{game.grid_size} card needs at least {game.grid_size ** 2} songs in the playlist.")
    session.execute(delete(GameSong).where(GameSong.game_id == game.id, GameSong.song_id == song_id))
    if game.play_order:
        game.play_order = remove_from_remaining(list(game.play_order), game.current_index, song_id)
    _commit(request, session, game)
    flash(request, "Song removed from the playlist.", "success")
    return _back(game)


@router.post("/replace")
def replace_song(
    request: Request, game_id: int, song_id: int = Form(...), with_id: int = Form(...), csrf_token: str = Form(""),
    user: User = Depends(require_user), session: Session = Depends(get_session),
):
    check_csrf(request, csrf_token)
    game = owned_game(session, user, game_id)
    if game.status == "finished":
        return _problem(request, game, "This game has finished. Run it again to change its songs.")
    pool = _pool(session, game)
    if song_id not in pool:
        return _problem(request, game, "That song isn't in this game.")
    if not _unplayed(game, song_id):
        return _problem(request, game, "That song has already been played, so it can't be replaced.")
    if with_id in pool or session.get(Song, with_id) is None:
        return _problem(request, game, "Choose a song from your library that isn't already in the game.")
    changed = 0
    for ticket in session.exec(select(Ticket).where(Ticket.game_id == game.id)).all():
        if song_id not in ticket.cells:
            continue
        positions = [pos for pos, cell in enumerate(ticket.cells) if cell == song_id]
        ticket.cells = [with_id if cell == song_id else cell for cell in ticket.cells]  # a new list, so it is saved
        session.add(ticket)
        changed += 1
        for team in session.exec(select(Team).where(Team.ticket_id == ticket.id)).all():
            team.marks = [m for m in team.marks if m not in positions]  # a square that now holds a different song starts unmarked
            session.add(team)
    session.execute(delete(GameSong).where(GameSong.game_id == game.id, GameSong.song_id == song_id))
    session.add(GameSong(game_id=game.id, song_id=with_id))
    if game.play_order:
        game.play_order = replace_in_remaining(list(game.play_order), game.current_index, song_id, with_id)
    _commit(request, session, game)
    note = f" on {changed} card{'s' if changed != 1 else ''}" if changed else ""
    flash(request, f"Song replaced{note}." + (" Cards you have already printed still show the old song." if changed else ""), "success")
    return _back(game)

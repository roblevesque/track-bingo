"""Check a printed card against the songs played so far, for the host console and the phone remote.

Besides the verdict, the result describes every square (title, whether it has been played, whether it is part of
a winning line, whether it is still needed) so the host can see the card on screen and compare it with the paper.
"""

from sqlmodel import Session, select

from app.models import Game, Round, Song, Ticket
from app.services.checker import verify_claim
from app.services.patterns import describe_line
from app.services.playlist import played_ids
from app.services.snapshots import round_name


class CardCheckError(Exception):
    """The card can't be checked; `status` is the HTTP status that fits (404 no such card, 409 not now)."""

    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def check_card(session: Session, game: Game, number: int) -> dict:
    if game.status == "draft":
        raise CardCheckError("Start the game first.")
    if game.status == "finished":
        raise CardCheckError("This game has finished.")
    ticket = session.exec(select(Ticket).where(Ticket.game_id == game.id, Ticket.number == number)).first()
    if ticket is None:
        raise CardCheckError(f"There is no card number {number} in this game.", 404)
    current = session.exec(select(Round).where(Round.game_id == game.id, Round.number == game.current_round)).first()
    if current is None:
        raise CardCheckError("There is no round in progress.")
    cells = list(ticket.cells)
    played = set(played_ids(game.play_order, game.current_index))
    try:
        result = verify_claim(cells, played, game.grid_size, current.rules())
    except ValueError as exc:
        raise CardCheckError(str(exc)) from None
    songs = {s.id: s for s in session.exec(select(Song).where(Song.id.in_(cells))).all()}
    winning: set[int] = set()
    if result.is_win:  # a full house wins with no lines, and then every square counts
        winning = {pos for line in result.completed for pos in line.cells} or set(range(len(cells)))
    needed = set(result.missing_song_ids)
    return {
        "ticket": ticket.number,
        "round": round_name(current),
        "status": result.status,
        "lines": [describe_line(line) for line in result.completed],
        "squares_needed": result.squares_needed,
        "missing": [songs[sid].title if sid in songs else "?" for sid in result.missing_song_ids],
        "size": game.grid_size,
        "squares": [
            {
                "title": songs[sid].title if sid in songs else "(song removed)",
                "artist": songs[sid].artist if sid in songs else "",
                "played": sid in played,
                "winning": pos in winning,  # part of a completed line or shape (a full house marks every square)
                "needed": sid in needed,  # not played yet, on the closest route to a win
            }
            for pos, sid in enumerate(cells)
        ],
    }

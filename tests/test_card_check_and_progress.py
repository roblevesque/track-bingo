"""Checking a printed card shows the card itself, and the clip position reaches the phone remote."""
import pytest
from sqlmodel import Session, select

from app.models import Round, Ticket
from app.services.events import REMOTE
from app.services.remote import parse_playback, playback_now
from tests.conftest import csrf_token, host_post, new_player, set_play_order
from tests.test_remote_routes import paired_phone, with_console


def ticket_cells(app, game_id, number=1):
    with Session(app.state.engine) as session:
        return list(session.exec(select(Ticket).where(Ticket.game_id == game_id, Ticket.number == number)).one().cells)


def phone_check(phone, game_id, number):
    data = {"csrf_token": csrf_token(phone, f"/remote/{game_id}"), "ticket_number": str(number)}
    return phone.post(f"/remote/{game_id}/check", data=data)


def test_the_check_describes_every_square(app, running_game):
    host, game_id, _code = running_game
    cells = ticket_cells(app, game_id)
    set_play_order(app, game_id, cells[3:6])  # row 2 of card 1
    for _ in range(2):
        host_post(host, game_id, "next")
    short = host_post(host, game_id, "check", ticket_number=1).json()
    assert short["size"] == 3 and len(short["squares"]) == 9
    assert [s["played"] for s in short["squares"]] == [False, False, False, True, True, False, False, False, False]
    assert not any(s["winning"] for s in short["squares"])
    assert sum(s["needed"] for s in short["squares"]) == 1 and all(s["title"] for s in short["squares"])
    host_post(host, game_id, "next")
    win = host_post(host, game_id, "check", ticket_number=1).json()
    assert [s["winning"] for s in win["squares"]] == [False] * 3 + [True] * 3 + [False] * 3
    assert not any(s["needed"] for s in win["squares"])


def test_a_full_house_marks_every_square_as_winning(app, running_game):
    host, game_id, _code = running_game
    with Session(app.state.engine) as session:
        round_ = session.exec(select(Round).where(Round.game_id == game_id)).one()
        round_.mode = "full_house"
        session.add(round_)
        session.commit()
    cells = ticket_cells(app, game_id)
    set_play_order(app, game_id, cells)
    for _ in range(9):
        host_post(host, game_id, "next")
    result = host_post(host, game_id, "check", ticket_number=1).json()
    assert result["status"] == "win" and all(s["winning"] and s["played"] for s in result["squares"])


def test_a_paired_phone_can_check_a_card(app, running_game):
    host, game_id, _code = running_game
    phone, _ = paired_phone(app, host, game_id)
    host_post(host, game_id, "next")
    result = phone_check(phone, game_id, 1)
    assert result.status_code == 200 and len(result.json()["squares"]) == 9
    assert sum(s["played"] for s in result.json()["squares"]) <= 1
    assert phone_check(phone, game_id, 99).status_code == 404
    assert phone_check(phone, game_id, "abc").status_code == 400
    with_console(app, console_open=False)
    assert phone_check(phone, game_id, 1).status_code == 200  # read-only: works with the console closed


def test_an_unpaired_phone_cannot_check_cards(app, running_game):
    host, game_id, _code = running_game
    paired_phone(app, host, game_id)
    stranger = new_player(app)
    token = csrf_token(stranger, "/remote")
    response = stranger.post(f"/remote/{game_id}/check", data={"csrf_token": token, "ticket_number": "1"})
    assert response.status_code == 403


def test_the_console_passes_the_clip_position_to_phones(app, running_game):
    host, game_id, _code = running_game
    hub = with_console(app)
    response = host_post(host, game_id, "playback", song_id="7", elapsed="12.5", length="30", paused="")
    assert response.status_code == 200
    sent = [(aud, data) for aud, name, data in hub.published if name == "playback"]
    assert sent == [(REMOTE, {"song_id": 7, "elapsed": 12.5, "length": 30.0, "paused": False})]
    assert hub.real.playback[game_id][0]["elapsed"] == 12.5
    assert host_post(host, game_id, "playback", song_id="7", elapsed="nan").status_code == 400
    assert host.post(f"/games/{game_id}/run/playback", data={"song_id": "7"}).status_code == 403  # no csrf token
    stranger = new_player(app)
    token = csrf_token(stranger, "/remote")
    assert stranger.post(f"/games/{game_id}/run/playback", data={"song_id": "7", "csrf_token": token},
                         follow_redirects=False).status_code == 303


def test_playback_reports_are_checked_and_brought_up_to_date():
    assert parse_playback(1, "5", "", "1") == {"song_id": 1, "elapsed": 5.0, "length": None, "paused": True}
    assert parse_playback(1, "50", "30", "")["elapsed"] == 30.0  # never past the end of the clip
    for bad in ("-1", "inf", "nan", "soon", "99999"):
        with pytest.raises(ValueError):
            parse_playback(1, bad, "30", "")
    playing = parse_playback(1, "10", "30", "")
    assert playback_now(playing, 100.0, 104.0)["elapsed"] == 14.0
    assert playback_now(playing, 100.0, 200.0)["elapsed"] == 30.0
    paused = parse_playback(1, "10", "", "1")
    assert playback_now(paused, 100.0, 104.0)["elapsed"] == 10.0

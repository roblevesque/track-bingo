import io
import json
import zipfile

from sqlmodel import Session

from app.models import Game
from tests.conftest import add_user, create_game, csrf_token, game_id_from, login, new_player, seed_songs
from tests.test_pdf import page_count, page_sizes


def make_game(app, host, tmp_path):
    ids = seed_songs(app, host, tmp_path, 12)
    return game_id_from(create_game(host, ids, name="Pub Night", grid_size=3, tickets=4))


def set_footer(client, game_id, text):
    return client.post(f"/games/{game_id}/ticket-footer",
                       data={"ticket_footer": text, "csrf_token": csrf_token(client, f"/games/{game_id}")},
                       follow_redirects=False)


def footer_of(app, game_id):
    with Session(app.state.engine) as session:
        return session.get(Game, game_id).ticket_footer


def test_a_new_game_has_no_footer_and_the_page_offers_the_form(app, logged_in, tmp_path):
    game_id = make_game(app, logged_in, tmp_path)
    assert footer_of(app, game_id) == ""
    assert f'action="/games/{game_id}/ticket-footer"' in logged_in.get(f"/games/{game_id}").text


def test_the_footer_is_saved_tidied_and_shown_again(app, logged_in, tmp_path):
    game_id = make_game(app, logged_in, tmp_path)
    assert set_footer(logged_in, game_id, "  Next week:   90s Night  ").status_code == 303
    assert footer_of(app, game_id) == "Next week: 90s Night"
    assert 'value="Next week: 90s Night"' in logged_in.get(f"/games/{game_id}").text


def test_a_footer_can_be_cleared(app, logged_in, tmp_path):
    game_id = make_game(app, logged_in, tmp_path)
    set_footer(logged_in, game_id, "Something")
    set_footer(logged_in, game_id, "   ")
    assert footer_of(app, game_id) == ""


def test_an_overlong_footer_is_refused_and_nothing_changes(app, logged_in, tmp_path):
    game_id = make_game(app, logged_in, tmp_path)
    set_footer(logged_in, game_id, "Keep me")
    assert set_footer(logged_in, game_id, "x" * 121).status_code == 303
    assert footer_of(app, game_id) == "Keep me"
    set_footer(logged_in, game_id, "x" * 120)
    assert footer_of(app, game_id) == "x" * 120


def test_only_the_owner_can_set_it(app, logged_in, tmp_path):
    game_id = make_game(app, logged_in, tmp_path)
    token = csrf_token(logged_in, f"/games/{game_id}")
    add_user(app, "other")
    other = new_player(app)
    login(other, "other")
    response = other.post(f"/games/{game_id}/ticket-footer", data={"ticket_footer": "hijack", "csrf_token": csrf_token(other, "/games")})
    assert response.status_code == 404
    assert footer_of(app, game_id) == ""
    assert token  # the owner's page still renders for them


def test_it_needs_a_csrf_token(app, logged_in, tmp_path):
    game_id = make_game(app, logged_in, tmp_path)
    response = logged_in.post(f"/games/{game_id}/ticket-footer", data={"ticket_footer": "x"}, follow_redirects=False)
    assert response.status_code in (400, 403)
    assert footer_of(app, game_id) == ""


def test_the_pdf_defaults_to_one_landscape_ticket_per_page(app, logged_in, tmp_path):
    game_id = make_game(app, logged_in, tmp_path)
    pdf = logged_in.get(f"/games/{game_id}/tickets.pdf").content
    assert page_count(pdf) == 4
    assert all(w > h for w, h in page_sizes(pdf))
    portrait = logged_in.get(f"/games/{game_id}/tickets.pdf?orientation=portrait&per_page=2").content
    assert page_count(portrait) == 2 and all(w < h for w, h in page_sizes(portrait))
    assert logged_in.get(f"/games/{game_id}/tickets.pdf?orientation=sideways").status_code == 400


def test_the_game_page_defaults_match(app, logged_in, tmp_path):
    html = logged_in.get(f"/games/{make_game(app, logged_in, tmp_path)}").text
    assert '<option value="1" selected>' in html and '<option value="landscape" selected>' in html


def test_the_footer_survives_export_and_import(app, logged_in, tmp_path):
    game_id = make_game(app, logged_in, tmp_path)
    set_footer(logged_in, game_id, "Next week: Quiz Night")
    data = logged_in.get(f"/games/{game_id}/export?audio=1").content
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert json.loads(z.read("manifest.json"))["game"]["ticket_footer"] == "Next week: Quiz Night"
    response = logged_in.post("/games/import", data={"csrf_token": csrf_token(logged_in, "/games")},
                              files={"bundle": ("g.musicbingo.zip", data, "application/zip")}, follow_redirects=False)
    assert footer_of(app, game_id_from(response)) == "Next week: Quiz Night"

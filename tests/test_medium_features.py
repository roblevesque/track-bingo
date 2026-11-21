from sqlmodel import Session, select

from app.models import Branding, GameSong, Round, Ticket, WinShape
from tests.conftest import (
    csrf_token, create_game, game_id_from, get_game, host_post, join_game, login, new_player, pool_ids, seed_songs,
    set_played_count,
)


def post(client, path, page, **fields):
    data = {"csrf_token": csrf_token(client, page)}
    data.update(fields)
    return client.post(path, data=data, follow_redirects=False)


def shapes(app):
    with Session(app.state.engine) as session:
        return session.exec(select(WinShape).order_by(WinShape.id)).all()


def rounds(app, game_id):
    with Session(app.state.engine) as session:
        return session.exec(select(Round).where(Round.game_id == game_id).order_by(Round.number)).all()


# ---------------------------------------------------------------- shapes page

def test_shapes_need_a_login(client):
    assert client.get("/shapes", follow_redirects=False).status_code in (303, 401)


def test_a_shape_is_saved_listed_and_deleted(app, logged_in):
    r = post(logged_in, "/shapes", "/shapes?size=3", name="Corner", size="3", cell=["0", "2", "6", "8"])
    assert r.status_code == 303
    (shape,) = shapes(app)
    assert (shape.name, shape.size, list(shape.cell_list)) == ("Corner", 3, [0, 2, 6, 8])
    assert "Corner" in logged_in.get("/shapes?size=3").text
    assert post(logged_in, f"/shapes/{shape.id}/delete", "/shapes?size=3").status_code == 303
    assert shapes(app) == []


def test_bad_shapes_are_refused(app, logged_in):
    post(logged_in, "/shapes", "/shapes?size=3", name="", size="3", cell=["1"])
    post(logged_in, "/shapes", "/shapes?size=3", name="Empty", size="3")
    post(logged_in, "/shapes", "/shapes?size=3", name="Off", size="3", cell=["99"])
    assert shapes(app) == []
    post(logged_in, "/shapes", "/shapes?size=3", name="Dup", size="3", cell=["1"])
    post(logged_in, "/shapes", "/shapes?size=3", name="dup", size="3", cell=["2"])
    assert len(shapes(app)) == 1


def test_common_shapes_are_added_once(app, logged_in):
    post(logged_in, "/shapes/presets", "/shapes?size=5", size="5")
    first = len(shapes(app))
    assert first >= 5
    post(logged_in, "/shapes/presets", "/shapes?size=5", size="5")
    assert len(shapes(app)) == first


# ---------------------------------------------------------------- shape rounds

def make_game(app, logged_in, tmp_path, grid=3):
    ids = seed_songs(app, logged_in, tmp_path, 12)
    return game_id_from(create_game(logged_in, ids, grid_size=grid, tickets=6)), ids


def test_a_round_can_use_custom_shapes_and_keeps_its_own_copy(app, logged_in, tmp_path):
    game_id, _ = make_game(app, logged_in, tmp_path)
    post(logged_in, "/shapes", "/shapes?size=3", name="Top row", size="3", cell=["0", "1", "2"])
    shape_id = shapes(app)[0].id
    first = rounds(app, game_id)[0]
    r = post(logged_in, f"/games/{game_id}/rounds/{first.id}", f"/games/{game_id}", name="Shapes",
             mode="shapes", shape_ids=[str(shape_id)])
    assert r.status_code == 303
    rules = rounds(app, game_id)[0].rules()
    assert rules.mode == "shapes" and [s.name for s in rules.shapes] == ["Top row"]
    post(logged_in, f"/shapes/{shape_id}/delete", "/shapes?size=3")
    assert [s.name for s in rounds(app, game_id)[0].rules().shapes] == ["Top row"]


def test_a_shape_round_without_shapes_is_refused(app, logged_in, tmp_path):
    game_id, _ = make_game(app, logged_in, tmp_path)
    first = rounds(app, game_id)[0]
    post(logged_in, f"/games/{game_id}/rounds/{first.id}", f"/games/{game_id}", name="x", mode="shapes")
    assert rounds(app, game_id)[0].mode != "shapes"


def test_rules_can_switch_to_shapes_during_a_game(app, running_game):
    host, game_id, code = running_game
    post(host, "/shapes", f"/games/{game_id}/run", name="Top row", size="3", cell=["0", "1", "2"])
    shape_id = shapes(app)[0].id
    rnd = rounds(app, game_id)[0]
    r = host_post(host, game_id, "rules", round_id=str(rnd.id), name="R", mode="shapes", shape_ids=[str(shape_id)])
    assert r.status_code == 200
    assert rounds(app, game_id)[0].mode == "shapes"
    state = host.get(f"/games/{game_id}/run/state").json()
    assert state["shapes"][0]["name"] == "Top row"
    assert state["rounds"][0]["shapes"][0]["name"] == "Top row"


# ---------------------------------------------------------------- playlist editing

def spare(app):
    with Session(app.state.engine) as session:
        from app.models import Song
        return [s.id for s in session.exec(select(Song)).all()]


def test_songs_can_be_added_before_the_game_starts(app, logged_in, tmp_path):
    ids = seed_songs(app, logged_in, tmp_path, 14)
    game_id = game_id_from(create_game(logged_in, ids[:12], grid_size=3, tickets=4))
    r = post(logged_in, f"/games/{game_id}/playlist/add", f"/games/{game_id}", song_ids=[str(ids[12]), str(ids[13]), str(ids[0])])
    assert r.status_code == 303
    assert set(pool_ids(app, game_id)) == set(ids)  # the duplicate was ignored


def test_a_song_that_is_on_no_card_can_be_removed_but_not_below_the_minimum(app, logged_in, tmp_path):
    ids = seed_songs(app, logged_in, tmp_path, 14)
    game_id = game_id_from(create_game(logged_in, ids[:12], grid_size=3, tickets=1))
    post(logged_in, f"/games/{game_id}/playlist/add", f"/games/{game_id}", song_ids=[str(ids[12])])
    with Session(app.state.engine) as session:
        on_cards = {c for t in session.exec(select(Ticket).where(Ticket.game_id == game_id)).all() for c in t.cells}
    free = [i for i in pool_ids(app, game_id) if i not in on_cards]
    assert free
    post(logged_in, f"/games/{game_id}/playlist/remove", f"/games/{game_id}", song_id=str(free[0]))
    assert free[0] not in pool_ids(app, game_id)
    carded = next(iter(on_cards))
    post(logged_in, f"/games/{game_id}/playlist/remove", f"/games/{game_id}", song_id=str(carded))
    assert carded in pool_ids(app, game_id)  # it's on a card, so replace instead


def test_replacing_a_song_swaps_it_on_every_card(app, logged_in, tmp_path):
    ids = seed_songs(app, logged_in, tmp_path, 14)
    game_id = game_id_from(create_game(logged_in, ids[:12], grid_size=3, tickets=4))
    old, new = ids[0], ids[13]
    r = post(logged_in, f"/games/{game_id}/playlist/replace", f"/games/{game_id}", song_id=str(old), with_id=str(new))
    assert r.status_code == 303
    assert old not in pool_ids(app, game_id) and new in pool_ids(app, game_id)
    with Session(app.state.engine) as session:
        for t in session.exec(select(Ticket).where(Ticket.game_id == game_id)).all():
            assert old not in t.cells


def test_a_played_song_cannot_be_replaced_or_removed(app, running_game):
    host, game_id, _ = running_game
    assert host_post(host, game_id, "next").status_code == 200
    game = get_game(app, game_id)
    played = list(game.play_order)[0]
    before = set(pool_ids(app, game_id))
    post(host, f"/games/{game_id}/playlist/remove", f"/games/{game_id}", song_id=str(played))
    assert set(pool_ids(app, game_id)) == before


def test_a_finished_game_s_playlist_is_locked(app, running_game, tmp_path):
    host, game_id, _ = running_game
    assert host_post(host, game_id, "finish").status_code == 200
    seed_songs(app, host, tmp_path, 1)
    before = set(pool_ids(app, game_id))
    post(host, f"/games/{game_id}/playlist/add", f"/games/{game_id}", song_ids=[str(i) for i in spare(app) if i not in before])
    assert set(pool_ids(app, game_id)) == before


def test_the_game_page_shows_the_playlist_card(app, logged_in, tmp_path):
    game_id, _ = make_game(app, logged_in, tmp_path)
    html = logged_in.get(f"/games/{game_id}").text
    assert 'id="playlist"' in html and "Custom shape" in html


# ---------------------------------------------------------------- variables and markup

def test_unknown_variables_are_refused_in_footers(app, logged_in, tmp_path):
    game_id, _ = make_game(app, logged_in, tmp_path)
    post(logged_in, f"/games/{game_id}/card-footer", f"/games/{game_id}", ticket_footer="Hi ${BAR}")
    assert get_game(app, game_id).ticket_footer == ""
    post(logged_in, f"/games/{game_id}/card-footer", f"/games/{game_id}", ticket_footer="Next: ${GAME.NAME}")
    assert get_game(app, game_id).ticket_footer == "Next: ${GAME.NAME}"


def test_unknown_variables_are_refused_in_branding(app, logged_in):
    post(logged_in, "/branding", "/branding", header_text="${NOPE}", footer_text="")
    with Session(app.state.engine) as session:
        row = session.exec(select(Branding)).first()
    assert row is None or row.header_text != "${NOPE}"
    post(logged_in, "/branding", "/branding", header_text="Iron Horse - ${GAME.NAME}", footer_text="")
    with Session(app.state.engine) as session:
        assert session.exec(select(Branding)).first().header_text == "Iron Horse - ${GAME.NAME}"


def test_console_has_the_start_plays_option_and_new_game_says_select_all(app, running_game, logged_in):
    host, game_id, _ = running_game
    html = host.get(f"/games/{game_id}/run").text
    assert 'id="start-plays"' in html and "checked" in html.split('id="start-plays"')[1][:80]
    assert "Select all" in host.get("/games/new").text

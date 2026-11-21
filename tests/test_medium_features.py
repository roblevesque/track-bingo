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


# ---------------------------------------------------------------- Low tier: search, QR, fun facts

def test_library_search_supports_excluding_tags_and_untagged_songs(app, logged_in, tmp_path):
    ids = seed_songs(app, logged_in, tmp_path, 3)
    for song_id, tags in zip(ids, ["live,rock", "rock", ""]):
        post(logged_in, f"/library/{song_id}/edit", f"/library/{song_id}/edit", title=f"Track {song_id}", artist="A", tags=tags)
    html = logged_in.get("/library?q=%21live").text
    assert f"Track {ids[0]}" not in html and f"Track {ids[1]}" in html and f"Track {ids[2]}" in html
    html = logged_in.get("/library?q=no%3Atags").text
    assert f"Track {ids[2]}" in html and f"Track {ids[0]}" not in html and f"Track {ids[1]}" not in html


def test_a_fun_fact_is_saved_shown_on_the_edit_page_and_used_on_the_console(app, running_game):
    host, game_id, _ = running_game
    song_id = pool_ids(app, game_id)[0]
    r = post(host, f"/library/{song_id}/edit", f"/library/{song_id}/edit", title="T", artist="A", tags="",
             fun_fact="  Recorded\n in one take ")
    assert r.status_code == 303
    assert "Recorded in one take" in host.get(f"/library/{song_id}/edit").text
    too_long = post(host, f"/library/{song_id}/edit", f"/library/{song_id}/edit", title="T", artist="A", tags="", fun_fact="x" * 501)
    assert too_long.status_code == 400
    with Session(app.state.engine) as session:
        from app.models import Song
        assert session.get(Song, song_id).fun_fact == "Recorded in one take"
    state = host.get(f"/games/{game_id}/run/state").json()
    assert all("fun_fact" in s for s in state["upcoming"])


def test_the_remote_qr_code_needs_the_remote_on_and_a_host_login(app, running_game):
    host, game_id, _ = running_game
    assert host.get(f"/games/{game_id}/run/remote-qr.svg").status_code == 404  # remote still off
    assert host_post(host, game_id, "remote", mode="on").status_code == 200
    r = host.get(f"/games/{game_id}/run/remote-qr.svg")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml") and r.text.startswith("<svg")
    assert r.headers["cache-control"] == "no-store"
    assert new_player(app).get(f"/games/{game_id}/run/remote-qr.svg", follow_redirects=False).status_code in (303, 401, 403)
    assert 'id="remote-qr"' in host.get(f"/games/{game_id}/run").text


def test_the_pairing_page_fills_in_a_scanned_code(app, running_game):
    host, game_id, _ = running_game
    code = host_post(host, game_id, "remote", mode="on").json()["remote"]["code"]
    html = new_player(app).get(f"/remote?code={code}").text
    assert f'value="{code}"' in html and "Tap Connect" in html


def test_the_edit_page_offers_suggested_sections_and_serves_the_script(app, logged_in, tmp_path):
    ids = seed_songs(app, logged_in, tmp_path, 1)
    html = logged_in.get(f"/library/{ids[0]}/edit").text
    assert 'id="suggest"' in html and 'id="suggestions"' in html
    script = logged_in.get("/static/suggest.js")
    assert script.status_code == 200 and "export function suggestWindows" in script.text


# ---------------------------------------------------------------- planner

def planner_post(client, **fields):
    files = fields.pop("files", None)
    data = {"csrf_token": csrf_token(client, "/planner")}
    data.update(fields)
    return client.post("/planner", data=data, files=files, follow_redirects=False)


def titled(app, logged_in, tmp_path):
    """Three songs: 'Dancing Queen' by ABBA (tagged 70s), 'Killer Queen' by Queen, 'Waterloo' by ABBA."""
    ids = seed_songs(app, logged_in, tmp_path, 3)
    for song_id, (title, artist, tags) in zip(ids, [("Dancing Queen", "ABBA", "70s"), ("Killer Queen", "Queen", ""), ("Waterloo", "ABBA", "")]):
        post(logged_in, f"/library/{song_id}/edit", f"/library/{song_id}/edit", title=title, artist=artist, tags=tags)
    return ids


def test_the_planner_needs_a_login_and_offers_the_templates(app, logged_in, client):
    page = logged_in.get("/planner")
    assert page.status_code == 200 and "/planner/template.xlsx" in page.text and "/planner/template.csv" in page.text
    csv_file = logged_in.get("/planner/template.csv")
    assert csv_file.status_code == 200 and "Artist,Song" in csv_file.text and "attachment" in csv_file.headers["content-disposition"]
    xlsx = logged_in.get("/planner/template.xlsx")
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"
    assert new_player(app).get("/planner", follow_redirects=False).status_code in (303, 401, 403)


def test_a_pasted_sheet_is_checked_against_the_library(app, logged_in, tmp_path):
    titled(app, logged_in, tmp_path)
    r = planner_post(logged_in, action="check", pasted="Artist\tSong\nABBA\tdancing queen\nMadonna\tVogue\nQueen\n")
    assert r.status_code == 200
    html = r.text
    assert "In library" in html and "To get" in html and "Artist in library" in html
    assert "Madonna &ndash; Vogue" in html
    assert 'name="role_0"' in html and 'name="has_header"' in html


def test_an_uploaded_csv_works_and_bad_input_is_explained(app, logged_in, tmp_path):
    titled(app, logged_in, tmp_path)
    ok = planner_post(logged_in, action="check", files={"sheet": ("list.csv", b"Waterloo,ABBA\nVogue,Madonna\n", "text/csv")})
    assert ok.status_code == 200 and "Waterloo" in ok.text
    assert planner_post(logged_in, action="check").status_code == 400
    bad = planner_post(logged_in, action="check", files={"sheet": ("list.xlsx", b"nope", "application/octet-stream")})
    assert bad.status_code == 400 and "Excel" in bad.text


def test_columns_can_be_corrected_on_the_second_pass(app, logged_in, tmp_path):
    titled(app, logged_in, tmp_path)
    raw = "Waterloo\tABBA\nVogue\tMadonna"
    r = planner_post(logged_in, action="check", raw=raw, role_0="song", role_1="artist", overuse="3")
    assert "1 in the library" in r.text and "1 to get" in r.text
    swapped = planner_post(logged_in, action="check", raw=raw, role_0="artist", role_1="song", overuse="3")
    assert "0 in the library" in swapped.text


def test_ticked_songs_get_the_tag_and_the_page_shows_it(app, logged_in, tmp_path):
    ids = titled(app, logged_in, tmp_path)
    raw = "ABBA\tDancing Queen\nQueen\tKiller Queen"
    r = planner_post(logged_in, action="tag", raw=raw, role_0="artist", role_1="song", tag="Royalty Night",
                     song_ids=[str(ids[0]), str(ids[1])])
    assert r.status_code == 200 and "Added the tag" in r.text and "royalty night" in r.text
    with Session(app.state.engine) as session:
        from app.models import Song
        assert session.get(Song, ids[0]).tags == "70s,royalty night"
        assert session.get(Song, ids[1]).tags == "royalty night"
        assert session.get(Song, ids[2]).tags == ""
    assert "Type the tag" in planner_post(logged_in, action="tag", raw=raw, role_0="artist", role_1="song", song_ids=[str(ids[0])]).text


def test_the_songs_to_get_can_be_downloaded_as_csv(app, logged_in, tmp_path):
    titled(app, logged_in, tmp_path)
    r = planner_post(logged_in, action="csv", raw="ABBA\tWaterloo\nMadonna\tVogue\nPrince", role_0="artist", role_1="song")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lines = r.text.lstrip("﻿").splitlines()
    assert lines[0] == "Artist,Song,Note" and "Madonna,Vogue," in lines and "Prince,,any song by this artist" in lines
    assert not any("Waterloo" in line for line in lines)


def test_games_count_towards_how_often_a_song_was_used(app, running_game):
    host, game_id, _ = running_game
    song_id = pool_ids(app, game_id)[0]
    with Session(app.state.engine) as session:
        from app.models import Song
        song = session.get(Song, song_id)
        title, artist = song.title, song.artist
    html = planner_post(host, action="check", raw=f"{artist}\t{title}", role_0="artist", role_1="song", overuse="1").text
    assert "used in 1 game" in html and "heavily used" in html


# ---------------------------------------------------------------- the library search survives editing

def test_saving_or_deleting_a_song_returns_to_the_same_search(app, logged_in, tmp_path):
    ids = seed_songs(app, logged_in, tmp_path, 2)
    search = 'song !live !"classic rock"'  # matches both seeded songs ("song 00", "song 01") and has awkward characters
    html = logged_in.get("/library", params={"q": search}).text
    assert f"/library/{ids[0]}/edit?q=" in html  # the Edit links remember the search
    edit = logged_in.get(f"/library/{ids[0]}/edit", params={"q": search}).text
    assert 'name="q"' in edit and "Back to library" in edit and "classic rock" in edit
    saved = post(logged_in, f"/library/{ids[0]}/edit", f"/library/{ids[0]}/edit", title="T", artist="A", tags="x", q=search)
    assert saved.status_code == 303
    from urllib.parse import parse_qs, urlparse
    location = urlparse(saved.headers["location"])
    assert location.path == "/library" and parse_qs(location.query) == {"q": [search]}
    assert location.fragment == f"song-{ids[0]}"  # the page scrolls to the song just edited
    plain = post(logged_in, f"/library/{ids[1]}/edit", f"/library/{ids[1]}/edit", title="U", artist="A", tags="")
    assert plain.headers["location"] == f"/library#song-{ids[1]}"
    deleted = post(logged_in, f"/library/{ids[1]}/delete", "/library", q="tag one")
    assert parse_qs(urlparse(deleted.headers["location"]).query) == {"q": ["tag one"]}
    assert urlparse(deleted.headers["location"]).fragment == "songs"  # no song to show: the list itself
    page = logged_in.get("/library").text
    assert f'id="song-{ids[0]}"' in page and 'id="songs"' in page
    assert f'/library#song-{ids[0]}' in logged_in.get(f"/library/{ids[0]}/edit").text  # Back to library lands on the song


def test_a_search_cannot_be_used_to_redirect_elsewhere(app, logged_in, tmp_path):
    ids = seed_songs(app, logged_in, tmp_path, 1)
    r = post(logged_in, f"/library/{ids[0]}/edit", f"/library/{ids[0]}/edit", title="T", artist="A", tags="", q="https://evil.example/")
    assert r.headers["location"].startswith("/library?q=https%3A") and r.headers["location"].endswith(f"#song-{ids[0]}")


def test_the_songs_in_the_library_tab_and_its_csv(app, logged_in, tmp_path):
    titled(app, logged_in, tmp_path)
    raw = "ABBA\tDancing Queen\nMadonna\tVogue\nQueen\t"
    page = planner_post(logged_in, action="check", raw=raw, role_0="artist", role_1="song").text
    assert 'id="tab-get"' in page and 'id="tab-have"' in page and "Songs in library (2)" in page and "Songs to get (1)" in page
    r = planner_post(logged_in, action="csv_library", raw=raw, role_0="artist", role_1="song")
    assert r.status_code == 200 and "songs-in-library.csv" in r.headers["content-disposition"]
    lines = r.text.lstrip("\ufeff").splitlines()
    assert lines[0] == "Artist,Song,Tags,Games used,Status"
    assert "ABBA,Dancing Queen,70s,0,In library" in lines and "Queen,Killer Queen,,0,By the artist" in lines
    assert not any("Madonna" in line for line in lines)

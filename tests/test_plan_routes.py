from sqlmodel import Session, select

from app.models import Game, GameSong, Plan, Song
from tests.conftest import add_user, csrf_token, login, make_mp3, new_player, seed_songs, upload

SHEET = "ABBA\tDancing Queen\nMadonna\tVogue"


def post(client, path, csrf_from, **fields):
    data = {"csrf_token": csrf_token(client, csrf_from)}
    data.update(fields)
    return client.post(path, data=data, follow_redirects=False)


def retitle(client, song_id, title, artist="", tags=""):
    post(client, f"/library/{song_id}/edit", f"/library/{song_id}/edit", title=title, artist=artist, tags=tags)


def plans(app):
    with Session(app.state.engine) as session:
        return session.exec(select(Plan).order_by(Plan.id)).all()


def songs(app):
    with Session(app.state.engine) as session:
        return session.exec(select(Song).order_by(Song.id)).all()


def save(client, raw=SHEET, roles=("artist", "song"), name="Royalty night", tag="royalty night", **extra):
    fields = {"raw": raw, "plan_name": name, "tag": tag, "overuse": "3", **extra}
    fields.update({f"role_{i}": role for i, role in enumerate(roles)})
    return post(client, "/planner/plans/save", "/planner", **fields)


def plan_url(response):
    assert response.status_code == 303, response.text
    return response.headers["location"].split("#")[0]


def library_with_abba(app, client, tmp_path, extra=1):
    """'Dancing Queen' by ABBA, plus `extra` untitled songs (song 01...) to retitle later; returns the ids."""
    ids = seed_songs(app, client, tmp_path, 1 + extra)
    retitle(client, ids[0], "Dancing Queen", "ABBA")
    return ids


def row_post(client, url, action, key, tab="get", **fields):
    return post(client, f"{url}/row", url, action=action, key=key, tab=tab, **fields)


# ---------------------------------------------------------------- saving and listing

def test_plans_need_a_login(client):
    assert client.get("/planner/plans", follow_redirects=False).status_code in (303, 401)
    assert client.get("/planner/plans/1", follow_redirects=False).status_code in (303, 401)


def test_a_checked_sheet_is_saved_as_a_plan_and_listed(app, logged_in, tmp_path):
    library_with_abba(app, logged_in, tmp_path)
    url = plan_url(save(logged_in))
    (plan,) = plans(app)
    assert (plan.name, plan.tag, plan.roles, plan.has_header) == ("Royalty night", "royalty night", "artist,song", False)
    page = logged_in.get(url).text
    assert "1 of 2 ready" in page and "Royalty night" in page
    listing = logged_in.get("/planner/plans").text
    assert "Royalty night" in listing and "1 of 2 ready" in listing
    assert "/planner/plans" in logged_in.get("/planner").text


def test_a_plan_needs_a_name_and_a_sheet(app, logged_in):
    assert save(logged_in, name="").headers["location"] == "/planner"
    assert save(logged_in, raw="").headers["location"] == "/planner"
    assert plans(app) == []


def test_the_check_page_offers_to_save_the_plan(app, logged_in, tmp_path):
    library_with_abba(app, logged_in, tmp_path)
    html = post(logged_in, "/planner", "/planner", action="check", raw=SHEET, role_0="artist", role_1="song").text
    assert "/planner/plans/save" in html and 'name="plan_name"' in html


# ---------------------------------------------------------------- live progress

def test_a_song_uploaded_later_ticks_its_line_off_by_itself(app, logged_in, tmp_path):
    ids = library_with_abba(app, logged_in, tmp_path)
    url = plan_url(save(logged_in))
    assert "1 of 2 ready" in logged_in.get(url).text
    retitle(logged_in, ids[1], "Vogue", "Madonna")
    page = logged_in.get(url).text
    assert "2 of 2 ready" in page and "Nothing left to get" in page


def test_uploading_from_a_plan_adds_its_theme_tag_and_returns_to_the_plan(app, logged_in, tmp_path):
    library_with_abba(app, logged_in, tmp_path, extra=0)
    url = plan_url(save(logged_in))
    assert 'name="plan_id"' in logged_in.get(url).text
    data = make_mp3(tmp_path / "new.mp3").read_bytes()
    r = logged_in.post("/library/upload", data={"csrf_token": csrf_token(logged_in, url), "plan_id": url.rsplit("/", 1)[1],
                                                 "tags": "80s"},
                       files=[("files", ("vogue.mp3", data, "audio/mpeg"))], follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == url
    new = songs(app)[-1]
    assert set(new.tag_list) == {"80s", "royalty night"}
    xhr = logged_in.post("/library/upload", data={"csrf_token": csrf_token(logged_in, url), "plan_id": url.rsplit("/", 1)[1]},
                         files=[("files", ("two.mp3", data, "audio/mpeg"))], headers={"x-requested-with": "xhr"})
    assert xhr.json() == {"redirect": url}


def test_an_unknown_plan_on_upload_is_just_ignored(app, logged_in, tmp_path):
    data = make_mp3(tmp_path / "x.mp3").read_bytes()
    r = logged_in.post("/library/upload", data={"csrf_token": csrf_token(logged_in, "/library"), "plan_id": "999"},
                       files=[("files", ("a.mp3", data, "audio/mpeg"))], follow_redirects=False)
    assert r.headers["location"] == "/library"


# ---------------------------------------------------------------- choosing

def test_choosing_a_song_for_an_artist_line_and_undoing_it(app, logged_in, tmp_path):
    ids = library_with_abba(app, logged_in, tmp_path)
    url = plan_url(save(logged_in, raw="ABBA", roles=("artist",)))
    page = logged_in.get(url).text
    assert "0 of 1 ready" in page and "Use this" in page
    key = "abba|"
    r = row_post(logged_in, url, "use", key, tab="confirm", song_id=str(ids[0]))
    assert r.status_code == 303 and r.headers["location"].endswith("#panel-confirm")
    page = logged_in.get(url).text
    assert "1 of 1 ready" in page and "your choice" in page
    row_post(logged_in, url, "reset", key, tab="ready")
    assert "0 of 1 ready" in logged_in.get(url).text
    row_post(logged_in, url, "none", key, tab="confirm")
    page = logged_in.get(url).text
    assert "0 of 1 ready" in page and "any song by this artist" in page


def test_none_of_these_sends_a_ready_line_back_to_get(app, logged_in, tmp_path):
    library_with_abba(app, logged_in, tmp_path)
    url = plan_url(save(logged_in))
    row_post(logged_in, url, "none", "abba|dancing queen", tab="ready")
    assert "0 of 2 ready" in logged_in.get(url).text


def test_a_song_that_is_not_in_the_library_cannot_be_chosen(app, logged_in, tmp_path):
    library_with_abba(app, logged_in, tmp_path)
    url = plan_url(save(logged_in, raw="ABBA", roles=("artist",)))
    row_post(logged_in, url, "use", "abba|", tab="confirm", song_id="9999")
    assert "0 of 1 ready" in logged_in.get(url).text
    assert row_post(logged_in, url, "bogus", "abba|").status_code == 400


def test_lines_can_be_removed_and_put_back(app, logged_in, tmp_path):
    library_with_abba(app, logged_in, tmp_path)
    url = plan_url(save(logged_in))
    row_post(logged_in, url, "skip", "madonna|vogue")
    page = logged_in.get(url).text
    assert "1 of 1 ready" in page and "Removed (1)" in page
    row_post(logged_in, url, "restore", "madonna|vogue", tab="dropped")
    assert "1 of 2 ready" in logged_in.get(url).text


def test_replacing_the_sheet_keeps_decisions(app, logged_in, tmp_path):
    ids = library_with_abba(app, logged_in, tmp_path)
    url = plan_url(save(logged_in, raw="ABBA", roles=("artist",)))
    row_post(logged_in, url, "use", "abba|", tab="confirm", song_id=str(ids[0]))
    r = post(logged_in, f"{url}/sheet", url, pasted="Queen\t\nABBA\t")
    assert r.status_code == 303
    page = logged_in.get(url).text
    assert "1 of 2 ready" in page  # ABBA keeps the choice; Queen has nothing in the library
    assert post(logged_in, f"{url}/sheet", url).status_code == 303  # nothing given: a message, no change


# ---------------------------------------------------------------- tags and settings

def test_the_ready_songs_can_be_tagged_with_the_plan_tag(app, logged_in, tmp_path):
    library_with_abba(app, logged_in, tmp_path)
    url = plan_url(save(logged_in))
    assert post(logged_in, f"{url}/tag", url).status_code == 303
    assert songs(app)[0].tag_list == ["royalty night"]
    assert songs(app)[1].tag_list == []  # not on the sheet
    assert "1 of the 1 ready songs already have" in logged_in.get(url).text


def test_tagging_needs_a_theme_tag(app, logged_in, tmp_path):
    library_with_abba(app, logged_in, tmp_path)
    url = plan_url(save(logged_in, tag=""))
    post(logged_in, f"{url}/tag", url)
    assert songs(app)[0].tag_list == []


def test_settings_rename_retag_and_change_the_flag_threshold(app, logged_in, tmp_path):
    library_with_abba(app, logged_in, tmp_path)
    url = plan_url(save(logged_in))
    post(logged_in, f"{url}/settings", url, plan_name="Kings", tag="Kings Night, extra", overuse="5")
    (plan,) = plans(app)
    assert (plan.name, plan.tag, plan.overuse) == ("Kings", "kings night", 5)
    post(logged_in, f"{url}/settings", url, plan_name="", tag="x", overuse="5")
    assert plans(app)[0].name == "Kings"


def test_songs_to_get_download_is_a_csv(app, logged_in, tmp_path):
    library_with_abba(app, logged_in, tmp_path)
    url = plan_url(save(logged_in))
    r = logged_in.get(f"{url}/songs-to-get.csv")
    assert r.status_code == 200 and "Madonna" in r.text and "Dancing Queen" not in r.text
    assert "attachment" in r.headers["content-disposition"]


# ---------------------------------------------------------------- creating a game

def test_a_game_is_created_from_the_ready_songs(app, logged_in, tmp_path):
    ids = seed_songs(app, logged_in, tmp_path, 10)
    raw = "\n".join(f"song {i:02d}" for i in range(10))  # the last line is a song that doesn't exist yet
    raw += "\nSong Nobody Has"
    url = plan_url(save(logged_in, raw=raw, roles=("song",), name="Ten songs"))
    page = logged_in.get(url).text
    assert "10 of 11 ready" in page and "Uses the 10 ready songs" in page
    r = post(logged_in, f"{url}/game", url, game_name="Ten songs night", grid_size="3", ticket_count="4")
    assert r.status_code == 303 and r.headers["location"].startswith("/games/")
    game_id = int(r.headers["location"].rsplit("/", 1)[1])
    with Session(app.state.engine) as session:
        game = session.get(Game, game_id)
        pool = {gs.song_id for gs in session.exec(select(GameSong).where(GameSong.game_id == game_id)).all()}
        assert (game.name, game.grid_size) == ("Ten songs night", 3) and pool == set(ids)
        assert session.get(Plan, int(url.rsplit("/", 1)[1])).game_id == game_id
    assert "A game was made from this plan" in logged_in.get(url).text


def test_too_few_ready_songs_cannot_make_a_game(app, logged_in, tmp_path):
    library_with_abba(app, logged_in, tmp_path)
    url = plan_url(save(logged_in))
    r = post(logged_in, f"{url}/game", url, game_name="Tiny", grid_size="3", ticket_count="4")
    assert r.status_code == 303 and r.headers["location"].startswith(url)
    assert "needs at least 9 different songs" in logged_in.get(url).text
    with Session(app.state.engine) as session:
        assert session.exec(select(Game)).all() == []


def test_bad_game_settings_are_refused(app, logged_in, tmp_path):
    seed_songs(app, logged_in, tmp_path, 10)
    url = plan_url(save(logged_in, raw="\n".join(f"song {i:02d}" for i in range(10)), roles=("song",)))
    for fields in ({"game_name": "", "grid_size": "3", "ticket_count": "4"},
                   {"game_name": "x", "grid_size": "2", "ticket_count": "4"},
                   {"game_name": "x", "grid_size": "3", "ticket_count": "0"},
                   {"game_name": "x", "grid_size": "abc", "ticket_count": "4"}):
        assert post(logged_in, f"{url}/game", url, **fields).headers["location"].startswith(url)
    with Session(app.state.engine) as session:
        assert session.exec(select(Game)).all() == []


def test_someone_who_cannot_create_games_cannot_make_one_from_a_plan(app, logged_in, tmp_path):
    seed_songs(app, logged_in, tmp_path, 10)
    url = plan_url(save(logged_in, raw="\n".join(f"song {i:02d}" for i in range(10)), roles=("song",)))
    add_user(app, username="guest", can_create_games=False)
    guest = new_player(app)
    login(guest, "guest")
    r = guest.post(f"{url}/game", data={"csrf_token": csrf_token(guest, url), "game_name": "x", "grid_size": "3",
                                       "ticket_count": "4"}, follow_redirects=False)
    assert r.status_code in (303, 401, 403) and not (r.status_code == 303 and r.headers["location"].startswith("/games/"))
    with Session(app.state.engine) as session:
        assert session.exec(select(Game)).all() == []


# ---------------------------------------------------------------- sharing and deleting

def test_everyone_sees_plans_but_only_the_creator_or_an_admin_deletes(app, logged_in, tmp_path):
    url = plan_url(save(logged_in))
    add_user(app, username="second")
    other = new_player(app)
    login(other, "second")
    assert "Royalty night" in other.get("/planner/plans").text
    page = other.get(url).text
    assert "Delete the plan" not in page
    denied = other.post(f"{url}/delete", data={"csrf_token": csrf_token(other, url)}, follow_redirects=False)
    assert denied.status_code == 403 and len(plans(app)) == 1
    assert post(logged_in, f"{url}/delete", url).headers["location"] == "/planner/plans"
    assert plans(app) == []
    assert logged_in.get(url).status_code == 404

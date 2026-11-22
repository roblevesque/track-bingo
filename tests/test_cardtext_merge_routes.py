import json
import re

from sqlmodel import Session, select

from app.models import Branding, Game, GameSong, Plan, Song, Ticket
from tests.conftest import (
    add_user, all_songs, create_game, csrf_token, game_id_from, get_game, join_game, login, make_mp3, new_player,
    seed_songs, upload,
)


def post(client, path, csrf_from, **fields):
    data = {"csrf_token": csrf_token(client, csrf_from)}
    data.update(fields)
    return client.post(path, data=data, follow_redirects=False)


def edit(client, song_id, **fields):
    form = {"title": f"song {song_id}", "artist": "", "tags": "", "start": "", "end": ""}
    form.update(fields)
    return post(client, f"/library/{song_id}/edit", f"/library/{song_id}/edit", **form)


def brand_row(app):
    with Session(app.state.engine) as session:
        return session.exec(select(Branding)).first()


def save_branding(client, **fields):
    data = {"header_text": "", "footer_text": ""}
    data.update(fields)
    return post(client, "/branding", "/branding", **data)


# ---------------------------------------------------------------- song and band name looks

def test_the_branding_page_offers_the_text_looks_with_the_defaults(logged_in):
    page = logged_in.get("/branding").text
    for name in ("title_font", "title_style", "title_size", "title_color", "artist_font", "artist_style", "artist_size", "artist_color"):
        assert f'name="{name}"' in page
    assert re.search(r'<option value="bold"\s+selected', page) and "pv-song" in page


def test_text_looks_are_saved_and_shown_again(app, logged_in):
    r = save_branding(logged_in, title_font="serif", title_style="bold-italic", title_size="18", title_color="#8B0000",
                      artist_font="mono", artist_style="regular", artist_size="", artist_color="#006400")
    assert r.status_code == 303
    stored = json.loads(brand_row(app).text_style_json)
    assert stored["title"] == {"family": "serif", "style": "bold-italic", "size": 18.0, "color": "#8b0000"}
    assert stored["artist"]["family"] == "mono" and stored["artist"]["size"] is None
    page = logged_in.get("/branding").text
    assert re.search(r'<option value="serif"\s+selected', page) and 'value="#8b0000"' in page and 'value="18"' in page


def test_default_looks_store_nothing_and_bad_values_are_refused(app, logged_in):
    save_branding(logged_in)
    assert brand_row(app).text_style_json == ""
    for bad in ({"title_font": "comic"}, {"artist_size": "99"}, {"title_color": "red"}, {"artist_style": "heavy"}, {"title_size": "abc"}):
        assert save_branding(logged_in, **bad).status_code == 400
    assert brand_row(app).text_style_json == ""


def make_game(app, host, tmp_path, count=12, grid=3):
    ids = seed_songs(app, host, tmp_path, count)
    for n, song_id in enumerate(ids):
        edit(host, song_id, title=f"Song {n:02d}", artist=f"Band {n:02d}" if n != 0 else "")
    return game_id_from(create_game(host, ids, name="Pub Night", grid_size=grid, tickets=4))


def test_styled_cards_and_the_preview_still_print(app, logged_in, tmp_path):
    game_id = make_game(app, logged_in, tmp_path)
    save_branding(logged_in, title_font="serif", title_style="italic", title_size="16", title_color="#112233",
                  artist_font="mono", artist_style="bold", artist_size="9", artist_color="#445566")
    assert logged_in.get(f"/games/{game_id}/cards.pdf").content.startswith(b"%PDF")
    assert logged_in.get("/branding/preview.pdf").content.startswith(b"%PDF")


# ---------------------------------------------------------------- band names only

def test_a_game_can_print_band_names_only(app, logged_in, tmp_path):
    game_id = make_game(app, logged_in, tmp_path)
    assert get_game(app, game_id).card_content == "both"
    assert f'action="/games/{game_id}/card-content"' in logged_in.get(f"/games/{game_id}").text
    assert post(logged_in, f"/games/{game_id}/card-content", f"/games/{game_id}", card_content="artist").status_code == 303
    assert get_game(app, game_id).card_content == "artist"
    assert logged_in.get(f"/games/{game_id}/cards.pdf").content.startswith(b"%PDF")
    assert re.search(r'value="artist"\s+checked', logged_in.get(f"/games/{game_id}").text)


def test_an_unknown_card_content_is_refused(app, logged_in, tmp_path):
    game_id = make_game(app, logged_in, tmp_path)
    post(logged_in, f"/games/{game_id}/card-content", f"/games/{game_id}", card_content="artist")
    post(logged_in, f"/games/{game_id}/card-content", f"/games/{game_id}", card_content="nonsense")
    assert get_game(app, game_id).card_content == "artist"


def squares(html):
    return re.findall(r'<button type="button" class="square[^>]*>\s*<strong>(.*?)</strong><span>(.*?)</span>', html, re.S)


def test_players_see_band_names_only_when_the_game_prints_them(app, logged_in, tmp_path):
    game_id = make_game(app, logged_in, tmp_path)
    code = get_game(app, game_id).code
    player = new_player(app)
    join_game(player, code)
    both = squares(player.get(f"/play/{code}").text)
    assert all(title.startswith("Song") for title, _ in both) and any(artist.startswith("Band") for _, artist in both)
    post(logged_in, f"/games/{game_id}/card-content", f"/games/{game_id}", card_content="artist")
    only = squares(player.get(f"/play/{code}").text)
    assert len(only) == 9
    assert all(artist == "" for _, artist in only)
    assert all(main.startswith("Band") or main.startswith("Song 00") for main, _ in only)  # song 00 has no band: its title shows
    post(logged_in, f"/games/{game_id}/card-content", f"/games/{game_id}", card_content="title")
    assert all(title.startswith("Song") and artist == "" for title, artist in squares(player.get(f"/play/{code}").text))


# ---------------------------------------------------------------- merging duplicates

def distinct(i):
    return make_bytes() + bytes([i]) * (i + 3)


def make_bytes():
    frame = b"\xff\xfb\x90\x00" + b"\x00" * 413
    return frame * 40


def songs_by_name(app):
    return {s.original_name: s for s in all_songs(app)}


def setup_library(app, client, tmp_path, copies=3, others=12):
    """`copies` identical files a1.mp3...; then `others` different songs o00.mp3... Returns (copy ids, other ids)."""
    for n in range(1, copies + 1):
        upload(client, f"a{n}.mp3", make_bytes())
    for n in range(others):
        upload(client, f"o{n:02d}.mp3", distinct(n))
    by = songs_by_name(app)
    return [by[f"a{n}.mp3"].id for n in range(1, copies + 1)], [by[f"o{n:02d}.mp3"].id for n in range(others)]


def merge(client, ids, keeper):
    return post(client, "/library/duplicates/merge", "/library/duplicates", ids=[str(i) for i in ids], keeper_id=str(keeper))


def song_ids(app):
    return {s.id for s in all_songs(app)}


def test_the_page_lists_a_merge_form_with_the_best_copy_preselected(app, logged_in, tmp_path):
    copies, others = setup_library(app, logged_in, tmp_path)
    game_id = game_id_from(create_game(logged_in, [copies[1]] + others[:10], grid_size=3, tickets=3))
    page = logged_in.get("/library/duplicates").text
    assert 'action="/library/duplicates/merge"' in page and "Merge all identical files" in page
    assert re.search(rf'value="{copies[1]}" form="merge-1"\s+checked', page)  # the copy already in a game is the default
    assert game_id


def test_merging_combines_tags_and_points_games_cards_and_plans_at_the_kept_song(app, logged_in, tmp_path):
    copies, others = setup_library(app, logged_in, tmp_path)
    a1, a2, a3 = copies
    edit(logged_in, a1, title="Keeper", tags="80s")
    edit(logged_in, a2, title="Copy two", tags="rock, 80s", artist="ABBA", start="0.2")
    edit(logged_in, a3, title="Copy three", tags="pop")
    game_id = game_id_from(create_game(logged_in, [a2] + others[:10], grid_size=3, tickets=4))
    with Session(app.state.engine) as session:
        session.add(Plan(owner_id=1, name="P", choices_json=json.dumps({"abba|": a2, "x|y": 0})))
        session.commit()
        clip = session.get(Song, a3).filename
    r = merge(logged_in, copies, a1)
    assert r.status_code == 303 and r.headers["location"] == "/library/duplicates"
    assert song_ids(app).isdisjoint({a2, a3}) and a1 in song_ids(app)
    with Session(app.state.engine) as session:
        keeper = session.get(Song, a1)
        assert set(keeper.tag_list) == {"80s", "rock", "pop"} and keeper.artist == "ABBA" and keeper.start_ms == 200
        pool = set(session.exec(select(GameSong.song_id).where(GameSong.game_id == game_id)).all())
        assert pool == {a1, *others[:10]}
        cells = [c for t in session.exec(select(Ticket).where(Ticket.game_id == game_id)).all() for c in t.cells]
        assert a2 not in cells and a1 in cells
        game = session.get(Game, game_id)
        assert a2 not in game.play_order and a1 in game.play_order
        assert json.loads(session.exec(select(Plan)).one().choices_json) == {"abba|": a1, "x|y": 0}
    assert not (app.state.settings.clips_dir / clip).exists()
    assert "Merged 3 songs" in logged_in.get("/library/duplicates").text


def test_a_game_holding_two_copies_blocks_the_merge_and_nothing_changes(app, logged_in, tmp_path):
    copies, others = setup_library(app, logged_in, tmp_path)
    a1, a2, a3 = copies
    create_game(logged_in, [a1, a2] + others[:9], grid_size=3, tickets=3)
    before = song_ids(app)
    merge(logged_in, copies, a1)
    page = logged_in.get("/library/duplicates").text
    assert "can&#39;t hold a song twice" in page or "can't hold a song twice" in page
    assert song_ids(app) == before
    assert "disabled" in page  # the merge button is switched off for this group


def test_only_an_uploader_or_an_admin_can_merge_a_song_away(app, logged_in, tmp_path):
    copies, _ = setup_library(app, logged_in, tmp_path, copies=2, others=0)
    add_user(app, username="second")
    other = new_player(app)
    login(other, "second")
    before = song_ids(app)
    post(other, "/library/duplicates/merge", "/library/duplicates", ids=[str(i) for i in copies], keeper_id=str(copies[0]))
    assert song_ids(app) == before
    assert "Only the person who uploaded" in other.get("/library/duplicates").text


def test_merge_needs_two_songs_and_a_keeper_among_them(app, logged_in, tmp_path):
    copies, others = setup_library(app, logged_in, tmp_path, copies=2, others=1)
    before = song_ids(app)
    merge(logged_in, [copies[0]], copies[0])
    merge(logged_in, copies, others[0])
    post(logged_in, "/library/duplicates/merge", "/library/duplicates", ids=["1", "2"], keeper_id="abc")
    assert song_ids(app) == before


def test_merge_all_folds_every_identical_group_and_leaves_blocked_ones(app, logged_in, tmp_path):
    copies, others = setup_library(app, logged_in, tmp_path, copies=2, others=12)
    upload(logged_in, "b1.mp3", make_bytes() + b"\x01" * 40)
    upload(logged_in, "b2.mp3", make_bytes() + b"\x01" * 40)
    by = songs_by_name(app)
    b1, b2 = by["b1.mp3"].id, by["b2.mp3"].id
    create_game(logged_in, [b1, b2] + others[:9], grid_size=3, tickets=3)  # holds both b copies: blocked
    r = post(logged_in, "/library/duplicates/merge-all", "/library/duplicates")
    assert r.status_code == 303
    remaining = song_ids(app)
    assert len({copies[0], copies[1]} & remaining) == 1  # the a pair became one song
    assert {b1, b2} <= remaining  # the blocked pair is untouched
    page = logged_in.get("/library/duplicates").text
    assert "Merged 1 group" in page and "Left 1 alone" in page


def test_merge_all_with_nothing_to_do_says_so(app, logged_in, tmp_path):
    seed = make_mp3(tmp_path / "x.mp3").read_bytes()
    upload(logged_in, "one.mp3", seed)
    assert post(logged_in, "/library/duplicates/merge-all", "/library/duplicates").status_code == 303
    assert "no identical files to merge" in logged_in.get("/library/duplicates").text

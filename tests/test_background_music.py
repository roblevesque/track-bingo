from tests.conftest import add_user, create_game, csrf_token, game_id_from, login, new_player, seed_songs


def tracks(client, game_id):
    response = client.get(f"/games/{game_id}/run/background")
    assert response.status_code == 200
    return response.json()["songs"]


def game_with_spare_songs(app, host, tmp_path, spare=12, pool=10):
    """A game whose pool is `pool` songs, in a library that has `spare` more. Returns (game id, pool ids, spare ids)."""
    ids = seed_songs(app, host, tmp_path, pool + spare)
    game_id = game_id_from(create_game(host, ids[:pool], grid_size=3, tickets=2))  # 9 songs would allow only one distinct card
    return game_id, ids[:pool], ids[pool:]


def test_the_songs_outside_the_game_come_back_shuffled_each_time(app, logged_in, tmp_path):
    game_id, _pool, spare = game_with_spare_songs(app, logged_in, tmp_path)
    first, second = tracks(logged_in, game_id), tracks(logged_in, game_id)
    assert {t["id"] for t in first} == {t["id"] for t in second} == set(spare) and len(first) == 12
    assert all({"title", "artist", "audio_url"} <= set(t) and t["audio_url"] == f"/library/{t['id']}/audio" for t in first)
    assert [t["id"] for t in first] != [t["id"] for t in second]  # a fresh order each time (a 1-in-479-million chance of a false failure)


def test_songs_in_the_games_playlist_are_left_out(app, logged_in, tmp_path):
    game_id, pool, _spare = game_with_spare_songs(app, logged_in, tmp_path)
    assert not {t["id"] for t in tracks(logged_in, game_id)} & set(pool)
    assert logged_in.get(f"/games/{game_id}/run/background").json()["excluded"] == 10


def test_a_library_that_is_all_in_the_game_has_nothing_left_to_play(running_game):
    host, game_id, _code = running_game  # all 12 library songs are in this game
    data = host.get(f"/games/{game_id}/run/background").json()
    assert data["songs"] == [] and data["excluded"] == 12


def test_the_playlist_change_is_picked_up_by_background_music(app, logged_in, tmp_path):
    game_id, pool, spare = game_with_spare_songs(app, logged_in, tmp_path)
    token = csrf_token(logged_in, f"/games/{game_id}")
    logged_in.post(f"/games/{game_id}/playlist/add", data={"song_ids": [str(spare[0])], "csrf_token": token})
    assert spare[0] not in {t["id"] for t in tracks(logged_in, game_id)}  # now in the game, so not background music


def test_every_host_gets_the_songs_outside_the_game(app, logged_in, tmp_path):
    game_id, _pool, spare = game_with_spare_songs(app, logged_in, tmp_path)
    add_user(app, "other")
    other = new_player(app)
    login(other, "other")
    assert {t["id"] for t in tracks(other, game_id)} == set(spare)


def test_another_host_can_use_the_game_and_login_is_required(app, running_game):
    host, game_id, _code = running_game
    add_user(app, "other")
    other = new_player(app)
    login(other, "other")
    assert other.get(f"/games/{game_id}/run/background").status_code == 200
    assert new_player(app).get(f"/games/{game_id}/run/background", follow_redirects=False).status_code == 303


def test_the_console_has_the_background_music_card(running_game):
    host, game_id, _code = running_game
    page = host.get(f"/games/{game_id}/run").text
    for element in ('id="bg-card"', 'id="bg-play"', 'id="bg-audio"', 'id="bg-volume"', 'id="bg-after"'):
        assert element in page

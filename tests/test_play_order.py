"""Arranging the play order from the game page: before the start (Start keeps it) and during a game (unplayed songs only)."""
import random

import pytest

from app.services.playlist import planned_order, reorder_remaining
from tests.conftest import (
    create_game, csrf_token, game_id_from, get_game, host_post, pool_ids, seed_songs, set_played_count,
)


def save_order(client, game_id, song_ids, expect):
    data = {"csrf_token": csrf_token(client, f"/games/{game_id}"), "song_ids": [str(i) for i in song_ids],
            "expect": str(expect)}
    return client.post(f"/games/{game_id}/playlist/order", data=data, follow_redirects=False)


@pytest.fixture
def draft_game(app, logged_in, tmp_path):
    ids = seed_songs(app, logged_in, tmp_path, 12)
    return logged_in, game_id_from(create_game(logged_in, ids, grid_size=3, tickets=6))


# ---------------------------------------------------------------- pure functions

def test_reorder_keeps_the_played_songs_and_takes_the_new_tail():
    assert reorder_remaining([1, 2, 3, 4, 5], 2, [5, 3, 4]) == [1, 2, 5, 3, 4]


@pytest.mark.parametrize("tail", [[5, 3], [5, 3, 4, 4], [5, 3, 1], [5, 3, 9], [3, 3, 4]])
def test_reorder_refuses_anything_but_the_unplayed_songs_once_each(tail):
    with pytest.raises(ValueError):
        reorder_remaining([1, 2, 3, 4, 5], 2, tail)


def test_a_planned_order_is_kept_and_mended():
    assert planned_order([3, 1, 2], [1, 2, 3]) == [3, 1, 2]
    mended = planned_order([3, 9, 1, 3], [1, 2, 3], random.Random(1))  # 9 left the pool, 2 joined it, 3 repeated
    assert sorted(mended) == [1, 2, 3] and [s for s in mended if s != 2] == [3, 1]
    assert sorted(planned_order([], [4, 5, 6])) == [4, 5, 6]  # no plan: a shuffle


# ---------------------------------------------------------------- before the start

def test_a_draft_order_is_saved_and_used_by_start(app, draft_game):
    host, game_id = draft_game
    wanted = list(reversed(sorted(pool_ids(app, game_id))))
    assert save_order(host, game_id, wanted, 0).status_code == 303
    assert get_game(app, game_id).play_order == wanted
    page = host.get(f"/games/{game_id}").text
    assert "will play the songs in this order" in page and "Forget this order" in page
    assert host_post(host, game_id, "start").status_code == 200
    game = get_game(app, game_id)
    assert (game.status, game.play_order) == ("active", wanted)


def test_a_draft_order_must_hold_every_song_once(app, draft_game):
    host, game_id = draft_game
    pool = pool_ids(app, game_id)
    save_order(host, game_id, pool[:-1], 0)
    save_order(host, game_id, pool[:-1] + [pool[0]], 0)
    assert get_game(app, game_id).play_order == []


def test_forgetting_a_draft_order_goes_back_to_a_shuffle(app, draft_game):
    host, game_id = draft_game
    save_order(host, game_id, pool_ids(app, game_id), 0)
    r = host.post(f"/games/{game_id}/playlist/order/clear",
                  data={"csrf_token": csrf_token(host, f"/games/{game_id}")}, follow_redirects=False)
    assert r.status_code == 303 and get_game(app, game_id).play_order == []
    assert "No order set yet" in host.get(f"/games/{game_id}").text


def test_songs_added_to_a_planned_draft_join_its_order(app, logged_in, tmp_path):
    ids = seed_songs(app, logged_in, tmp_path, 13)
    game_id = game_id_from(create_game(logged_in, ids[:12], grid_size=3, tickets=4))
    save_order(logged_in, game_id, ids[:12], 0)
    logged_in.post(f"/games/{game_id}/playlist/add", data={
        "csrf_token": csrf_token(logged_in, f"/games/{game_id}"), "song_ids": [str(ids[12])]})
    order = get_game(app, game_id).play_order
    assert sorted(order) == sorted(ids) and [s for s in order if s != ids[12]] == ids[:12]


# ---------------------------------------------------------------- during a game

def test_only_the_songs_still_to_come_can_be_rearranged(app, running_game):
    host, game_id, _ = running_game
    set_played_count(app, game_id, 3)
    order = get_game(app, game_id).play_order
    new_tail = list(reversed(order[3:]))
    assert save_order(host, game_id, new_tail, 3).status_code == 303
    assert get_game(app, game_id).play_order == order[:3] + new_tail
    state = host.get(f"/games/{game_id}/run/state").json()
    assert [s["id"] for s in state["upcoming"]] == new_tail  # the console sees the new order


def test_a_stale_page_saves_nothing(app, running_game):
    host, game_id, _ = running_game
    set_played_count(app, game_id, 3)
    order = get_game(app, game_id).play_order
    save_order(host, game_id, list(reversed(order[2:])), 2)  # the page was opened before the third song played
    save_order(host, game_id, list(reversed(order)), 3)  # tries to move played songs
    assert get_game(app, game_id).play_order == order
    page = host.get(f"/games/{game_id}").text
    assert "Already played (3)" in page


def test_a_finished_game_s_order_is_locked(app, running_game):
    host, game_id, _ = running_game
    order = get_game(app, game_id).play_order
    save_order(host, game_id, list(reversed(order)), 0)  # still allowed: nothing played yet
    order = get_game(app, game_id).play_order
    assert host_post(host, game_id, "finish").status_code == 200
    save_order(host, game_id, list(reversed(order)), 0)
    assert get_game(app, game_id).play_order == order
    assert 'id="order-form"' not in host.get(f"/games/{game_id}").text

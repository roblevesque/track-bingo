"""Evening out clip volumes: measurements, the host's nudge, and the gain the console plays each song at."""
from types import SimpleNamespace

import pytest
from sqlalchemy import inspect, text
from sqlmodel import Session

from app.db import apply_additive_migrations, make_engine
from app.models import Song
from app.services.loudness import describe, is_measured, parse_adjust, parse_loudness, playback_gain_db, window_key
from tests.conftest import create_game, csrf_token, game_id_from, host_post, seed_songs


def song(**fields):
    base = {"start_ms": 30000, "end_ms": 60000, "loudness_db": None, "loudness_for": "", "volume_adjust_db": 0.0}
    return SimpleNamespace(**(base | fields))


def test_a_measured_song_is_brought_to_the_target():
    loud = song(loudness_db=-8.0, loudness_for="30000:60000")
    quiet = song(loudness_db=-21.0, loudness_for="30000:60000")
    assert is_measured(loud) and playback_gain_db(loud) == -8.0 and playback_gain_db(quiet) == 5.0
    assert playback_gain_db(song(loudness_db=-70.0, loudness_for="30000:60000")) == 10.0  # silence: boost is capped
    assert playback_gain_db(song(loudness_db=-1.0, loudness_for="30000:60000", volume_adjust_db=2.5)) == -12.5


def test_a_measurement_for_old_clip_times_is_ignored():
    stale = song(loudness_db=-8.0, loudness_for="0:30000")
    assert not is_measured(stale) and playback_gain_db(stale) == 0.0
    assert playback_gain_db(song(volume_adjust_db=-3.0)) == -3.0  # the nudge works without a measurement
    assert window_key(0, None) == "0:" and window_key(5, 10) == "5:10"
    assert "needs measuring again" in describe(stale) and describe(song()) == "Not measured yet. Plays at its own volume."
    assert describe(song(loudness_db=-10.0, loudness_for="30000:60000")) == "Measured at -10.0 LUFS. Plays 6.0 dB quieter."


@pytest.mark.parametrize("bad", ["", "loud", "nan", "inf", "3"])
def test_bad_measurements_are_refused(bad):
    with pytest.raises(ValueError):
        parse_loudness(bad)


def test_measurements_and_nudges_are_tidied():
    assert parse_loudness("-12.345") == -12.35 and parse_loudness("-200") == -70.0
    assert parse_adjust("") == 0.0 and parse_adjust(" 2.25 ") == 2.2 and parse_adjust("-12") == -12.0
    for bad in ("13", "-12.5", "x", "nan"):
        with pytest.raises(ValueError):
            parse_adjust(bad)


def post_loudness(client, song_id, **fields):
    data = {"csrf_token": csrf_token(client, "/library"), **fields}
    return client.post(f"/library/{song_id}/loudness", data=data)


def test_the_browser_saves_a_measurement_for_the_current_window(app, logged_in, tmp_path):
    ids = seed_songs(app, logged_in, tmp_path, 1)
    saved = post_loudness(logged_in, ids[0], loudness="-10", start_ms="0", end_ms="")
    assert saved.status_code == 200 and saved.json()["gain_db"] == -6.0 and "6.0 dB quieter" in saved.json()["text"]
    with Session(app.state.engine) as session:
        assert session.get(Song, ids[0]).loudness_for == "0:"
    assert post_loudness(logged_in, ids[0], loudness="-10", start_ms="1000", end_ms="").status_code == 409  # moved
    assert post_loudness(logged_in, ids[0], loudness="loud", start_ms="0", end_ms="").status_code == 400
    assert logged_in.post(f"/library/{ids[0]}/loudness", data={"loudness": "-10"}).status_code == 403  # no csrf


def test_the_host_can_nudge_a_song_on_its_edit_page(app, logged_in, tmp_path):
    ids = seed_songs(app, logged_in, tmp_path, 1)
    page = logged_in.get(f"/library/{ids[0]}/edit").text
    assert "Not measured yet." in page and 'name="volume_adjust"' in page and "measure.js" in page
    form = {"title": "Song", "volume_adjust": "3.5", "csrf_token": csrf_token(logged_in, f"/library/{ids[0]}/edit")}
    assert logged_in.post(f"/library/{ids[0]}/edit", data=form, follow_redirects=False).status_code == 303
    with Session(app.state.engine) as session:
        assert session.get(Song, ids[0]).volume_adjust_db == 3.5
    form["volume_adjust"] = "40"
    refused = logged_in.post(f"/library/{ids[0]}/edit", data=form)
    assert refused.status_code == 400 and "between -12 and +12 dB" in refused.text


def test_the_game_page_offers_to_measure_its_songs_and_the_console_gets_the_gain(app, logged_in, tmp_path):
    ids = seed_songs(app, logged_in, tmp_path, 12)
    game_id = game_id_from(create_game(logged_in, ids, grid_size=3, tickets=3))
    page = logged_in.get(f"/games/{game_id}").text
    assert "0 of 12 songs measured" in page and "Measure 12 songs" in page and "data-measure-songs" in page
    for sid in ids:
        assert post_loudness(logged_in, sid, loudness="-20", start_ms="0", end_ms="").status_code == 200
    assert "All 12 songs are measured" in logged_in.get(f"/games/{game_id}").text
    host_post(logged_in, game_id, "start")
    state = host_post(logged_in, game_id, "next").json()
    assert state["current_song"]["gain_db"] == 4.0 and state["unmeasured"] == 0


def test_older_databases_gain_the_volume_columns(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'old.db3'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE song (id INTEGER PRIMARY KEY, title TEXT)"))
        connection.execute(text("INSERT INTO song (title) VALUES ('Old song')"))
    apply_additive_migrations(engine)
    columns = {c["name"] for c in inspect(engine).get_columns("song")}
    assert {"loudness_db", "loudness_for", "volume_adjust_db"} <= columns
    with engine.connect() as connection:
        row = connection.execute(text("SELECT loudness_db, loudness_for, volume_adjust_db FROM song")).one()
    assert tuple(row) == (None, "", 0)

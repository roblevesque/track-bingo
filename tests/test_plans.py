import json

from app.services.planner import LibSong, PlanRow
from app.services.plans import (
    NEED, NONE_CHOICE, PICK, READY, SKIPPED, dump_choices, dump_skipped, load_choices, load_skipped, parse_roles,
    plan_rows_of, progress, ready_songs, resolve, row_key, to_get,
)
from app.services.sheets import rows_from_text

LIBRARY = [
    LibSong(1, "Dancing Queen", "ABBA", "70s", uses=1),
    LibSong(2, "Waterloo", "ABBA", "", uses=5),
    LibSong(3, "Killer Queen", "Queen", "", uses=0),
]


def rows(*pairs):
    return [PlanRow(i, a, s) for i, (a, s) in enumerate(pairs, start=1)]


def states(items):
    return [i.state for i in items]


def test_exact_matches_are_ready_missing_songs_are_to_get_and_artist_lines_wait_for_a_pick():
    items = resolve(rows(("ABBA", "Dancing Queen"), ("Madonna", "Vogue"), ("ABBA", "")), LIBRARY, 3, {}, set())
    assert states(items) == [READY, NEED, PICK]
    assert items[0].song.id == 1 and not items[0].chosen
    assert [s.id for s in items[2].candidates] == [1, 2]  # least used first


def test_a_close_match_waits_until_someone_accepts_it():
    close = resolve(rows(("ABBA", "Dance Queen")), LIBRARY, 3, {}, set())
    assert close[0].state == PICK and close[0].candidates[0].id == 1
    accepted = resolve(rows(("ABBA", "Dance Queen")), LIBRARY, 3, {row_key(PlanRow(1, "ABBA", "Dance Queen")): 1}, set())
    assert accepted[0].state == READY and accepted[0].chosen


def test_choosing_a_song_makes_the_line_ready_and_none_of_these_sends_it_back_to_get():
    plan = rows(("ABBA", ""), ("ABBA", "Dancing Queen"))
    key_artist, key_song = row_key(plan[0]), row_key(plan[1])
    items = resolve(plan, LIBRARY, 3, {key_artist: 2, key_song: NONE_CHOICE}, set())
    assert items[0].state == READY and items[0].song.id == 2 and items[0].chosen
    assert items[1].state == NEED and items[1].candidates  # looked at the library, wants the real thing


def test_a_chosen_song_that_was_deleted_falls_back_to_the_default():
    plan = rows(("ABBA", "Dancing Queen"))
    items = resolve(plan, LIBRARY, 3, {row_key(plan[0]): 99}, set())
    assert items[0].state == READY and items[0].song.id == 1 and not items[0].chosen


def test_skipped_lines_leave_the_count():
    plan = rows(("ABBA", "Dancing Queen"), ("Madonna", "Vogue"))
    items = resolve(plan, LIBRARY, 3, {}, {row_key(plan[1])})
    assert states(items) == [READY, SKIPPED]
    assert progress(items) == {READY: 1, PICK: 0, NEED: 0, SKIPPED: 1, "total": 1, "percent": 100}


def test_progress_updates_by_itself_when_a_song_is_added_to_the_library():
    plan = rows(("ABBA", "Dancing Queen"), ("Madonna", "Vogue"))
    before = resolve(plan, LIBRARY, 3, {}, set())
    assert progress(before)["percent"] == 50 and to_get(before) == [("Madonna", "Vogue", "")]
    after = resolve(plan, LIBRARY + [LibSong(9, "Vogue", "Madonna")], 3, {}, set())
    assert progress(after)["percent"] == 100 and to_get(after) == []


def test_decisions_are_keyed_by_the_line_not_its_position_so_reordering_keeps_them():
    a, b = PlanRow(1, "ABBA", ""), PlanRow(2, "Queen", "")
    choices = {row_key(a): 2}
    swapped = resolve([PlanRow(1, "Queen", ""), PlanRow(2, "ABBA", "")], LIBRARY, 3, choices, set())
    assert swapped[1].song.id == 2 and swapped[1].chosen
    assert row_key(PlanRow(7, "ABBA", "Waterloo")) == row_key(PlanRow(1, "abba", "WATERLOO"))


def test_ready_songs_are_listed_once_in_sheet_order():
    plan = rows(("ABBA", "Waterloo"), ("Queen", "Killer Queen"), ("ABBA", "Waterloo"))
    assert [s.id for s in ready_songs(resolve(plan, LIBRARY, 3, {}, set()))] == [2, 3]


def test_to_get_notes_artist_only_lines_that_were_declined():
    plan = rows(("ABBA", ""))
    items = resolve(plan, LIBRARY, 3, {row_key(plan[0]): NONE_CHOICE}, set())
    assert to_get(items) == [("ABBA", "", "any song by this artist")]


def test_saved_decisions_survive_a_round_trip_and_bad_data_is_ignored():
    assert load_choices(dump_choices({"a|b": 3, "c|": 0})) == {"a|b": 3, "c|": 0}
    assert load_skipped(dump_skipped({"x|y", "a|b"})) == {"x|y", "a|b"}
    for junk in ("", "nope", "[1]", json.dumps({"a": "text", "b": True, "c": 4})):
        assert load_choices(junk) in ({}, {"c": 4})
    assert load_skipped("{}") == set() and load_skipped("nope") == set()


def test_roles_are_cleaned_and_padded():
    assert parse_roles("artist,song", 3) == ["artist", "song", "ignore"]
    assert parse_roles("bogus,song", 2) == ["ignore", "song"]


def test_plan_rows_are_built_from_the_stored_sheet():
    raw = "Artist\tSong\nABBA\tWaterloo\nQueen\t"
    got = plan_rows_of(raw, "artist,song", True, rows_from_text)
    assert [(r.number, r.artist, r.song) for r in got] == [(2, "ABBA", "Waterloo"), (3, "Queen", "")]
    assert plan_rows_of("", "artist,song", False, rows_from_text) == []

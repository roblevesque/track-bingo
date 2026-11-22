from app.services.merge import Info, blocking_games, choose_keeper, merged_values, remap_choices, remap_ids


def test_the_copy_in_most_games_is_kept_so_least_has_to_change():
    assert choose_keeper([Info(1), Info(2, games=3), Info(3, games=1)]) == 2


def test_ties_prefer_a_play_window_then_more_tags_then_an_artist_then_the_oldest():
    assert choose_keeper([Info(1), Info(2, start_ms=5000)]) == 2
    assert choose_keeper([Info(1, tags="a"), Info(2, tags="a,b")]) == 2
    assert choose_keeper([Info(1), Info(2, artist="ABBA")]) == 2
    assert choose_keeper([Info(5), Info(3), Info(9)]) == 3


def test_tags_are_combined_and_blank_details_filled_in_from_a_copy():
    keeper = Info(1, tags="80s", artist="", fun_fact="")
    other = Info(2, tags="rock, 80s", artist="ABBA", fun_fact="Fun fact")
    got = merged_values(keeper, [other])
    assert got["tags"] == "80s,rock" and got["artist"] == "ABBA" and got["fun_fact"] == "Fun fact"


def test_the_keepers_own_details_win():
    got = merged_values(Info(1, artist="Queen", fun_fact="Mine"), [Info(2, artist="ABBA", fun_fact="Theirs")])
    assert got["artist"] == "Queen" and got["fun_fact"] == "Mine"


def test_a_play_window_is_kept_or_taken_from_a_copy_that_has_one():
    assert merged_values(Info(1, start_ms=1000, end_ms=31000), [Info(2, start_ms=5000, end_ms=9000)])["start_ms"] == 1000
    taken = merged_values(Info(1), [Info(2), Info(3, start_ms=5000, end_ms=35000)])
    assert (taken["start_ms"], taken["end_ms"]) == (5000, 35000)
    assert merged_values(Info(1), [Info(2)])["start_ms"] == 0


def test_ids_are_pointed_at_the_keeper():
    assert remap_ids([1, 2, 3, 2], {2: 1}) == [1, 1, 3, 1]
    assert remap_ids([], {2: 1}) == []


def test_saved_plan_choices_follow_the_merge_and_zero_or_junk_is_left_alone():
    assert remap_choices('{"a|b": 2, "c|": 0, "d|e": 7}', {2: 1}) == '{"a|b": 1, "c|": 0, "d|e": 7}'
    untouched = '{"a|b": 5}'
    assert remap_choices(untouched, {2: 1}) == untouched
    assert remap_choices("nope", {2: 1}) == "nope" and remap_choices("[1]", {2: 1}) == "[1]" and remap_choices("", {2: 1}) == ""


def test_a_game_holding_two_of_the_copies_blocks_the_merge():
    pools = {10: {1, 2, 3}, 11: {2, 9}, 12: {1, 3}}
    assert blocking_games(pools, {1, 2}) == [10]
    assert blocking_games(pools, {1, 3}) == [10, 12]
    assert blocking_games(pools, {2, 9}) == [11]
    assert blocking_games(pools, {5, 6}) == []

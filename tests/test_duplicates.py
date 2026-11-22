from app.services.duplicates import SAME_FILE, SAME_SONG, Entry, describe, duplicate_groups, find_duplicate

LIB = [
    Entry(1, "Dancing Queen", "ABBA", "aaa"),
    Entry(2, "Hold On", "Kings of Leon", "bbb"),
    Entry(3, "Mystery Song", "", "ccc"),
]


def test_the_same_file_is_caught_whatever_it_is_called():
    kind, entry = find_duplicate("Totally Different", "Someone", "aaa", LIB)
    assert (kind, entry.id) == (SAME_FILE, 1)


def test_the_same_song_is_caught_despite_case_brackets_and_remaster_tails():
    for title, artist in [("dancing queen", "abba"), ("Dancing Queen (Remastered 2001)", "ABBA"), ("Dancing Queen - 2020 Remaster", "Abba")]:
        found = find_duplicate(title, artist, "zzz", LIB)
        assert found and found[0] == SAME_SONG and found[1].id == 1, title


def test_a_different_song_or_artist_is_not_flagged():
    assert find_duplicate("Waterloo", "ABBA", "zzz", LIB) is None
    assert find_duplicate("Hold On", "Wilson Phillips", "zzz", LIB) is None


def test_a_missing_artist_only_matches_an_identical_title():
    assert find_duplicate("Hold On", "", "zzz", LIB)[1].id == 2
    assert find_duplicate("Hold Up", "", "zzz", LIB) is None
    assert find_duplicate("Mystery Song", "Anyone", "zzz", LIB)[1].id == 3


def test_an_empty_title_or_checksum_never_matches():
    assert find_duplicate("", "ABBA", "", LIB) is None
    assert find_duplicate("x", "y", "", [Entry(5, "z", "", "")]) is None


def test_messages_name_the_existing_song():
    assert describe(SAME_FILE, LIB[0]) == "is the same file as “Dancing Queen” by ABBA"
    assert describe(SAME_SONG, LIB[2]) == "may be a copy of “Mystery Song”"


def test_groups_list_identical_files_first_and_do_not_repeat_songs():
    library = [
        Entry(1, "Waterloo", "ABBA", "f1"), Entry(2, "Waterloo", "ABBA", "f1"),   # same file (and same title)
        Entry(3, "Vogue", "Madonna", "f3"), Entry(4, "vogue", "Madonna", "f4"),   # same song, different files
        Entry(5, "Solo", "Nobody", "f5"),
    ]
    groups = duplicate_groups(library)
    assert [(g.kind, [e.id for e in g.entries]) for g in groups] == [(SAME_FILE, [1, 2]), (SAME_SONG, [3, 4])]
    assert duplicate_groups([]) == []

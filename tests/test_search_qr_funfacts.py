import pytest

from app.services.gameio import BundleError, parse_manifest, manifest_dict
from app.services.parsing import MAX_FUN_FACT, clean_fun_fact
from app.services.qr import QRError, capacity, encode, to_svg
from app.services.remote import remote_view
from app.services.search import matches, parse_query


# ---------------------------------------------------------------- search

def find(text, songs):
    query = parse_query(text)
    return [title for title, artist, tags in songs if matches(query, title, artist, tags)]


SONGS = [
    ("Dancing Queen", "ABBA", "70s,pop"),
    ("Bohemian Rhapsody", "Queen", "70s,classic rock,live"),
    ("Take On Me", "a-ha", ""),
    ("Livin' on a Prayer", "Bon Jovi", "80s,rock"),
]


def test_plain_words_must_all_match_in_title_artist_or_tags():
    assert find("queen", SONGS) == ["Dancing Queen", "Bohemian Rhapsody"]
    assert find("queen 70s pop", SONGS) == ["Dancing Queen"]
    assert find("QUEEN  abba", SONGS) == ["Dancing Queen"]
    assert find("", SONGS) == [title for title, _, _ in SONGS]


def test_a_bang_leaves_out_songs_with_that_exact_tag():
    assert find("!live", SONGS) == ["Dancing Queen", "Take On Me", "Livin' on a Prayer"]
    assert find("queen !live", SONGS) == ["Dancing Queen"]
    assert find("!rock", SONGS) == [t for t, _, _ in SONGS if t != "Livin' on a Prayer"]  # "classic rock" is a different tag
    assert find('!"classic rock"', SONGS) == ["Dancing Queen", "Take On Me", "Livin' on a Prayer"]
    assert find("!70s !80s", SONGS) == ["Take On Me"]


def test_no_tags_finds_untagged_songs_and_combines_with_words():
    assert find("no:tags", SONGS) == ["Take On Me"]
    assert find("NO:TAGS take", SONGS) == ["Take On Me"]
    assert find("no:tags queen", SONGS) == []


def test_quotes_keep_a_phrase_together_and_odd_input_is_harmless():
    assert find('"on a prayer"', SONGS) == ["Livin' on a Prayer"]
    assert find("on prayer", SONGS) == ["Livin' on a Prayer"]
    assert parse_query("!").empty and parse_query("   ").empty
    assert parse_query('!"never closed').excluded_tags == ("never closed",)
    assert parse_query("wow! hit").words == ("wow!", "hit")
    assert len(" ".join(parse_query("x " * 500).words)) <= 100


# ---------------------------------------------------------------- QR codes

def test_the_code_is_square_with_finder_patterns_and_grows_with_the_text():
    small, big = encode("hi"), encode("x" * 100)
    assert len(small) == 21 and len(big) > len(small) and all(len(row) == len(big) for row in big)
    for grid in (small, big):  # the three finder squares have a dark 7x7 ring
        n = len(grid)
        for ox, oy in ((0, 0), (n - 7, 0), (0, n - 7)):
            assert all(grid[oy][ox + i] and grid[oy + 6][ox + i] and grid[oy + i][ox] and grid[oy + i][ox + 6] for i in range(7))
            assert grid[oy + 3][ox + 3] and not grid[oy + 1][ox + 1]


def test_too_long_text_and_bad_levels_are_refused():
    assert encode("y" * capacity("M"))  # exactly full
    with pytest.raises(QRError):
        encode("y" * (capacity("M") + 1))
    with pytest.raises(QRError):
        encode("x", level="H")


def test_the_svg_is_self_contained_black_on_white():
    svg = to_svg("http://192.168.1.20:8000/remote?code=ABC234")
    assert svg.startswith("<svg") and svg.endswith("</svg>") and 'fill="#fff"' in svg and 'fill="#000"' in svg
    assert "<script" not in svg and "http://192" not in svg  # the address is encoded in the squares, not written out


@pytest.mark.parametrize("level", ["L", "M"])
@pytest.mark.parametrize("length", [1, 20, 44, 84, 120, 213])
def test_codes_scan_back_to_the_text(level, length):
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    text = ("http://192.168.1.20:8000/remote?code=ABC234" + "x" * length)[:length] if length < 44 else "a1" * (length // 2)
    modules = encode(text, level)
    scale, quiet = 8, 4
    image = np.full(((len(modules) + 2 * quiet) * scale,) * 2, 255, np.uint8)
    for y, row in enumerate(modules):
        for x, dark in enumerate(row):
            if dark:
                image[(y + quiet) * scale:(y + quiet + 1) * scale, (x + quiet) * scale:(x + quiet + 1) * scale] = 0
    decoders = (cv2.QRCodeDetector(), cv2.QRCodeDetectorAruco())
    results = [d.detectAndDecode(cv2.resize(image, None, fx=f, fy=f, interpolation=cv2.INTER_NEAREST))[0] for d in decoders for f in (1, 1.25)]
    assert text in results  # OpenCV's detector is picky about scale, so any one reading it correctly is enough


# ---------------------------------------------------------------- fun facts

def test_a_fun_fact_is_tidied_into_one_paragraph():
    assert clean_fun_fact("  Recorded in\n\n one   take  ") == "Recorded in one take"
    assert MAX_FUN_FACT == 500


def host_snapshot(fact):
    song = {"id": 3, "title": "Song 3", "artist": "A", "fun_fact": fact, "audio_url": "/x", "start_ms": 0, "end_ms": None}
    return {"game": {"name": "Q", "status": "active"}, "round": None, "rounds": [], "songs_played": 1, "total_songs": 5,
            "current_song": song, "next_song": None, "claims": [], "effects": []}


def test_the_phone_remote_sees_the_current_songs_fun_fact_and_older_snapshots_still_work():
    assert remote_view(host_snapshot("Written in a day"), True)["current"]["fun_fact"] == "Written in a day"
    old = host_snapshot("")
    del old["current_song"]["fun_fact"]
    assert remote_view(old, True)["current"]["fun_fact"] == ""


def test_fun_facts_travel_in_exported_games_and_older_files_still_load():
    from tests.test_gameio import make_bundle
    import json
    bundle = make_bundle()
    bundle.songs[0].fun_fact = "Played at the first Iron Horse night"
    manifest = json.loads(json.dumps(manifest_dict(bundle)))
    assert parse_manifest(manifest).songs[0].fun_fact == "Played at the first Iron Horse night"
    for song in manifest["songs"]:
        song.pop("fun_fact")
    assert parse_manifest(manifest).songs[0].fun_fact == ""
    manifest["songs"][0]["fun_fact"] = "x" * (MAX_FUN_FACT + 1)
    with pytest.raises(BundleError):
        parse_manifest(manifest)


# ---------------------------------------------------------------- library ordering and play-window marker

from datetime import datetime, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from app.services.search import DEFAULT_SHOW, DEFAULT_SORT, SHOWS, SORTS, filter_show, has_window, sort_songs  # noqa: E402


def song(id, title, artist="", added=0, edited=None, start=0, end=None):
    base = datetime(2026, 1, 1)
    return SimpleNamespace(id=id, title=title, artist=artist, created_at=base + timedelta(days=added),
                           updated_at=None if edited is None else base + timedelta(days=edited), start_ms=start, end_ms=end)


LIBRARY = [
    song(1, "Waterloo", "ABBA", added=1, end=30000),
    song(2, "Dancing Queen", "ABBA", added=2),
    song(3, "killer queen", "Queen", added=3, start=5000),
    song(4, "Africa", "", added=4, edited=10),
    song(5, "Believe", "Cher", added=5),
]


def ids(songs):
    return [s.id for s in songs]


def test_a_song_with_a_start_or_end_time_has_a_play_window():
    assert has_window(song(1, "a", end=1000)) and has_window(song(1, "a", start=1000))
    assert not has_window(song(1, "a"))


def test_every_sort_is_stable_and_case_insensitive():
    assert ids(sort_songs(LIBRARY, "title")) == [4, 5, 2, 3, 1]  # Africa, Believe, Dancing Queen, killer queen, Waterloo
    assert ids(sort_songs(LIBRARY, "title_desc")) == [1, 3, 2, 5, 4]
    assert ids(sort_songs(LIBRARY, "artist")) == [2, 1, 5, 3, 4]  # ABBA (Dancing Queen, Waterloo by title), Cher, Queen; no artist last
    assert ids(sort_songs(LIBRARY, "added")) == [5, 4, 3, 2, 1]
    assert ids(sort_songs(LIBRARY, "edited")) == [4, 5, 3, 2, 1]  # edited on day 10 beats everything added earlier
    assert ids(sort_songs(LIBRARY, "nonsense")) == ids(sort_songs(LIBRARY, DEFAULT_SORT))


def test_songs_without_a_window_come_first_when_asked():
    ordered = sort_songs(LIBRARY, "window")
    assert ids(ordered)[:3] == [4, 5, 2] and set(ids(ordered)[3:]) == {1, 3}


def test_the_play_window_filter():
    assert ids(filter_show(LIBRARY, "todo")) == [2, 4, 5]
    assert ids(filter_show(LIBRARY, "done")) == [1, 3]
    assert ids(filter_show(LIBRARY, "all")) == [1, 2, 3, 4, 5] and ids(filter_show(LIBRARY, "x")) == [1, 2, 3, 4, 5]
    assert DEFAULT_SORT in SORTS and DEFAULT_SHOW in SHOWS


# ---------------------------------------------------------------- paging

from app.services.paging import DEFAULT_PER_PAGE, PER_PAGE_OPTIONS, clean_page, clean_per_page, page_links, paginate  # noqa: E402


def test_pages_cover_every_item_exactly_once():
    for total in (0, 1, 24, 25, 26, 99, 100, 101):
        seen = []
        first = paginate(total, 1, 25)
        for n in range(1, first.pages + 1):
            pg = paginate(total, n, 25)
            seen.extend(range(pg.start, pg.stop))
        assert seen == list(range(total)), total
    assert paginate(0, 1, 25).pages == 1 and paginate(26, 1, 25).pages == 2


def test_a_page_that_no_longer_exists_becomes_the_last_or_first_page():
    assert paginate(30, 99, 25).page == 2 and paginate(30, 0, 25).page == 1 and paginate(30, -4, 25).page == 1
    assert paginate(5, 1, 7).per_page == DEFAULT_PER_PAGE  # only the offered sizes are used


def test_page_numbers_from_forms_are_made_safe():
    assert [clean_page(x) for x in ("3", " 7 ", "0", "-2", "abc", "", None, "9" * 30)] == [3, 7, 1, 1, 1, 1, 1, 1_000_000]
    assert clean_per_page("100") == 100 and clean_per_page("7") == DEFAULT_PER_PAGE and clean_per_page("x", 25) == 25
    assert DEFAULT_PER_PAGE in PER_PAGE_OPTIONS


def test_the_pager_shows_the_ends_and_the_neighbours():
    assert page_links(1, 1) == [1]
    assert page_links(1, 5) == [1, 2, 3, 4, 5]
    assert page_links(10, 20) == [1, None, 8, 9, 10, 11, 12, None, 20]
    assert page_links(2, 20) == [1, 2, 3, 4, None, 20]
    assert page_links(20, 20) == [1, None, 18, 19, 20]


def test_the_phone_remote_also_gets_the_next_songs_fun_fact_and_older_snapshots_still_work():
    host = host_snapshot("Written in a day")
    host["next_song"] = {"id": 4, "title": "Song 4", "artist": "B", "fun_fact": "Covered by a pub band"}
    assert remote_view(host, True)["next"]["fun_fact"] == "Covered by a pub band"
    del host["next_song"]["fun_fact"]
    assert remote_view(host, True)["next"]["fun_fact"] == ""

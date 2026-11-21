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

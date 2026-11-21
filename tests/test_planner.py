import io
import zipfile

import pytest

from app.services.planner import (
    ARTIST, HAVE, MAYBE, NEED, LibSong, PlanRow, add_tag, build_rows, find_header, guess_mapping, match_rows,
    normalize, shopping_list, similarity, summarize,
)
from app.services.sheets import (
    MAX_ROWS, SheetError, clean_rows, rows_from_csv, rows_from_text, rows_from_upload, rows_from_xlsx, template_csv,
    template_xlsx,
)


# ---------------------------------------------------------------- reading sheets

def test_cells_pasted_from_excel_are_split_on_tabs_and_blank_rows_dropped():
    assert rows_from_text("Artist\tSong\r\nABBA\tDancing Queen\r\n\r\nCher\t\r\n") == [
        ["Artist", "Song"], ["ABBA", "Dancing Queen"], ["Cher", ""]]


def test_pasted_commas_and_plain_lists_also_work():
    assert rows_from_text("ABBA, Dancing Queen\nCher, Believe") == [["ABBA", "Dancing Queen"], ["Cher", "Believe"]]
    assert rows_from_text("Prince\nMadonna") == [["Prince"], ["Madonna"]]


def test_cells_are_tidied_and_empty_trailing_columns_dropped():
    rows = clean_rows([["  King of   Anything ", "Sara Bareilles", None], [None, "Albert King", ""], [None, None, None]])
    assert rows == [["King of Anything", "Sara Bareilles"], ["", "Albert King"]]


def test_too_many_rows_are_refused():
    with pytest.raises(SheetError):
        clean_rows([[f"song {i}"] for i in range(MAX_ROWS + 1)])


def test_csv_in_utf8_with_bom_and_in_old_excel_encoding_both_read():
    assert rows_from_csv("﻿Artist,Song\nCafé Tacvba,Eres\n".encode("utf-8")) == [["Artist", "Song"], ["Café Tacvba", "Eres"]]
    assert rows_from_csv("Artist;Song\nCafé Tacvba;Eres\n".encode("cp1252"))[1][0] == "Café Tacvba"


def test_the_templates_read_back_as_artist_and_song_with_a_header():
    for rows in (rows_from_xlsx(template_xlsx()), rows_from_csv(template_csv().encode("utf-8"))):
        assert rows[0] == ["Artist", "Song"] and rows[1] == ["ABBA", "Dancing Queen"] and rows[3] == ["Prince", ""]
        assert find_header(rows[0]) == {0: "artist", 1: "song"}


def test_an_xlsx_written_by_excel_style_tools_is_read(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    book.active.append(["King of the Road", "Roger Miller"])
    book.active.append([None, "Albert King"])
    book.active.append(["Royals ", None])
    path = tmp_path / "sheet.xlsx"
    book.save(path)
    assert rows_from_upload("Royalty.XLSX", path.read_bytes()) == [
        ["King of the Road", "Roger Miller"], ["", "Albert King"], ["Royals", ""]]


def test_unreadable_uploads_get_a_plain_message():
    with pytest.raises(SheetError, match="Excel"):
        rows_from_xlsx(b"not a zip at all")
    broken = io.BytesIO()
    with zipfile.ZipFile(broken, "w") as z:
        z.writestr("hello.txt", "x")
    with pytest.raises(SheetError):
        rows_from_xlsx(broken.getvalue())
    with pytest.raises(SheetError, match="xlsx"):
        rows_from_upload("old.xls", b"x")
    with pytest.raises(SheetError):
        rows_from_upload("notes.docx", b"x")


# ---------------------------------------------------------------- normalising and similarity

@pytest.mark.parametrize("a, b", [
    ("Royals (Remastered 2020)", "royals"),
    ("The Police", "police"),
    ("Beyoncé", "Beyonce"),
    ("Kool & the Gang", "Kool and the Gang"),
    ("Dancing Queen - 2011 Remaster", "Dancing Queen"),
    ('"Childish Gambino"', "Childish Gambino"),
    ("Ed Sheeran ft Taylor Swift", "Ed Sheeran"),
    ("Don’t Stop Believin’", "Dont Stop Believin"),
])
def test_normalising_makes_the_usual_differences_disappear(a, b):
    is_artist = a in ("The Police", "Ed Sheeran ft Taylor Swift", '"Childish Gambino"', "Kool & the Gang")
    assert normalize(a, is_artist=is_artist) == normalize(b, is_artist=is_artist)


def test_typos_score_high_and_different_names_low():
    assert similarity(normalize("Weezzer"), normalize("Weezer")) > 0.9
    assert similarity(normalize("Cultue Club"), normalize("Culture Club")) > 0.9
    assert similarity(normalize("Dancing Queen"), normalize("Killer Queen")) < 0.75
    assert similarity("", "x") == 0.0


# ---------------------------------------------------------------- guessing the columns

LIB = [
    LibSong(1, "Dancing Queen", "ABBA", "70s,pop", uses=4, last_game="ABBA night"),
    LibSong(2, "Waterloo", "ABBA", "70s"),
    LibSong(3, "Killer Queen", "Queen", "", uses=1),
    LibSong(4, "Buddy Song", "Weezer"),
    LibSong(5, "Royals (Remastered 2020)", "Lorde", uses=2),
    LibSong(6, "Dancing Queen", "Some Cover Band"),
    LibSong(7, "King of Pain", "The Police"),
    LibSong(8, "Untitled", ""),
]


def test_a_header_row_decides_the_columns_whatever_their_order():
    assert guess_mapping([["Song", "Artist"], ["x", "y"]], LIB) == (["song", "artist"], True)
    assert guess_mapping([["Title", "Band", "Notes"], ["x", "y", "z"]], LIB) == (["song", "artist", "ignore"], True)
    assert find_header(["King of the Road", "Roger Miller"]) is None


def test_without_a_header_the_library_shows_which_column_holds_artists():
    rows = [["King of Pain", "The Police"], ["Killer Queen", "Queen"], ["Waterloo", "ABBA"], ["Mystery", "Nobody"]]
    assert guess_mapping(rows, LIB) == (["song", "artist"], False)
    rows3 = [["Freddie Mercury", "Queen", ""], ["Benny Andersson", "ABBA", "Waterloo"], ["Sting", "The Police", ""]]
    roles, header = guess_mapping(rows3, LIB)
    assert roles[1] == "artist" and not header


def test_with_no_hints_the_templates_order_is_used():
    assert guess_mapping([["zzz", "yyy"], ["qqq", "www"]], []) == (["artist", "song"], False)


def test_rows_are_built_from_the_chosen_columns():
    rows = [["Artist", "Song", "Who"], ["ABBA", "Dancing Queen", "x"], ["Cher", "", ""], ["", "", "only notes"]]
    plan = build_rows(rows, ["artist", "song", "ignore"], skip_header=True)
    assert [(p.number, p.artist, p.song) for p in plan] == [(2, "ABBA", "Dancing Queen"), (3, "Cher", "")]


# ---------------------------------------------------------------- matching

def run(artist, song, overuse=3):
    (result,) = match_rows([PlanRow(1, artist, song)], LIB, overuse)
    return result


def test_a_song_in_the_library_is_found_despite_case_remasters_and_the():
    r = run("abba", "dancing queen")
    assert r.status == HAVE and r.matches[0].song.id == 1
    assert run("Lorde", "Royals").status == HAVE
    assert run("Police", "King of Pain").matches[0].song.id == 7


def test_a_missing_song_is_marked_to_get_and_typos_are_forgiven():
    assert run("Queen", "Bohemian Rhapsody").status == NEED
    assert run("Queen", "Killer Queeen").status == HAVE


def test_the_same_title_by_another_artist_is_only_a_close_match():
    r = run("Cher", "Waterloo")
    assert r.status == MAYBE and "ABBA" in r.matches[0].note
    r = run("", "Killer Queen")  # no artist given: the title alone is enough
    assert r.status == HAVE


def test_a_song_used_often_is_flagged_and_other_songs_by_the_artist_are_offered():
    r = run("ABBA", "Dancing Queen", overuse=3)
    assert r.overused and [s.title for s in r.alternatives] == ["Waterloo"]
    assert not run("ABBA", "Dancing Queen", overuse=5).overused


def test_an_artist_only_row_lists_their_songs_least_used_first():
    r = run("abba", "")
    assert r.status == ARTIST and [m.song.title for m in r.matches] == ["Waterloo", "Dancing Queen"]
    assert run("Weezzer", "").status == ARTIST  # a typo in the artist
    assert run("Madonna", "").status == NEED


def test_summary_and_shopping_list_cover_what_is_missing():
    plan = [PlanRow(1, "ABBA", "Dancing Queen"), PlanRow(2, "Madonna", ""), PlanRow(3, "Prince", "Kiss"), PlanRow(4, "Cher", "Waterloo")]
    results = match_rows(plan, LIB)
    assert summarize(results) == {HAVE: 1, MAYBE: 1, ARTIST: 0, NEED: 2, "overused": 1}
    assert shopping_list(results) == [("Madonna", "", "any song by this artist"), ("Prince", "Kiss", "")]


def test_an_empty_library_needs_everything():
    assert [r.status for r in match_rows([PlanRow(1, "ABBA", "Waterloo"), PlanRow(2, "Cher", "")], [])] == [NEED, NEED]


# ---------------------------------------------------------------- tagging

def test_tags_are_added_without_duplicates_and_within_the_limit():
    assert add_tag("70s,pop", "Royalty Night") == "70s,pop,royalty night"
    assert add_tag("70s", "70S") == "70s"
    assert add_tag("", "  ") is None and add_tag("a", "x,y") is None
    assert add_tag(",".join(f"t{i}" for i in range(20)), "new") is None

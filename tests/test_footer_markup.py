import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.services.branding import MAX_FOOTER_CHARS, clean_footer, footer_problem, parse_footer, parse_inline
from app.services.pdf import BrandStyle, Fonts, build_tickets_pdf, footer_lines, with_footer
from tests.test_pdf import page_count

HERE = Path(__file__).parent
CASES = [
    "Next week: **90s Night**, *Thursday* 7pm", "***both*** plain", "2 * 3 * 4", "**unclosed", "a*b*c", "*", "**", "****",
    "**bold *and italic* inside**", "* spaced *", "x**y**z", "no markup at all", "", "  lots   of   space  ", "**a** **b** *c*",
    "price is $5 * 2 and *really* so", "Ünicode **日本語** *ñ*", "line one\nline **two**\r\n\n  three  ",
]


def test_footers_are_tidied_one_line_per_line_of_text():
    assert clean_footer("  a   b \r\n\n\n c\n") == "a b\nc"
    assert clean_footer("") == "" and clean_footer("  \n ") == ""


def test_footer_limits_are_characters_and_lines():
    assert footer_problem("a\nb\nc\nd") is None
    assert "4 lines" in footer_problem("a\nb\nc\nd\ne")
    assert footer_problem("x" * MAX_FOOTER_CHARS) is None
    assert "400 characters" in footer_problem("x" * (MAX_FOOTER_CHARS + 1))
    assert footer_problem("") is None


def test_bold_italic_and_both_are_read_and_stray_markers_are_just_text():
    assert parse_inline("Next **90s** *Night*") == [("Next ", False, False), ("90s", True, False), (" ", False, False), ("Night", False, True)]
    assert parse_inline("***both***") == [("both", True, True)]
    for plain in ("2 * 3 * 4", "**unclosed", "* spaced *", "****", "*", "no markup"):
        assert parse_inline(plain) == [(plain, False, False)], plain


def test_fonts_pick_the_right_face_and_a_custom_font_prints_upright():
    f = Fonts()
    assert [f.styled(False, False), f.styled(True, False), f.styled(False, True), f.styled(True, True)] == [
        "Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique"]


def test_footer_lines_wrap_cap_and_style():
    f = Fonts()
    one = footer_lines("Next **90s** night", "G", f, 8, 300)
    assert len(one) == 1 and ("90s", "Helvetica-Bold") in one[0]
    wrapped = footer_lines("word " * 40, "G", f, 8, 120)
    assert len(wrapped) > 1 and all(line for line in wrapped)
    capped = footer_lines("a\nb\nc\nd\ne\nf", "G", f, 8, 300)
    assert len(capped) == 4 and capped[-1][-1][0].endswith("…")
    assert footer_lines("", "G", f, 8, 300) == []


def test_variables_fill_in_after_styling_so_a_game_name_cannot_restyle_the_footer():
    f = Fonts()
    (line,) = footer_lines("${GAME.NAME} **night**", "A*B*C **x**", f, 8, 400)
    assert "".join(text for text, _ in line) == "A*B*C **x** night"
    assert all(font == "Helvetica" for text, font in line if "night" not in text)


def test_a_long_unbroken_word_is_cut_not_overflowed():
    (line,) = footer_lines("W" * 200, "G", Fonts(), 8, 100)
    assert line[0][0].endswith("…")


def test_unsupported_characters_become_question_marks_in_the_built_in_font():
    (line,) = footer_lines("日本 **ñ**", "G", Fonts(), 8, 300)
    assert "".join(t for t, _ in line) == "?? ñ"


def test_a_four_line_footer_still_builds_the_pdf_at_every_layout():
    brand = BrandStyle(accent="#336699", footer_text="One **bold**\n*Two*\n${GAME.NAME} three\nFour " + "long " * 30)
    cells = [("Song", "Artist")] * 9
    for per_page in (1, 2, 4):
        for orientation in ("landscape", "portrait"):
            pdf = build_tickets_pdf("Night", 3, [(n, cells) for n in range(1, 5)], brand=brand, per_page=per_page, orientation=orientation)
            assert pdf.startswith(b"%PDF") and page_count(pdf) == -(-4 // per_page)


def test_a_game_footer_keeps_its_line_breaks():
    assert with_footer(None, "  One \n\n Two  ").footer_text == "One\nTwo"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js isn't installed (only needed for this check)")
def test_the_browser_preview_reads_footers_exactly_like_the_server(tmp_path):
    corpus = tmp_path / "cases.json"
    corpus.write_text(json.dumps(CASES))
    out = subprocess.run(["node", str(HERE / "js" / "footer_check.mjs"), str(corpus)], capture_output=True, text=True, timeout=60, check=True)
    from_js = json.loads(out.stdout)
    from_python = [[[list(run) for run in line] for line in parse_footer(text)] for text in CASES]
    assert from_js == from_python

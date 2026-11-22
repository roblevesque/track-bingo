import pytest

from app.services.cardtext import (
    DEFAULT_ARTIST, DEFAULT_TITLE, MAX_SIZE, MIN_SIZE, TextStyle, card_text, clean_content, clean_style, dumps, loads,
)
from app.services.gameio import manifest_dict, parse_manifest
from app.services.pdf import BrandStyle, Fonts, build_tickets_pdf
from tests.test_gameio import make_bundle
from tests.test_pdf import page_count


def test_the_defaults_are_bold_song_names_and_plain_band_names_in_black():
    assert (DEFAULT_TITLE.style, DEFAULT_TITLE.size, DEFAULT_TITLE.color) == ("bold", None, "#000000")
    assert (DEFAULT_ARTIST.style, DEFAULT_ARTIST.size) == ("regular", None)


def test_a_valid_style_is_cleaned():
    style, errors = clean_style("serif", "bold-italic", " 18,5 ", "#AABBCC", DEFAULT_TITLE, "Song names")
    assert errors == [] and style == TextStyle("serif", "bold-italic", 18.5, "#aabbcc")
    assert style.bold and style.italic


def test_blank_values_mean_the_defaults_and_blank_size_means_automatic():
    style, errors = clean_style("", "", "", "", DEFAULT_TITLE, "Song names")
    assert errors == [] and style == DEFAULT_TITLE


@pytest.mark.parametrize("family,style,size,color", [
    ("comic", "bold", "", "#000000"), ("sans", "heavy", "", "#000000"), ("sans", "bold", "abc", "#000000"),
    ("sans", "bold", str(MAX_SIZE + 1), "#000000"), ("sans", "bold", str(MIN_SIZE - 1), "#000000"), ("sans", "bold", "", "red"),
    ("sans", "bold", "", "#12345"),
])
def test_bad_values_are_reported_by_name(family, style, size, color):
    _, errors = clean_style(family, style, size, color, DEFAULT_TITLE, "Band names")
    assert errors and all(e.startswith("Band names:") for e in errors)


def test_styles_survive_storing_and_junk_means_the_defaults():
    title = TextStyle("mono", "italic", 12.0, "#112233")
    assert loads(dumps(title, DEFAULT_ARTIST)) == (title, DEFAULT_ARTIST)
    assert dumps(DEFAULT_TITLE, DEFAULT_ARTIST) == ""
    for junk in ("", "nope", "[]", '{"title": 5}', '{"title": {"family": "x"}}'):
        assert loads(junk) == (DEFAULT_TITLE, DEFAULT_ARTIST)


def test_what_a_square_shows_depends_on_the_game():
    assert card_text("Dancing Queen", "ABBA", "both") == ("Dancing Queen", "ABBA")
    assert card_text("Dancing Queen", "ABBA", "artist") == ("", "ABBA")
    assert card_text("Dancing Queen", "ABBA", "title") == ("Dancing Queen", "")
    assert card_text("Wannabe", "", "artist") == ("Wannabe", "")  # no band to show: the song name, so no square is blank
    assert card_text("x", "y", "anything else") == ("x", "y")
    assert clean_content("artist") == "artist" and clean_content("bogus") == "both"


def test_fonts_pick_the_family_and_a_supplied_font_replaces_them():
    f = Fonts()
    assert f.face("serif", True, True) == "Times-BoldItalic" and f.face("mono", False, False) == "Courier"
    assert f.face("sans", True, False) == "Helvetica-Bold" and f.face("unknown", False, True) == "Helvetica-Oblique"
    custom = Fonts("TicketFont", "TicketFont-Bold", unicode=True, italic="TicketFont", bold_italic="TicketFont-Bold")
    assert custom.face("serif", True, False) == "TicketFont-Bold" and custom.face("mono", False, True) == "TicketFont"


def test_cards_build_with_every_style_and_with_band_names_alone():
    cells = [("Dancing Queen", "ABBA"), ("Wannabe", ""), ("", "Queen")] * 3
    for family in ("sans", "serif", "mono"):
        for style in ("regular", "bold", "italic", "bold-italic"):
            brand = BrandStyle(title_style=TextStyle(family, style, 20, "#8b0000"), artist_style=TextStyle(family, style, 9, "#006400"))
            pdf = build_tickets_pdf("Night", 3, [(1, cells), (2, cells)], brand=brand, per_page=2)
            assert pdf.startswith(b"%PDF") and page_count(pdf) == 1


def test_game_files_carry_what_cards_show_and_older_files_still_load():
    bundle = make_bundle()
    bundle.card_content = "artist"
    manifest = manifest_dict(bundle)
    assert parse_manifest(manifest).card_content == "artist"
    del manifest["game"]["card_content"]  # a file exported before this setting existed
    assert parse_manifest(manifest).card_content == "both"
    manifest["game"]["card_content"] = "nonsense"
    assert parse_manifest(manifest).card_content == "both"
    manifest["game"]["card_content"] = 5
    assert parse_manifest(manifest).card_content == "both"

import re

import pytest

from app.services.pdf import BrandStyle, Fonts, build_tickets_pdf, fit_text, printable, with_footer
from tests.conftest import add_user, create_game, game_id_from, login, new_player, seed_songs


def sheets(count, size=3):
    return [(n, [(f"Song {n}-{i} with a long title", f"Artist {i}") for i in range(size * size)])
            for n in range(1, count + 1)]


def page_count(pdf):
    return len(re.findall(rb"/Type\s*/Page(?![a-z])", pdf))


@pytest.mark.parametrize("per_page, pages", [(1, 5), (2, 3), (4, 2)])
def test_pages_match_tickets_per_page(per_page, pages):
    pdf = build_tickets_pdf("Pub Night", 3, sheets(5), per_page=per_page)
    assert pdf.startswith(b"%PDF") and page_count(pdf) == pages


@pytest.mark.parametrize("paper", ["letter", "a4"])
def test_both_paper_sizes(paper):
    assert build_tickets_pdf("Pub Night", 5, sheets(2, 5), paper=paper).startswith(b"%PDF")


def test_awkward_text_does_not_break_layout():
    odd = [(1, [("\u65e5\u672c\u8a9e \u2013 \u00f1and\u00fa", ""), ("A" * 200, "B" * 200)] + [("t", "a")] * 7)]
    assert build_tickets_pdf("\u00dcn\u00efcode \u65e5\u672c game " * 5, 3, odd).startswith(b"%PDF")
    assert build_tickets_pdf("Big", 9, sheets(2, 9), per_page=4).startswith(b"%PDF")


def test_rejects_bad_requests():
    with pytest.raises(ValueError):
        build_tickets_pdf("X", 3, [])
    with pytest.raises(ValueError):
        build_tickets_pdf("X", 3, sheets(1), paper="tabloid")
    with pytest.raises(ValueError):
        build_tickets_pdf("X", 3, sheets(1), per_page=3)


def test_unsupported_characters_become_question_marks():
    assert printable("\u65e5\u672c \u00f1 \u201cq\u201d", Fonts()) == "?? \u00f1 \u201cq\u201d"
    assert printable("  spaced   out ", Fonts()) == "spaced out"


def test_text_shrinks_to_fit_then_is_cut_with_an_ellipsis():
    size, lines = fit_text("Short", "Helvetica-Bold", 14, 100, 30)
    assert size == 14 and lines == ["Short"]
    size, lines = fit_text("word " * 60, "Helvetica-Bold", 14, 60, 30)
    assert size == 5.0 and len(lines) * size * 1.15 <= 30 and lines[-1].endswith("\u2026")


def test_download_route(app, logged_in, tmp_path):
    ids = seed_songs(app, logged_in, tmp_path, 12)
    game_id = game_id_from(create_game(logged_in, ids, name="Pub Night!", grid_size=3, tickets=5))
    response = logged_in.get(f"/games/{game_id}/cards.pdf?paper=a4&per_page=2")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == 'attachment; filename="Pub-Night-cards.pdf"'
    assert response.content.startswith(b"%PDF") and page_count(response.content) == 3
    assert logged_in.get(f"/games/{game_id}/cards.pdf").status_code == 200  # defaults
    assert logged_in.get(f"/games/{game_id}/cards.pdf?per_page=3").status_code == 400
    assert logged_in.get(f"/games/{game_id}/cards.pdf?paper=tabloid").status_code == 400
    assert "cards.pdf" in logged_in.get(f"/games/{game_id}").text


def test_download_needs_a_login_but_any_host_may_print(app, logged_in, tmp_path):
    ids = seed_songs(app, logged_in, tmp_path, 12)
    game_id = game_id_from(create_game(logged_in, ids, grid_size=3))
    assert new_player(app).get(f"/games/{game_id}/cards.pdf", follow_redirects=False).status_code == 303
    add_user(app, "other")
    other = new_player(app)
    login(other, "other")
    assert other.get(f"/games/{game_id}/cards.pdf").status_code == 200


def page_sizes(pdf):
    return [tuple(float(v) for v in m.groups()) for m in re.finditer(rb"/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*\]", pdf)]


def test_defaults_are_one_ticket_per_page_in_landscape():
    pdf = build_tickets_pdf("Pub Night", 3, sheets(3))
    assert page_count(pdf) == 3
    sizes = page_sizes(pdf)
    assert sizes and all(w > h for w, h in sizes)


@pytest.mark.parametrize("paper", ["letter", "a4"])
def test_portrait_is_still_available(paper):
    pdf = build_tickets_pdf("Pub Night", 3, sheets(2), paper=paper, orientation="portrait")
    sizes = page_sizes(pdf)
    assert sizes and all(w < h for w, h in sizes)


@pytest.mark.parametrize("per_page, pages", [(1, 5), (2, 3), (4, 2)])
def test_landscape_page_counts(per_page, pages):
    pdf = build_tickets_pdf("Pub Night", 3, sheets(5), per_page=per_page, orientation="landscape")
    assert page_count(pdf) == pages


def test_rejects_unknown_orientation():
    with pytest.raises(ValueError):
        build_tickets_pdf("X", 3, sheets(1), orientation="diagonal")


def test_a_game_footer_replaces_the_brand_footer():
    brand = BrandStyle(accent="#336699", header_text="Head", footer_text="Host footer")
    out = with_footer(brand, "  Next week:   90s Night ")
    assert out.footer_text == "Next week: 90s Night"
    assert (out.accent, out.header_text) == ("#336699", "Head")


def test_an_empty_game_footer_keeps_the_brand_footer():
    brand = BrandStyle(footer_text="Host footer")
    assert with_footer(brand, "") is brand
    assert with_footer(brand, "   ") is brand
    assert with_footer(None, "") is None


def test_a_game_footer_works_with_no_branding_at_all():
    out = with_footer(None, "Next week: Quiz Night")
    assert out.footer_text == "Next week: Quiz Night" and out.accent is None
    assert build_tickets_pdf("Pub Night", 3, sheets(1), brand=out).startswith(b"%PDF")

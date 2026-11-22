"""Printable ticket sheets: every ticket of a game in one PDF, each with its number.

Pure layout code (no database or web imports): it is handed plain data and returns bytes.
"""

import re
from dataclasses import dataclass, replace
from io import BytesIO

from reportlab.lib.colors import HexColor, black, gray
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

from app.services.branding import clean_footer, expand_variables, on_color, parse_footer
from app.services.cardtext import DEFAULT_ARTIST, DEFAULT_TITLE, TextStyle

PAPER_SIZES = {"letter": letter, "a4": A4}
ORIENTATIONS = ("landscape", "portrait")
DEFAULT_ORIENTATION = "landscape"
DEFAULT_PER_PAGE = 1
# per page -> (columns, rows). Two tickets sit side by side on a landscape page and stacked on a portrait one.
LAYOUTS = {
    "portrait": {1: (1, 1), 2: (1, 2), 4: (2, 2)},
    "landscape": {1: (1, 1), 2: (2, 1), 4: (2, 2)},
}
TICKETS_PER_PAGE = LAYOUTS["portrait"]  # the allowed counts (the same in either orientation)

PAGE_MARGIN = 28
TICKET_INSET = 8  # space between a ticket and the cut line around it
HEADER_HEIGHT = 26
LEADING = 1.15
MIN_FONT = 5.0


@dataclass(frozen=True)
class BrandStyle:
    """The host's ticket branding. Every part is optional."""

    accent: str | None = None  # "#rrggbb": header band and square borders
    header_text: str = ""  # shown instead of the game name
    footer_text: str = ""
    logo_png: bytes | None = None  # already validated by services.branding.process_logo
    title_style: TextStyle | None = None  # how song names print; None = bold, automatic size, black
    artist_style: TextStyle | None = None  # the same for band names


@dataclass(frozen=True)
class Fonts:
    regular: str = "Helvetica"
    bold: str = "Helvetica-Bold"
    unicode: bool = False  # the built-in fonts only cover Western European text
    italic: str = "Helvetica-Oblique"
    bold_italic: str = "Helvetica-BoldOblique"

    def face(self, family: str, bold: bool, italic: bool) -> str:
        """The font for a family and style. A supplied TrueType font replaces the built-in families."""
        if self.unicode:
            return self.styled(bold, italic)
        return _BUILTIN_FACES.get(family, _BUILTIN_FACES["sans"])[(2 if italic else 0) + (1 if bold else 0)]

    def styled(self, bold: bool, italic: bool) -> str:
        return (self.bold_italic if italic else self.bold) if bold else (self.italic if italic else self.regular)


_BUILTIN_FACES = {  # regular, bold, italic, bold italic
    "sans": ("Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique"),
    "serif": ("Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic"),
    "mono": ("Courier", "Courier-Bold", "Courier-Oblique", "Courier-BoldOblique"),
}


def load_fonts(regular_path: str | None = None, bold_path: str | None = None) -> Fonts:
    """Use the built-in fonts, or a TrueType font the host supplies for other alphabets."""
    if not regular_path:
        return Fonts()
    from reportlab.pdfbase.ttfonts import TTFont

    pdfmetrics.registerFont(TTFont("TicketFont", regular_path))
    bold = "TicketFont"
    if bold_path:
        pdfmetrics.registerFont(TTFont("TicketFont-Bold", bold_path))
        bold = "TicketFont-Bold"
    return Fonts("TicketFont", bold, unicode=True, italic="TicketFont", bold_italic=bold)  # no italic file: italic text prints upright


def printable(text: str, fonts: Fonts) -> str:
    """Characters the font can't draw would come out as black boxes, so show '?' instead."""
    text = " ".join(text.split())
    return text if fonts.unicode else text.encode("cp1252", "replace").decode("cp1252")


FOOTER_LINES = 4


def _encodable(text: str, fonts: Fonts) -> str:
    return text if fonts.unicode else text.encode("cp1252", "replace").decode("cp1252")


def footer_lines(text: str, game_name: str, fonts: Fonts, size: float, width: float, max_lines: int = FOOTER_LINES):
    """The footer as at most `max_lines` centred lines that fit `width`: each a list of (text, font name).

    Lines the host typed stay separate, long ones wrap at spaces, **bold** and *italic* pick the font, and
    ${GAME.NAME}/${GAME.DATE} are filled in after the styling is read (so a game name can't change the styling).
    Anything past the last line is cut with an ellipsis."""
    out: list[list[tuple[str, str]]] = []
    for runs in parse_footer(text):
        words: list[tuple[str, str]] = []  # (piece, font); a piece is a word or a run of spaces
        for run_text, bold, italic in runs:
            font = fonts.styled(bold, italic)
            expanded = _encodable(expand_variables(run_text, game_name=game_name), fonts)
            for piece in re.findall(r"\s+|\S+", expanded):
                words.append((" " if piece.isspace() else piece, font))
        line: list[tuple[str, str]] = []
        used = 0.0
        for piece, font in words:
            piece_w = pdfmetrics.stringWidth(piece, font, size)
            if piece != " " and line and used + piece_w > width:
                while line and line[-1][0] == " ":
                    line.pop()
                out.append(line)
                line, used = [], 0.0
            if piece == " " and not line:
                continue
            if piece != " " and piece_w > width:  # one word wider than the card: cut it
                piece = shorten(piece, font, size, width)
                piece_w = pdfmetrics.stringWidth(piece, font, size)
            line.append((piece, font))
            used += piece_w
        while line and line[-1][0] == " ":
            line.pop()
        if line:
            out.append(line)
    if len(out) > max_lines:
        out = out[:max_lines]
        last = out[-1]
        text_, font = last[-1]
        room = width - sum(pdfmetrics.stringWidth(t, f, size) for t, f in last[:-1])
        last[-1] = (shorten(text_ + "\u2026", font, size, max(room, 1)), font)
    return [_merge(line) for line in out]


def _merge(line):
    merged: list[tuple[str, str]] = []
    for piece, font in line:
        if merged and merged[-1][1] == font:
            merged[-1] = (merged[-1][0] + piece, font)
        else:
            merged.append((piece, font))
    return merged


def fit_text(text: str, font: str, max_size: float, width: float, height: float):
    """Largest font size (down to MIN_FONT) at which the wrapped text fits the box.

    Returns (size, lines). If even the smallest size is too tall the text is cut with an ellipsis.
    """
    size = max_size
    while size >= MIN_FONT:
        lines = simpleSplit(text, font, size, width)
        fits_height = len(lines) * size * LEADING <= height
        fits_width = all(pdfmetrics.stringWidth(line, font, size) <= width for line in lines)
        if fits_height and fits_width:
            return size, lines
        size -= 0.5
    size = MIN_FONT
    lines = simpleSplit(text, font, size, width)
    room = max(1, int(height // (size * LEADING)))
    if len(lines) > room:
        lines = lines[:room]
        lines[-1] = shorten(lines[-1] + "\u2026", font, size, width)
    return size, [shorten(line, font, size, width) for line in lines]


def shorten(text: str, font: str, size: float, width: float) -> str:
    if pdfmetrics.stringWidth(text, font, size) <= width:
        return text
    while text and pdfmetrics.stringWidth(text + "\u2026", font, size) > width:
        text = text[:-1]
    return text + "\u2026"


def _draw_cell(c, x, y, w, h, title, artist, fonts, border, title_style=DEFAULT_TITLE, artist_style=DEFAULT_ARTIST):
    c.setStrokeColor(border)
    c.setFillColor(black)
    c.setLineWidth(0.6)
    c.rect(x, y, w, h)
    pad = 3
    inner_w, inner_h = w - 2 * pad, h - 2 * pad
    # A square with one piece of text (a game that prints only band names, or a song with no artist) gives it the
    # whole square; with both, the song name gets two thirds and the band name the rest.
    if not title and artist:
        title, artist, title_style = artist, "", artist_style  # the band name stands alone, in the band's style
    lone = not artist
    title_font = fonts.face(title_style.family, title_style.bold, title_style.italic)
    title_max = title_style.size or min(14, w / 5)
    title_size, title_lines = fit_text(title, title_font, title_max, inner_w, inner_h * (0.9 if lone else 0.66))
    artist_size, artist_lines = 0, []
    artist_font = fonts.face(artist_style.family, artist_style.bold, artist_style.italic)
    if artist:
        artist_max = artist_style.size or max(MIN_FONT, title_size - 1)
        artist_size, artist_lines = fit_text(artist, artist_font, artist_max, inner_w, inner_h * 0.3)
    gap = 2 if artist_lines else 0
    block = len(title_lines) * title_size * LEADING + gap + len(artist_lines) * artist_size * LEADING
    cursor = y + h / 2 + block / 2  # top of the text block, which is centred in the cell
    centre = x + w / 2
    for font, size, lines, colour in (
        (title_font, title_size, title_lines, title_style.color), (artist_font, artist_size, artist_lines, artist_style.color),
    ):
        c.setFillColor(HexColor(colour))
        for line in lines:
            cursor -= size * LEADING
            c.setFont(font, size)
            c.drawCentredString(centre, cursor + size * 0.28, line)
        cursor -= gap


def _draw_ticket(c, x, y, w, h, *, game_name, number, size, cells, fonts, brand, logo):
    """Draw one ticket in the box whose lower-left corner is (x, y)."""
    accent = HexColor(brand.accent) if brand.accent else None
    ink = HexColor(on_color(brand.accent)) if accent else black
    top = y + h
    if accent:
        c.setFillColor(accent)
        c.rect(x, top - HEADER_HEIGHT, w, HEADER_HEIGHT, stroke=0, fill=1)
    c.setFillColor(ink)

    left = x + 4
    if logo is not None:
        logo_w, logo_h = logo.getSize()
        height = HEADER_HEIGHT - 6
        width = min(height * logo_w / logo_h, w * 0.35)
        height = width * logo_h / logo_w
        c.drawImage(logo, left, top - HEADER_HEIGHT + (HEADER_HEIGHT - height) / 2, width=width, height=height, mask="auto")
        left += width + 6

    number_text = f"Card {number}"
    number_width = pdfmetrics.stringWidth(number_text, fonts.bold, 14)
    c.setFont(fonts.bold, 12)
    title = printable(expand_variables(brand.header_text, game_name=game_name), fonts) or game_name
    c.drawString(left, top - HEADER_HEIGHT + 8, shorten(title, fonts.bold, 12, x + w - number_width - 12 - left))
    c.setFont(fonts.bold, 14)
    c.drawRightString(x + w - 4, top - HEADER_HEIGHT + 8, number_text)

    big = w > 480  # a ticket with a whole landscape page to itself has room for a more readable footer
    lines = footer_lines(brand.footer_text, game_name, fonts, 12 if big else 8, w - 8)
    footer_size = 12 if big else (8 if len(lines) <= 2 else 7)  # four lines on a small card need a smaller type
    if len(lines) > 2 or not lines:
        lines = footer_lines(brand.footer_text, game_name, fonts, footer_size, w - 8)
    leading = footer_size * 1.2
    footer_height = len(lines) * leading + (10 if big else 6) if lines else 0
    grid_bottom = y + footer_height
    if lines:
        c.setFillColor(gray)
        cursor = y + footer_height - (5 if big else 3) - footer_size * 0.85  # baseline of the first line
        for line in lines:
            start = x + w / 2 - sum(pdfmetrics.stringWidth(t, f, footer_size) for t, f in line) / 2
            for piece, font in line:
                c.setFont(font, footer_size)
                c.drawString(start, cursor, piece)
                start += pdfmetrics.stringWidth(piece, font, footer_size)
            cursor -= leading

    grid_top = top - HEADER_HEIGHT
    cell_w = w / size
    cell_h = (grid_top - grid_bottom) / size
    border = accent if accent else black
    for row in range(size):
        for col in range(size):
            title_text, artist = cells[row * size + col]
            _draw_cell(
                c, x + col * cell_w, grid_top - (row + 1) * cell_h, cell_w, cell_h,
                printable(title_text, fonts), printable(artist, fonts), fonts, border,
                brand.title_style or DEFAULT_TITLE, brand.artist_style or DEFAULT_ARTIST,
            )


def _draw_cut_lines(c, page_w, page_h, cols, rows, slot_w, slot_h):
    c.saveState()
    c.setDash(3, 3)
    c.setLineWidth(0.4)
    c.setStrokeGray(0.5)
    for col in range(1, cols):
        x = PAGE_MARGIN + col * slot_w
        c.line(x, 0, x, page_h)
    for row in range(1, rows):
        y = page_h - PAGE_MARGIN - row * slot_h
        c.line(0, y, page_w, y)
    c.restoreState()


def build_tickets_pdf(
    game_name: str,
    size: int,
    tickets: list[tuple[int, list[tuple[str, str]]]],
    *,
    paper: str = "letter",
    per_page: int = DEFAULT_PER_PAGE,
    orientation: str = DEFAULT_ORIENTATION,
    fonts: Fonts | None = None,
    brand: BrandStyle | None = None,
) -> bytes:
    """tickets: [(ticket number, [(title, artist) per square, row-major]), ...]"""
    if not tickets:
        raise ValueError("there are no cards to print")
    if paper not in PAPER_SIZES:
        raise ValueError(f"unknown paper size {paper!r}")
    if per_page not in TICKETS_PER_PAGE:
        raise ValueError(f"cards per page must be one of {sorted(TICKETS_PER_PAGE)}")
    if orientation not in ORIENTATIONS:
        raise ValueError(f"orientation must be one of {list(ORIENTATIONS)}")
    fonts = fonts or Fonts()
    brand = brand or BrandStyle()
    try:
        logo = ImageReader(BytesIO(brand.logo_png)) if brand.logo_png else None
    except Exception:  # an unreadable logo must never stop tickets from printing
        logo = None
    page_w, page_h = PAPER_SIZES[paper]
    if orientation == "landscape":
        page_w, page_h = max(page_w, page_h), min(page_w, page_h)
    cols, rows = LAYOUTS[orientation][per_page]
    slot_w = (page_w - 2 * PAGE_MARGIN) / cols
    slot_h = (page_h - 2 * PAGE_MARGIN) / rows

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=(page_w, page_h))
    c.setTitle(printable(f"{game_name} cards", fonts))
    for index, (number, cells) in enumerate(tickets):
        slot = index % per_page
        if slot == 0:
            if index:
                c.showPage()
            _draw_cut_lines(c, page_w, page_h, cols, rows, slot_w, slot_h)
        col, row = slot % cols, slot // cols
        x = PAGE_MARGIN + col * slot_w + TICKET_INSET
        y = page_h - PAGE_MARGIN - (row + 1) * slot_h + TICKET_INSET
        _draw_ticket(
            c, x, y, slot_w - 2 * TICKET_INSET, slot_h - 2 * TICKET_INSET,
            game_name=printable(game_name, fonts), number=number, size=size, cells=cells, fonts=fonts,
            brand=brand, logo=logo,
        )
    c.save()
    return buffer.getvalue()


def with_footer(brand: BrandStyle | None, footer: str) -> BrandStyle | None:
    """The brand with this game's own footer in place of the host's, if the game has one."""
    footer = clean_footer(footer or "")
    if not footer:
        return brand
    return replace(brand or BrandStyle(), footer_text=footer)


def fonts_from_settings(settings) -> Fonts:
    """The configured TrueType font, or the built-in one if none is set or it can't be loaded."""
    try:
        return load_fonts(settings.pdf_font, settings.pdf_font_bold)
    except Exception:
        return load_fonts()

"""How song and band names look on printed cards, and what a game prints on them. Pure functions."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass

FAMILIES = {"sans": "Sans-serif (Helvetica)", "serif": "Serif (Times)", "mono": "Monospace (Courier)"}
STYLES = {"regular": "Regular", "bold": "Bold", "italic": "Italic", "bold-italic": "Bold italic"}
MIN_SIZE, MAX_SIZE = 6.0, 30.0
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

CONTENTS = {"both": "Song and band name", "artist": "Band name only", "title": "Song name only"}
DEFAULT_CONTENT = "both"


@dataclass(frozen=True)
class TextStyle:
    family: str = "sans"
    style: str = "regular"
    size: float | None = None  # the largest size to try (it still shrinks to fit the square); None = automatic
    color: str = "#000000"

    @property
    def bold(self) -> bool:
        return self.style in ("bold", "bold-italic")

    @property
    def italic(self) -> bool:
        return self.style in ("italic", "bold-italic")


DEFAULT_TITLE = TextStyle(style="bold")
DEFAULT_ARTIST = TextStyle()


def clean_style(family: str, style: str, size: str, color: str, default: TextStyle, what: str) -> tuple[TextStyle, list[str]]:
    """A style from form values, plus anything wrong with them (`what` names the text in messages)."""
    errors: list[str] = []
    family, style, color = (family or default.family).strip(), (style or default.style).strip(), (color or default.color).strip()
    if family not in FAMILIES:
        errors.append(f"{what}: choose one of the listed fonts.")
        family = default.family
    if style not in STYLES:
        errors.append(f"{what}: choose one of the listed font styles.")
        style = default.style
    if not HEX.match(color):
        errors.append(f"{what}: the colour must look like #1a2b3c.")
        color = default.color
    value: float | None = None
    if (size or "").strip():
        try:
            value = round(float(size.strip().replace(",", ".")), 1)
        except ValueError:
            value = None
        if value is None or not MIN_SIZE <= value <= MAX_SIZE:
            errors.append(f"{what}: the size must be a number from {MIN_SIZE:g} to {MAX_SIZE:g}, or blank for automatic.")
            value = None
    return TextStyle(family, style, value, color.lower()), errors


def dumps(title: TextStyle, artist: TextStyle) -> str:
    """For storing: empty when both are the defaults."""
    if title == DEFAULT_TITLE and artist == DEFAULT_ARTIST:
        return ""
    return json.dumps({"title": asdict(title), "artist": asdict(artist)}, sort_keys=True)


def _from_dict(data: object, default: TextStyle) -> TextStyle:
    if not isinstance(data, dict):
        return default
    style, errors = clean_style(
        str(data.get("family", "")), str(data.get("style", "")),
        "" if data.get("size") is None else str(data.get("size")), str(data.get("color", "")), default, "",
    )
    return default if errors else style


def loads(text: str) -> tuple[TextStyle, TextStyle]:
    """Stored styles back to (title, artist); anything unreadable means the defaults."""
    try:
        data = json.loads(text) if text else {}
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    return _from_dict(data.get("title"), DEFAULT_TITLE), _from_dict(data.get("artist"), DEFAULT_ARTIST)


def clean_content(value: str) -> str:
    return value if value in CONTENTS else DEFAULT_CONTENT


def card_text(title: str, artist: str, content: str) -> tuple[str, str]:
    """What goes in one square: (title, artist) for 'both', only the band for 'artist' (the song name if the song
    has no artist, so no square is blank), only the song for 'title'."""
    if content == "artist":
        return ("", artist) if artist else (title, "")
    if content == "title":
        return title, ""
    return title, artist

"""The playlist planner: lines from a spreadsheet matched against the song library.

A sheet row can name an artist and a song, only an artist ("any song by them"), or only a song. Each row
comes back as one of four statuses:

    have     the song is in the library
    maybe    something close is in the library, for a person to confirm
    artist   an artist-only row: these are the library's songs by that artist
    need     nothing suitable in the library

Matching ignores case, accents, punctuation, "The", "(Remastered)" and "feat." tails, and forgives typos.
Pure Python with no database, so it can be tested on its own.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher

from app.services.parsing import MAX_TAGS, normalize_tags

HAVE, MAYBE, ARTIST, NEED = "have", "maybe", "artist", "need"
TITLE_SURE = 0.92  # a title this close counts as the same song
TITLE_MAYBE = 0.75
ARTIST_SAME = 0.82
ARTIST_LOOSE = 0.6
DEFAULT_OVERUSE = 3
ROLES = ("artist", "song", "ignore")

_HEADER_WORDS = {
    "artist": {"artist", "artists", "band", "performer", "singer", "musician", "by"},
    "song": {"song", "songs", "title", "titles", "track", "tracks", "song title", "song name", "name"},
}
_FEAT = re.compile(r"\b(?:feat|ft|featuring|with|vs|x)\b\.?.*$")
_BRACKETS = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_VERSION_TAIL = re.compile(r"\s-\s.*\b(?:remaster\w*|live|version|edit|mix|mono|stereo|single|radio|demo)\b.*$")


def normalize(text: str, *, is_artist: bool = False) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    text = _BRACKETS.sub(" ", text)
    text = _VERSION_TAIL.sub("", text)
    text = text.replace("&", " and ").replace("’", "'")
    text = re.sub(r"[^a-z0-9' ]+", " ", text).replace("'", "")
    text = _FEAT.sub("", text) if is_artist or " feat" in text or " ft " in text else text
    text = " ".join(text.split())
    return text[4:] if text.startswith("the ") else text


def similarity(a: str, b: str) -> float:
    """0 to 1 for two already-normalised strings."""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if abs(len(a) - len(b)) > 0.45 * max(len(a), len(b)):
        return 0.0
    matcher = SequenceMatcher(None, a, b)
    if matcher.real_quick_ratio() < 0.6 or matcher.quick_ratio() < 0.6:
        return 0.0
    return matcher.ratio()


# ---------------------------------------------------------------- the library and the sheet

@dataclass
class LibSong:
    id: int
    title: str
    artist: str
    tags: str = ""
    uses: int = 0  # games this song has been in
    last_used: datetime | None = None
    last_game: str = ""
    title_norm: str = field(init=False, default="")
    artist_norm: str = field(init=False, default="")

    def __post_init__(self) -> None:
        self.title_norm = normalize(self.title)
        self.artist_norm = normalize(self.artist, is_artist=True)

    @property
    def tag_list(self) -> list[str]:
        return [t for t in self.tags.split(",") if t]


@dataclass
class PlanRow:
    number: int  # the row's position in the sheet, from 1
    artist: str = ""
    song: str = ""


@dataclass
class Match:
    song: LibSong
    score: float  # 0 to 1
    note: str = ""


@dataclass
class Result:
    row: PlanRow
    status: str
    matches: list[Match] = field(default_factory=list)
    overused: bool = False  # a matched song has been used `overuse` times or more
    alternatives: list[LibSong] = field(default_factory=list)  # other songs by the artist, least used first


def find_header(row: list[str]) -> dict[int, str] | None:
    """If a row is a header ('Artist', 'Song'...), the role of each column it names."""
    roles: dict[int, str] = {}
    for i, cell in enumerate(row):
        word = cell.strip().lower()
        for role, words in _HEADER_WORDS.items():
            if word in words and role not in roles.values():
                roles[i] = role
    filled = [c for c in row if c.strip()]
    return roles if roles and len(roles) * 2 >= len(filled) else None  # at least half the cells are header words


def guess_mapping(rows: list[list[str]], library: list[LibSong]) -> tuple[list[str], bool]:
    """(a role for every column, whether the first row is a header). A guess: the page lets a person correct it."""
    width = len(rows[0]) if rows else 0
    header = find_header(rows[0]) if rows else None
    if header:
        return [header.get(i, "ignore") for i in range(width)], True
    body = rows
    artists = {s.artist_norm for s in library if s.artist_norm}
    titles = {s.title_norm for s in library if s.title_norm}
    artist_hit, song_hit = [], []
    for col in range(width):
        values = [normalize(r[col], is_artist=True) for r in body if r[col]]
        values_t = [normalize(r[col]) for r in body if r[col]]
        n = max(1, len(values))
        artist_hit.append(sum(v in artists for v in values) / n)
        song_hit.append(sum(v in titles for v in values_t) / n)
    roles = ["ignore"] * width
    if width and library:
        best_artist = max(range(width), key=lambda c: artist_hit[c])
        if artist_hit[best_artist] >= 0.12:
            roles[best_artist] = "artist"
        rest = [c for c in range(width) if roles[c] == "ignore"]
        if rest:
            best_song = max(rest, key=lambda c: song_hit[c])
            if song_hit[best_song] >= 0.12:
                roles[best_song] = "song"
    if "artist" not in roles and "song" not in roles:  # no hints: the template's order
        for i, role in enumerate(("artist", "song")[:width]):
            roles[i] = role
    elif "artist" not in roles or "song" not in roles:
        missing = "song" if "artist" in roles else "artist"
        free = [c for c in range(width) if roles[c] == "ignore"]
        if free and width <= 2:
            roles[free[0]] = missing
    return roles, False


def build_rows(rows: list[list[str]], roles: list[str], skip_header: bool) -> list[PlanRow]:
    out = []
    for index, row in enumerate(rows, start=1):
        if skip_header and index == 1:
            continue
        artist = " ".join(c for c, r in zip(row, roles) if r == "artist" and c).strip()
        song = " ".join(c for c, r in zip(row, roles) if r == "song" and c).strip()
        if artist or song:
            out.append(PlanRow(index, artist, song))
    return out


# ---------------------------------------------------------------- matching

def match_rows(plan: list[PlanRow], library: list[LibSong], overuse: int = DEFAULT_OVERUSE) -> list[Result]:
    by_artist: dict[str, list[LibSong]] = {}
    for song in library:
        by_artist.setdefault(song.artist_norm, []).append(song)
    artist_names = list(by_artist)
    artist_cache: dict[str, list[str]] = {}

    def artists_like(norm: str) -> list[str]:
        if norm not in artist_cache:
            artist_cache[norm] = [a for a in artist_names if a and similarity(norm, a) >= ARTIST_SAME]
        return artist_cache[norm]

    def songs_by(norm: str) -> list[LibSong]:
        found = [s for a in artists_like(norm) for s in by_artist[a]]
        return sorted(found, key=lambda s: (s.uses, s.title_norm))

    results = []
    for row in plan:
        a_norm, t_norm = normalize(row.artist, is_artist=True), normalize(row.song)
        if t_norm:
            matches = []
            for song in library:
                ts = similarity(t_norm, song.title_norm)
                if ts < TITLE_MAYBE:
                    continue
                if a_norm and song.artist_norm:
                    a_sim = similarity(a_norm, song.artist_norm)
                    other = a_sim < ARTIST_LOOSE
                else:
                    a_sim, other = (1.0 if not a_norm else 0.85), False  # an artist missing on either side can't count against a match
                if ts >= TITLE_SURE and a_sim >= ARTIST_SAME:
                    matches.append(Match(song, 0.7 * ts + 0.3 * a_sim))
                elif other and ts >= TITLE_SURE:
                    matches.append(Match(song, 0.5 * ts, f"by {song.artist}, not {row.artist}"))
                elif not other:
                    matches.append(Match(song, 0.7 * ts + 0.3 * a_sim, "close, not exact"))
            matches.sort(key=lambda m: -m.score)
            matches = matches[:3]
            if not matches:
                results.append(Result(row, NEED))
                continue
            sure = matches[0].note == ""
            result = Result(row, HAVE if sure else MAYBE, matches)
            result.overused = any(m.song.uses >= overuse for m in matches[:1])
            if result.overused and a_norm:
                taken = {m.song.id for m in matches}
                result.alternatives = [s for s in songs_by(a_norm) if s.id not in taken][:5]
            results.append(result)
        else:  # an artist and no song
            found = songs_by(a_norm)
            if found:
                result = Result(row, ARTIST, [Match(s, 1.0) for s in found])
                result.overused = all(s.uses >= overuse for s in found)
                results.append(result)
            else:
                results.append(Result(row, NEED))
    return results


def summarize(results: list[Result]) -> dict[str, int]:
    counts = {HAVE: 0, MAYBE: 0, ARTIST: 0, NEED: 0, "overused": 0}
    for r in results:
        counts[r.status] += 1
        counts["overused"] += r.overused
    return counts


def shopping_list(results: list[Result]) -> list[tuple[str, str, str]]:
    """(artist, song, note) for every row that needs something from outside the library."""
    out = []
    for r in results:
        if r.status == NEED:
            out.append((r.row.artist, r.row.song, "any song by this artist" if not r.row.song else ""))
        elif r.status == ARTIST and r.overused:
            out.append((r.row.artist, "", f"all of the library's songs by them have been used {DEFAULT_OVERUSE}+ times; pick another"))
    return out


# ---------------------------------------------------------------- tagging

def add_tag(existing: str, tag: str) -> str | None:
    """The tag string with `tag` added, or None if it can't be added (blank, or the song already has the maximum)."""
    new = normalize_tags(tag)
    if not new or "," in new:
        return None
    tags = [t for t in existing.split(",") if t]
    if new in tags:
        return ",".join(tags)
    if len(tags) >= MAX_TAGS:
        return None
    return ",".join(tags + [new])

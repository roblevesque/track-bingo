"""Spotting songs that are probably already in the library. Pure functions.

Two kinds of match: the *same file* (identical audio bytes, by checksum) and the *same song* (the same title by the
same artist once case, accents, brackets such as "(Remastered)" and a leading "The" are ignored). The second is a
suggestion, not a certainty: a live version can look like the studio one."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.planner import ARTIST_SAME, TITLE_SURE, normalize, similarity

SAME_FILE, SAME_SONG = "file", "song"


@dataclass
class Entry:
    id: int
    title: str
    artist: str = ""
    sha256: str = ""
    title_norm: str = field(init=False, default="")
    artist_norm: str = field(init=False, default="")

    def __post_init__(self) -> None:
        self.title_norm = normalize(self.title)
        self.artist_norm = normalize(self.artist, is_artist=True)


def same_song(title_norm: str, artist_norm: str, other: Entry) -> bool:
    if not title_norm or not other.title_norm:
        return False
    if artist_norm and other.artist_norm:
        return similarity(title_norm, other.title_norm) >= TITLE_SURE and similarity(artist_norm, other.artist_norm) >= ARTIST_SAME
    # One side has no artist: only an identical title counts, or a different artist's song of the same name would be flagged.
    return title_norm == other.title_norm


def find_duplicate(title: str, artist: str, sha256: str, library: list[Entry]) -> tuple[str, Entry] | None:
    """The existing song this one is probably a copy of, with why: the same file, else the same song."""
    if sha256:
        for entry in library:
            if entry.sha256 == sha256:
                return SAME_FILE, entry
    t_norm, a_norm = normalize(title), normalize(artist, is_artist=True)
    for entry in library:
        if same_song(t_norm, a_norm, entry):
            return SAME_SONG, entry
    return None


def describe(kind: str, entry: Entry) -> str:
    who = f"“{entry.title}”" + (f" by {entry.artist}" if entry.artist else "")
    return f"is the same file as {who}" if kind == SAME_FILE else f"may be a copy of {who}"


@dataclass
class Group:
    kind: str
    entries: list[Entry]


def duplicate_groups(library: list[Entry]) -> list[Group]:
    """Songs that share a file, then songs that share a title and artist (skipping ones already grouped)."""
    groups: list[Group] = []
    seen: set[int] = set()
    by_file: dict[str, list[Entry]] = {}
    for entry in library:
        if entry.sha256:
            by_file.setdefault(entry.sha256, []).append(entry)
    for entries in by_file.values():
        if len(entries) > 1:
            groups.append(Group(SAME_FILE, entries))
            seen.update(e.id for e in entries)
    by_name: dict[tuple[str, str], list[Entry]] = {}
    for entry in library:
        if entry.title_norm:
            by_name.setdefault((entry.title_norm, entry.artist_norm), []).append(entry)
    for entries in by_name.values():
        fresh = [e for e in entries if e.id not in seen]
        if len(entries) > 1 and len(fresh) > 1:
            groups.append(Group(SAME_SONG, entries))
    groups.sort(key=lambda g: (g.kind != SAME_FILE, g.entries[0].title_norm))
    return groups

"""Saved plans: turning a sheet plus the host's decisions into a live checklist.

Pure functions. A line is *ready* when a library song is settled for it, *pick* when the library has candidates and
a person must choose, *need* when the song still has to be found, and *skipped* when it was dropped from the plan.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.services.planner import (
    ARTIST, HAVE, LibSong, PlanRow, Result, build_rows, match_rows, normalize,
)

READY, PICK, NEED, SKIPPED = "ready", "pick", "need", "skipped"
STATES = (READY, PICK, NEED, SKIPPED)
NONE_CHOICE = 0  # the host looked at the library's songs and wants none of them


def row_key(row: PlanRow) -> str:
    """A stable name for a line that survives the sheet being edited or reordered."""
    return f"{normalize(row.artist, is_artist=True)}|{normalize(row.song)}"


def load_choices(text: str) -> dict[str, int]:
    try:
        data = json.loads(text or "{}")
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): int(v) for k, v in data.items() if isinstance(v, int) and not isinstance(v, bool)}


def load_skipped(text: str) -> set[str]:
    try:
        data = json.loads(text or "[]")
    except ValueError:
        return set()
    return {str(k) for k in data} if isinstance(data, list) else set()


def dump_choices(choices: dict[str, int]) -> str:
    return json.dumps(choices, sort_keys=True)


def dump_skipped(skipped: set[str]) -> str:
    return json.dumps(sorted(skipped))


@dataclass
class Item:
    result: Result
    key: str
    state: str
    song: LibSong | None = None  # the song settled for a ready line
    candidates: list[LibSong] = field(default_factory=list)  # what to choose from on a pick line (and to change a ready one)
    chosen: bool = False  # the host picked this (rather than the planner)

    @property
    def row(self) -> PlanRow:
        return self.result.row


def resolve(
    plan_rows: list[PlanRow], library: list[LibSong], overuse: int, choices: dict[str, int], skipped: set[str],
) -> list[Item]:
    by_id = {s.id: s for s in library}
    items: list[Item] = []
    for result in match_rows(plan_rows, library, overuse):
        key = row_key(result.row)
        candidates = [m.song for m in result.matches]
        item = Item(result, key, NEED, candidates=candidates)
        choice = choices.get(key)
        if key in skipped:
            item.state = SKIPPED
        elif choice == NONE_CHOICE and choice is not None:
            item.state = NEED
        elif choice in by_id:  # a chosen song; one that has since been deleted falls back to the default
            item.state, item.song, item.chosen = READY, by_id[choice], True
        elif result.status == HAVE:
            item.state, item.song = READY, candidates[0]
        elif candidates:  # a close match, or an artist with no song named: someone has to say yes
            item.state = PICK
        items.append(item)
    return items


def progress(items: list[Item]) -> dict[str, int]:
    counts = {READY: 0, PICK: 0, NEED: 0, SKIPPED: 0}
    for item in items:
        counts[item.state] += 1
    counts["total"] = len(items) - counts[SKIPPED]
    counts["percent"] = round(100 * counts[READY] / counts["total"]) if counts["total"] else 0
    return counts


def ready_songs(items: list[Item]) -> list[LibSong]:
    """The settled songs, each once, in sheet order."""
    seen: set[int] = set()
    out = []
    for item in items:
        if item.state == READY and item.song and item.song.id not in seen:
            seen.add(item.song.id)
            out.append(item.song)
    return out


def to_get(items: list[Item]) -> list[tuple[str, str, str]]:
    """(artist, song, note) for lines still needing a song found outside the library."""
    out = []
    for item in items:
        if item.state != NEED:
            continue
        note = "any song by this artist" if not item.row.song else ""
        out.append((item.row.artist, item.row.song, note))
    return out


def parse_roles(text: str, width: int) -> list[str]:
    roles = [r if r in ("artist", "song", "ignore") else "ignore" for r in (text or "").split(",")]
    return (roles + ["ignore"] * width)[:width]


def plan_rows_of(raw: str, roles_text: str, has_header: bool, rows_from_text) -> list[PlanRow]:
    rows = rows_from_text(raw)
    if not rows:
        return []
    return build_rows(rows, parse_roles(roles_text, max(len(r) for r in rows)), has_header)

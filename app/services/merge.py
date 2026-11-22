"""Merging songs that are copies of each other. The decisions are pure functions; the database work is in the route.

Merging keeps one song (the keeper) and folds the others into it: tags are combined, blank details are filled in, a
play window is kept (or taken from a copy that has one), and every game, card, play order and saved plan that used a
copy is pointed at the keeper. A card can't hold the same song twice, so a game that already has two of the copies
blocks the merge until one is taken out of it."""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.services.parsing import normalize_tags


@dataclass
class Info:
    id: int
    tags: str = ""
    artist: str = ""
    fun_fact: str = ""
    start_ms: int = 0
    end_ms: int | None = None
    games: int = 0  # how many games have it in their pool

    @property
    def has_window(self) -> bool:
        return bool(self.start_ms or self.end_ms)


def choose_keeper(infos: list[Info]) -> int:
    """The copy most worth keeping: the one in most games (so the least has to change), then one with a play
    window set, then the most tags, then one with an artist, then the oldest."""
    best = max(infos, key=lambda i: (i.games, i.has_window, len([t for t in i.tags.split(",") if t]), bool(i.artist), -i.id))
    return best.id


def merged_values(keeper: Info, others: list[Info]) -> dict:
    """What the keeper should hold afterwards."""
    tags = normalize_tags(",".join([keeper.tags] + [o.tags for o in others if o.tags]))
    artist = keeper.artist or next((o.artist for o in others if o.artist), "")
    fun_fact = keeper.fun_fact or next((o.fun_fact for o in others if o.fun_fact), "")
    start_ms, end_ms = keeper.start_ms, keeper.end_ms
    if not keeper.has_window:
        donor = next((o for o in others if o.has_window), None)
        if donor:
            start_ms, end_ms = donor.start_ms, donor.end_ms
    return {"tags": tags, "artist": artist, "fun_fact": fun_fact, "start_ms": start_ms, "end_ms": end_ms}


def remap_ids(ids: list[int], mapping: dict[int, int]) -> list[int]:
    return [mapping.get(i, i) for i in ids]


def remap_choices(text: str, mapping: dict[int, int]) -> str:
    """A saved plan's choices (line key -> song id) with merged-away songs replaced by the keeper."""
    try:
        data = json.loads(text or "{}")
    except ValueError:
        return text
    if not isinstance(data, dict):
        return text
    changed = {k: (mapping.get(v, v) if isinstance(v, int) and not isinstance(v, bool) else v) for k, v in data.items()}
    return json.dumps(changed, sort_keys=True) if changed != data else text


def blocking_games(pools: dict[int, set[int]], group: set[int]) -> list[int]:
    """Games (by id) whose song pool holds two or more of the songs being merged."""
    return sorted(game for game, songs in pools.items() if len(songs & group) >= 2)

"""Play order for a running game. Pure Python.

A game stores one shuffled `order` of song ids and an `index` = how many have been
played. The played songs are always `order[:index]`; the rest are still to come.
"""

import random


class PlaylistExhausted(Exception):
    """Every song has been played."""


def new_play_order(pool: list[int], rng: random.Random | None = None) -> list[int]:
    order = list(dict.fromkeys(pool))
    (rng or random.Random()).shuffle(order)
    return order


def played_ids(order: list[int], index: int) -> list[int]:
    return list(order[:index])


def advance(order: list[int], index: int) -> tuple[int, int]:
    """Play the next song. Returns (song_id, new_index)."""
    if index >= len(order):
        raise PlaylistExhausted()
    return order[index], index + 1


def skip_next(order: list[int], index: int) -> list[int]:
    """Move the next song to the end of the order, so it is heard last instead."""
    if len(order) - index < 2:
        raise ValueError("There is no other song to skip to.")
    new_order = list(order)
    new_order.append(new_order.pop(index))
    return new_order


def reshuffle_remaining(order: list[int], index: int, rng: random.Random | None = None) -> list[int]:
    """Reshuffle only the songs not yet played; the played prefix never changes."""
    tail = list(order[index:])
    (rng or random.Random()).shuffle(tail)
    return list(order[:index]) + tail


def insert_into_remaining(order: list[int], index: int, song_ids: list[int], rng: random.Random | None = None) -> list[int]:
    """Add songs at random places among the songs still to come. The played prefix never changes."""
    rng = rng or random.Random()
    new_order = list(order)
    for song_id in song_ids:
        new_order.insert(rng.randint(index, len(new_order)), song_id)
    return new_order


def remove_from_remaining(order: list[int], index: int, song_id: int) -> list[int]:
    """Take an unplayed song out of the order. ValueError if it has been played or isn't there."""
    if song_id not in order[index:]:
        raise ValueError("That song has already been played or isn't in this game.")
    new_order = list(order)
    new_order.pop(index + order[index:].index(song_id))
    return new_order


def replace_in_remaining(order: list[int], index: int, old_id: int, new_id: int) -> list[int]:
    """Put another song in the place of an unplayed one, keeping its position in the order."""
    if old_id not in order[index:]:
        raise ValueError("That song has already been played or isn't in this game.")
    new_order = list(order)
    new_order[index + order[index:].index(old_id)] = new_id
    return new_order


def reorder_remaining(order: list[int], index: int, new_tail: list[int]) -> list[int]:
    """Put the songs still to come in the host's chosen order. The played prefix never changes.

    `new_tail` must hold exactly the unplayed songs, each once; anything else (a song played or added meanwhile,
    a song twice) is a ValueError, so a stale page can't drop, repeat or replay a song."""
    tail = list(order[index:])
    if len(new_tail) != len(tail) or sorted(new_tail) != sorted(tail):
        raise ValueError("The playlist changed while you were arranging it.")
    return list(order[:index]) + list(new_tail)


def planned_order(planned: list[int], pool: list[int], rng: random.Random | None = None) -> list[int]:
    """The order to start a game with: the host's planned order where there is one, otherwise a shuffle.

    Songs no longer in the pool are dropped and songs not yet placed go in at random places, so a planned
    order that fell out of step with the pool still starts a valid game."""
    in_pool = set(pool)
    order = [sid for sid in dict.fromkeys(planned) if sid in in_pool]
    missing = [sid for sid in dict.fromkeys(pool) if sid not in set(order)]
    if not order:
        return new_play_order(missing, rng)
    return insert_into_remaining(order, 0, missing, rng)

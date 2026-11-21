import datetime
import random

import pytest

from app.services.branding import VARIABLE_HELP, expand_variables, unknown_variables
from app.services.checker import verify_claim
from app.services.patterns import (
    MAX_SHAPES_PER_ROUND, Line, RoundRules, ShapeDef, describe_line, describe_rules, matching_shape_ids, parse_cells,
    preset_shapes, shapes_from_json, shapes_to_json, validate_rules,
)
from app.services.playlist import insert_into_remaining, remove_from_remaining, replace_in_remaining


def rules(*shapes):
    return RoundRules(mode="shapes", shapes=tuple(shapes))


# ---------------------------------------------------------------- presets and validation

@pytest.mark.parametrize("size", range(3, 10))
def test_every_preset_fits_its_card_size(size):
    presets = preset_shapes(size)
    assert {"Four corners", "X", "L", "T", "Frame"} <= set(presets)
    for name, cells in presets.items():
        assert cells and len(set(cells)) == len(cells) and all(0 <= c < size * size for c in cells), name
        assert validate_rules(rules(ShapeDef(name, cells)), size) == []


def test_odd_sizes_get_a_plus_and_big_odd_sizes_a_diamond():
    assert "Plus" in preset_shapes(5) and "Plus" not in preset_shapes(4)
    assert "Diamond" in preset_shapes(5) and "Diamond" not in preset_shapes(3)


def test_the_l_shape_on_a_5x5_card_is_the_first_column_and_last_row():
    assert preset_shapes(5)["L"] == (0, 5, 10, 15, 20, 21, 22, 23, 24)


def test_a_shape_round_needs_at_least_one_valid_shape():
    assert validate_rules(rules(), 5) == ["Choose at least one custom shape."]
    assert "doesn't fit" in validate_rules(rules(ShapeDef("Big", (0, 99))), 5)[0]
    assert "doesn't fit" in validate_rules(rules(ShapeDef("Empty", ())), 5)[0]
    assert "doesn't fit" in validate_rules(rules(ShapeDef("Twice", (1, 1))), 5)[0]
    too_many = tuple(ShapeDef(f"s{i}", (i % 25,)) for i in range(MAX_SHAPES_PER_ROUND + 1))
    assert "at most" in validate_rules(rules(*too_many), 5)[0]


def test_a_shape_round_is_described_by_its_shape_names():
    assert describe_rules(rules(ShapeDef("L", (0,)), ShapeDef("T", (1,))), 5) == "Custom shape (L or T)"
    assert describe_rules(rules(), 5) == "Custom shape (none chosen)"
    assert describe_line(Line("shape", 0, (0,), "L")) == "shape “L”"


# ---------------------------------------------------------------- the checker

def test_a_card_wins_when_any_one_shape_is_complete():
    cells = list(range(100, 125))  # song ids on a 5x5 card
    shapes = rules(ShapeDef("Corners", preset_shapes(5)["Four corners"]), ShapeDef("L", preset_shapes(5)["L"]))
    corners_played = {cells[i] for i in preset_shapes(5)["Four corners"]}
    result = verify_claim(cells, corners_played, 5, shapes)
    assert result.is_win and [line.name for line in result.completed] == ["Corners"]
    l_played = {cells[i] for i in preset_shapes(5)["L"]}
    assert verify_claim(cells, l_played, 5, shapes).is_win


def test_a_card_missing_a_square_is_rejected_with_the_closest_shape_s_gap():
    cells = list(range(100, 125))
    shapes = rules(ShapeDef("Corners", (0, 4, 20, 24)), ShapeDef("Row", (0, 1, 2, 3, 4)))
    played = {cells[i] for i in (0, 4, 20)}  # corners are one short, the row is two short
    result = verify_claim(cells, played, 5, shapes)
    assert not result.is_win and result.squares_needed == 1 and result.missing_song_ids == (cells[24],)


def test_nothing_played_is_rejected_and_extra_songs_do_not_matter():
    cells = list(range(25))
    assert not verify_claim(cells, set(), 5, rules(ShapeDef("X", (0, 6, 12)))).is_win
    assert verify_claim(cells, set(range(25)), 5, rules(ShapeDef("X", (0, 6, 12)))).is_win


# ---------------------------------------------------------------- storage and matching

def test_shapes_round_trip_through_the_rounds_saved_form():
    shapes = (ShapeDef("L", (0, 5, 10)), ShapeDef("Dot", (12,)))
    assert shapes_from_json(shapes_to_json(shapes)) == shapes
    assert shapes_to_json(()) == "" and shapes_from_json("") == ()


@pytest.mark.parametrize("raw", ["not json", "[1, 2]", '[{"name": "x"}]', '[{"name": "x", "cells": ["a"]}]', "{}"])
def test_damaged_saved_shapes_mean_no_shapes_not_an_error(raw):
    assert shapes_from_json(raw) == ()


def test_cells_are_read_from_their_comma_form():
    assert parse_cells("0,5,10") == (0, 5, 10) and parse_cells("") == () and parse_cells("1,x,3") == (1, 3)


def test_a_round_s_copies_are_matched_back_to_the_global_shapes():
    class Global:  # stand-in for a row of the shape table
        def __init__(self, id, name, cells): self.id, self.name, self.cells = id, name, cells
    available = [Global(1, "L", (0, 5)), Global(2, "T", (0, 1)), Global(3, "L", (9, 9))]
    used = (ShapeDef("L", (0, 5)), ShapeDef("Gone", (4,)))
    assert matching_shape_ids(used, available) == {1}  # same name and squares; a deleted shape matches nothing


# ---------------------------------------------------------------- header and footer variables

TODAY = datetime.date(2026, 11, 5)


def test_variables_are_filled_in():
    assert expand_variables("Iron Horse - ${GAME.NAME}", game_name="90s Night") == "Iron Horse - 90s Night"
    assert expand_variables("${ game.name } on ${GAME.DATE}", game_name="Quiz", today=TODAY) == "Quiz on November 5, 2026"
    assert expand_variables("no variables", game_name="x") == "no variables"


def test_a_game_name_is_inserted_as_plain_text_and_never_evaluated():
    tricky = "${GAME.DATE} <b>{{ 7*7 }}</b> ${GAME.NAME}"
    out = expand_variables("Hi ${GAME.NAME}", game_name=tricky, today=TODAY)
    assert out == f"Hi {tricky}"  # substituted once, not re-expanded; braces and tags untouched


def test_unknown_variables_are_listed_and_left_as_typed():
    assert unknown_variables("${GAME.NAME} ${BAR.NAME} ${ nope }") == ["${BAR.NAME}", "${ nope }"]
    assert unknown_variables("plain ${GAME.DATE}") == []
    assert expand_variables("${BAR.NAME}", game_name="x") == "${BAR.NAME}"
    assert "GAME.NAME" in VARIABLE_HELP and "GAME.DATE" in VARIABLE_HELP


# ---------------------------------------------------------------- editing the play order

def test_added_songs_land_among_the_songs_still_to_come():
    order = [1, 2, 3, 4, 5]
    for seed in range(30):
        new = insert_into_remaining(order, 2, [8, 9], random.Random(seed))
        assert new[:2] == [1, 2] and sorted(new) == [1, 2, 3, 4, 5, 8, 9]  # the played prefix never changes


def test_removing_only_works_on_songs_still_to_come():
    assert remove_from_remaining([1, 2, 3, 4], 2, 4) == [1, 2, 3]
    with pytest.raises(ValueError):
        remove_from_remaining([1, 2, 3, 4], 2, 2)  # already played
    with pytest.raises(ValueError):
        remove_from_remaining([1, 2, 3, 4], 2, 99)


def test_replacing_keeps_the_songs_place_in_the_order():
    assert replace_in_remaining([1, 2, 3, 4], 1, 3, 9) == [1, 2, 9, 4]
    with pytest.raises(ValueError):
        replace_in_remaining([1, 2, 3, 4], 2, 1, 9)  # already played

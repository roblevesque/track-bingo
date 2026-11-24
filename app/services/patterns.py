"""What counts as a win in a round, on an N x N ticket. Pure Python, no framework.

Cells are numbered row-major: on a 5x5 ticket, row 2 column 3 is position 2*5+3 = 13.
The host chooses the rules per round and may change them as the game goes on, so
rules are plain data that the checker takes as an argument.
"""

import json
from dataclasses import dataclass

MODE_LINES = "lines"
MODE_FULL_HOUSE = "full_house"
MODE_SHAPES = "shapes"
MODES = (MODE_LINES, MODE_FULL_HOUSE, MODE_SHAPES)
MAX_SHAPES_PER_ROUND = 30
MAX_SHAPE_NAME = 40


@dataclass(frozen=True)
class ShapeDef:
    """A custom winning pattern: these squares (row-major positions) must all be played."""

    name: str
    cells: tuple[int, ...]


@dataclass(frozen=True)
class RoundRules:
    mode: str = MODE_LINES
    lines_required: int = 1  # how many complete lines win (lines mode only)
    rows: bool = True
    columns: bool = False
    diagonals: bool = False
    shapes: tuple[ShapeDef, ...] = ()  # used when mode is "shapes": completing any one of them wins


@dataclass(frozen=True)
class Line:
    kind: str  # "row" | "column" | "diagonal" | "shape"
    index: int  # row or column number; diagonals: 0 = top-left to bottom-right, 1 = the other; shapes: position in the list
    cells: tuple[int, ...]
    name: str = ""  # shapes only


def all_lines(size: int, *, rows: bool, columns: bool, diagonals: bool) -> list[Line]:
    lines: list[Line] = []
    if rows:
        for r in range(size):
            lines.append(Line("row", r, tuple(r * size + c for c in range(size))))
    if columns:
        for c in range(size):
            lines.append(Line("column", c, tuple(r * size + c for r in range(size))))
    if diagonals:
        lines.append(Line("diagonal", 0, tuple(i * size + i for i in range(size))))
        lines.append(Line("diagonal", 1, tuple(i * size + (size - 1 - i) for i in range(size))))
    return lines


def enabled_lines(size: int, rules: RoundRules) -> list[Line]:
    return all_lines(size, rows=rules.rows, columns=rules.columns, diagonals=rules.diagonals)


def validate_rules(rules: RoundRules, size: int) -> list[str]:
    """Human-readable problems with these rules for a ticket of this size (empty = fine)."""
    if rules.mode not in MODES:
        return ["Unknown pattern type."]
    if rules.mode == MODE_FULL_HOUSE:
        return []
    if rules.mode == MODE_SHAPES:
        if not rules.shapes:
            return ["Choose at least one custom shape."]
        if len(rules.shapes) > MAX_SHAPES_PER_ROUND:
            return [f"A round can use at most {MAX_SHAPES_PER_ROUND} shapes."]
        for shape in rules.shapes:
            if not shape.cells or len(set(shape.cells)) != len(shape.cells) or not all(0 <= c < size * size for c in shape.cells):
                return [f"The shape \u201c{shape.name}\u201d doesn't fit a {size}\u00d7{size} card."]
        return []
    available = len(enabled_lines(size, rules))
    if available == 0:
        return ["Choose at least one of rows, columns or diagonals."]
    if not 1 <= rules.lines_required <= available:
        return [f"Lines required must be between 1 and {available} for the chosen line types."]
    return []


def _join_or(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " or " + items[-1]


def describe_rules(rules: RoundRules, size: int) -> str:
    if rules.mode == MODE_FULL_HOUSE:
        return "Full house (every square)"
    if rules.mode == MODE_SHAPES:
        names = [shape.name for shape in rules.shapes]
        return f"Custom shape ({_join_or(names)})" if names else "Custom shape (none chosen)"
    kinds = [
        name
        for name, enabled in (("rows", rules.rows), ("columns", rules.columns), ("diagonals", rules.diagonals))
        if enabled
    ]
    count = rules.lines_required
    return f"{count} line{'' if count == 1 else 's'} ({_join_or(kinds) if kinds else 'none'})"


def describe_line(line: Line) -> str:
    """'row 2', 'column 4', 'diagonal (top-left to bottom-right)' for showing to the host."""
    if line.kind == "shape":
        return f"shape \u201c{line.name}\u201d"
    if line.kind == "diagonal":
        return "diagonal (top-left to bottom-right)" if line.index == 0 else "diagonal (top-right to bottom-left)"
    return f"{line.kind} {line.index + 1}"


# ---- custom shapes: storage form, presets and matching


def shapes_to_json(shapes) -> str:
    return json.dumps([{"name": s.name, "cells": list(s.cells)} for s in shapes], separators=(",", ":")) if shapes else ""


def shapes_from_json(raw: str) -> tuple[ShapeDef, ...]:
    """Shapes saved with a round. Bad or empty data gives no shapes rather than an error."""
    if not raw:
        return ()
    try:
        items = json.loads(raw)
        return tuple(ShapeDef(str(i["name"]), tuple(int(c) for c in i["cells"])) for i in items)
    except (ValueError, TypeError, KeyError):
        return ()


def parse_cells(raw: str) -> tuple[int, ...]:
    """'0,1,2' as saved on a shape. Bad pieces are skipped."""
    return tuple(int(part) for part in raw.split(",") if part.strip().isdigit())


def preset_shapes(size: int) -> dict[str, tuple[int, ...]]:
    """Common shapes for a size x size card, by name. Shapes that don't exist at this size are left out."""
    n = size
    cell = lambda r, c: r * n + c  # noqa: E731
    mid = n // 2
    presets: dict[str, set[int]] = {
        "Four corners": {cell(0, 0), cell(0, n - 1), cell(n - 1, 0), cell(n - 1, n - 1)},
        "X": {cell(i, i) for i in range(n)} | {cell(i, n - 1 - i) for i in range(n)},
        "L": {cell(r, 0) for r in range(n)} | {cell(n - 1, c) for c in range(n)},
        "T": {cell(0, c) for c in range(n)} | {cell(r, mid) for r in range(n)},
        "Frame": {cell(r, c) for r in range(n) for c in range(n) if r in (0, n - 1) or c in (0, n - 1)},
    }
    if n % 2 == 1:
        presets["Plus"] = {cell(mid, c) for c in range(n)} | {cell(r, mid) for r in range(n)}
        if n >= 5:
            presets["Diamond"] = {cell(r, c) for r in range(n) for c in range(n) if abs(r - mid) + abs(c - mid) == mid}
    return {name: tuple(sorted(cells)) for name, cells in presets.items()}


def matching_shape_ids(round_shapes, available) -> set[int]:
    """Ids of the global shapes (objects with id, name and cells) that a round's saved shapes were copied from."""
    wanted = {(s.name, tuple(s.cells)) for s in round_shapes}
    # A stored WinShape keeps its cells as text ("0,2,6,8"); its cell_list is the tuple to compare.
    return {a.id for a in available if (a.name, tuple(getattr(a, "cell_list", a.cells))) in wanted}

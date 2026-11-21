"""Looking up custom win shapes in the database (the pure rules live in patterns.py)."""

from sqlalchemy import func
from sqlmodel import Session, select

from app.models import Game, Round, WinShape
from app.services.patterns import MAX_SHAPE_NAME, ShapeDef, matching_shape_ids


def shapes_for_size(session: Session, size: int) -> list[WinShape]:
    return list(session.exec(select(WinShape).where(WinShape.size == size).order_by(func.lower(WinShape.name), WinShape.id)).all())


def resolve_shapes(session: Session, game: Game, ids: list[int]) -> list[ShapeDef]:
    """The shapes with these ids that fit this game's grid, in list order. Others are ignored."""
    if not ids:
        return []
    chosen = {s.id: s for s in shapes_for_size(session, game.grid_size) if s.id in set(ids)}
    return [chosen[i].as_def() for i in dict.fromkeys(ids) if i in chosen]


def selected_ids(round_: Round, available: list[WinShape]) -> set[int]:
    return matching_shape_ids(round_.rules().shapes, available)


def clean_name(raw: str) -> str:
    return " ".join(raw.split())[:MAX_SHAPE_NAME]

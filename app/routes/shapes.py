"""Custom win shapes: draw a pattern once, then tick it for any round of any game with that card size."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlmodel import Session, select

from app.db import get_session
from app.deps import require_user
from app.models import User, WinShape
from app.routes.games import DEFAULT_GRID, MAX_GRID, MIN_GRID
from app.security import check_csrf
from app.services.patterns import MAX_SHAPE_NAME, preset_shapes
from app.services.shapes_store import clean_name
from app.web import flash, render

router = APIRouter(prefix="/shapes")

MAX_SHAPES = 200


def _redirect(size: int) -> RedirectResponse:
    return RedirectResponse(f"/shapes?size={size}", status_code=303)


def _size(raw: str | int | None) -> int:
    try:
        size = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_GRID
    return size if MIN_GRID <= size <= MAX_GRID else DEFAULT_GRID


@router.get("")
def shapes_page(request: Request, size: str = "", user: User = Depends(require_user), session: Session = Depends(get_session)):
    chosen = _size(size)
    shapes = session.exec(select(WinShape).order_by(WinShape.size, func.lower(WinShape.name), WinShape.id)).all()
    return render(
        request, "shapes.html", user=user, size=chosen, sizes=list(range(MIN_GRID, MAX_GRID + 1)),
        shapes=[{"id": s.id, "name": s.name, "size": s.size, "cells": set(s.cell_list)} for s in shapes],
        presets=list(preset_shapes(chosen)),
    )


@router.post("")
def create_shape(
    request: Request,
    name: str = Form(""),
    size: str = Form(""),
    cell: list[int] = Form(default=[]),
    csrf_token: str = Form(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    check_csrf(request, csrf_token)
    grid = _size(size)
    name = clean_name(name)
    cells = sorted({c for c in cell if 0 <= c < grid * grid})
    problem = None
    if not name:
        problem = "Give the shape a name."
    elif not cells:
        problem = "Click at least one square to make up the shape."
    elif session.exec(select(WinShape).where(WinShape.size == grid, func.lower(WinShape.name) == name.lower())).first():
        problem = f"There is already a {grid}×{grid} shape called “{name}”."
    elif session.exec(select(func.count(WinShape.id))).one() >= MAX_SHAPES:
        problem = "There are too many shapes already; delete some first."
    if problem:
        flash(request, problem, "error")
        return _redirect(grid)
    session.add(WinShape(name=name[:MAX_SHAPE_NAME], size=grid, cells=",".join(map(str, cells))))
    session.commit()
    flash(request, f"Saved the shape “{name}”.", "success")
    return _redirect(grid)


@router.post("/presets")
def add_presets(
    request: Request,
    size: str = Form(""),
    csrf_token: str = Form(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    """Add the common shapes (L, T, X, frame, corners, plus, diamond) for a card size, skipping any already there."""
    check_csrf(request, csrf_token)
    grid = _size(size)
    have = {s.name.lower() for s in session.exec(select(WinShape).where(WinShape.size == grid)).all()}
    added = 0
    for name, cells in preset_shapes(grid).items():
        if name.lower() not in have:
            session.add(WinShape(name=name, size=grid, cells=",".join(map(str, cells))))
            added += 1
    session.commit()
    flash(request, f"Added {added} common shape{'s' if added != 1 else ''} for {grid}×{grid} cards." if added
          else f"The common shapes for {grid}×{grid} cards are already there.", "success")
    return _redirect(grid)


@router.post("/{shape_id}/delete")
def delete_shape(
    request: Request,
    shape_id: int,
    csrf_token: str = Form(""),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
):
    """Rounds keep their own copy of a shape, so deleting one here never breaks a game."""
    check_csrf(request, csrf_token)
    shape = session.get(WinShape, shape_id)
    size = shape.size if shape else DEFAULT_GRID
    if shape:
        session.delete(shape)
        session.commit()
        flash(request, "Shape deleted. Rounds that already use it keep working.", "success")
    return _redirect(size)

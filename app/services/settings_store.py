"""Small site-wide settings kept in the database (shared by every account)."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # the parsing helper below stays importable (and testable) without the database libraries
    from sqlmodel import Session

DEFAULT_CLIP_SECONDS = 30
MIN_CLIP_SECONDS = 1
MAX_CLIP_SECONDS = 300


def get_clip_seconds(session: "Session") -> int:
    """How long a clip should be, used to fill in the other end when one end is set."""
    from app.models import AppSetting

    row = session.get(AppSetting, "clip_seconds")
    try:
        value = int(row.value) if row else DEFAULT_CLIP_SECONDS
    except ValueError:
        value = DEFAULT_CLIP_SECONDS
    return min(MAX_CLIP_SECONDS, max(MIN_CLIP_SECONDS, value))


def parse_clip_seconds(raw: str) -> int:
    """Whole seconds from a form field; ValueError with a readable message when it isn't usable."""
    try:
        value = int(float(raw.strip()))
    except (ValueError, OverflowError, AttributeError):
        raise ValueError("Enter the clip length as a whole number of seconds.") from None
    if not MIN_CLIP_SECONDS <= value <= MAX_CLIP_SECONDS:
        raise ValueError(f"The clip length must be between {MIN_CLIP_SECONDS} and {MAX_CLIP_SECONDS} seconds.")
    return value


def set_clip_seconds(session: "Session", seconds: int) -> None:
    from app.models import AppSetting

    row = session.get(AppSetting, "clip_seconds") or AppSetting(key="clip_seconds")
    row.value = str(seconds)
    session.add(row)
    session.commit()


def _view_key(user_id: int) -> str:
    return f"library_view:{user_id}"


def get_library_view(session: "Session", user_id: int) -> tuple[str, str, int]:
    """(sort, show, songs per page) this person last chose on the library page, so it looks the same from visit to visit."""
    from app.models import AppSetting
    from app.services.paging import clean_per_page
    from app.services.search import DEFAULT_SHOW, DEFAULT_SORT, SHOWS, SORTS

    row = session.get(AppSetting, _view_key(user_id))
    sort, _, rest = (row.value if row else "").partition("|")
    show, _, per_page = rest.partition("|")
    return (sort if sort in SORTS else DEFAULT_SORT), (show if show in SHOWS else DEFAULT_SHOW), clean_per_page(per_page)


def set_library_view(session: "Session", user_id: int, sort: str, show: str, per_page: int) -> None:
    from app.models import AppSetting

    value = f"{sort}|{show}|{per_page}"
    row = session.get(AppSetting, _view_key(user_id))
    if row is not None and row.value == value:
        return
    row = row or AppSetting(key=_view_key(user_id))
    row.value = value
    session.add(row)
    session.commit()

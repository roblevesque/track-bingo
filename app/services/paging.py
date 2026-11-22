"""Splitting a long list into pages, and the page numbers to show in a pager. Pure Python."""

from __future__ import annotations

from dataclasses import dataclass

PER_PAGE_OPTIONS = (25, 50, 100, 200)
DEFAULT_PER_PAGE = 50


@dataclass(frozen=True)
class Page:
    page: int  # 1-based, already limited to the pages that exist
    pages: int
    per_page: int
    total: int

    @property
    def start(self) -> int:  # index of the first item on the page
        return (self.page - 1) * self.per_page

    @property
    def stop(self) -> int:
        return min(self.total, self.start + self.per_page)


def clean_page(raw: object) -> int:
    """A page number from a query string or form: anything unusable means page 1."""
    try:
        return max(1, min(int(str(raw).strip()), 1_000_000))
    except ValueError:
        return 1


def clean_per_page(raw: object, default: int = DEFAULT_PER_PAGE) -> int:
    try:
        value = int(str(raw).strip())
    except ValueError:
        return default
    return value if value in PER_PAGE_OPTIONS else default


def paginate(total: int, page: int, per_page: int) -> Page:
    """The page to show: a page past the end (after deleting songs, say) becomes the last page."""
    per_page = per_page if per_page in PER_PAGE_OPTIONS else DEFAULT_PER_PAGE
    pages = max(1, -(-total // per_page))
    return Page(min(max(1, page), pages), pages, per_page, total)


def page_links(page: int, pages: int, around: int = 2) -> list[int | None]:
    """Numbers for a pager: first, last, and a few around the current page; None marks a gap (shown as an ellipsis)."""
    wanted = sorted({1, pages, *range(max(1, page - around), min(pages, page + around) + 1)})
    out: list[int | None] = []
    for n in wanted:
        if out and n - out[-1] == 2:  # type: ignore[operator]
            out.append(n - 1)  # a gap of one page is shown, not hidden behind an ellipsis
        elif out and n - out[-1] > 2:  # type: ignore[operator]
            out.append(None)
        out.append(n)
    return out

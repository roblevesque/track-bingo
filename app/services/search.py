"""The library search box: words to find, `!tag` to leave a tag out, and `no:tags` for untagged songs.

    rock 80s          title, artist or tag contains both words
    !live             leave out songs tagged exactly "live"
    !"classic rock"   quotes for a tag with a space in it
    no:tags           only songs with no tags at all
    "dancing queen"   quotes keep a phrase together

Pure Python, so it is easy to test; app/static/app.js does the same for the new-game song picker.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MAX_QUERY = 100
UNTAGGED = "no:tags"


@dataclass(frozen=True)
class Query:
    words: tuple[str, ...] = ()
    excluded_tags: tuple[str, ...] = ()
    untagged: bool = False
    extra: dict = field(default_factory=dict, compare=False)

    @property
    def empty(self) -> bool:
        return not (self.words or self.excluded_tags or self.untagged)


def _tokens(text: str) -> list[tuple[str, bool]]:
    """Split on spaces, keeping "quoted phrases" together. Returns (token, started_with_!) pairs."""
    out, i, n = [], 0, len(text)
    while i < n:
        if text[i].isspace():
            i += 1
            continue
        negate = text[i] == "!"
        if negate:
            i += 1
        if i < n and text[i] == '"':
            end = text.find('"', i + 1)
            end = n if end == -1 else end
            token, i = text[i + 1:end], end + 1
        else:
            start = i
            while i < n and not text[i].isspace():
                i += 1
            token = text[start:i]
        token = " ".join(token.split()).lower()
        if token:
            out.append((token, negate))
        # a lone "!" with nothing after it is ignored
    return out


def parse_query(text: str) -> Query:
    words, excluded, untagged = [], [], False
    for token, negate in _tokens(text[:MAX_QUERY]):
        if negate:
            if token not in excluded:
                excluded.append(token)
        elif token == UNTAGGED:
            untagged = True
        else:
            words.append(token)
    return Query(tuple(words), tuple(excluded), untagged)


def matches(query: Query, title: str, artist: str, tags: str) -> bool:
    """Whether a song (tags as stored: lower case, comma separated) satisfies the query."""
    tag_list = [t for t in tags.split(",") if t]
    if query.untagged and tag_list:
        return False
    if any(tag in tag_list for tag in query.excluded_tags):
        return False
    haystack = f"{title} {artist} {tags}".lower()
    return all(word in haystack for word in query.words)


# ---------------------------------------------------------------- ordering and the play-window filter

SORTS = {
    "title": "Title (A\u2013Z)",
    "title_desc": "Title (Z\u2013A)",
    "artist": "Artist (A\u2013Z)",
    "added": "Newest added first",
    "edited": "Recently edited first",
    "window": "Play window not set first",
}
SHOWS = {"all": "All songs", "todo": "Play window not set", "done": "Play window set"}
DEFAULT_SORT, DEFAULT_SHOW = "title", "all"


def has_window(song) -> bool:
    """A song counts as set up once it has a start or an end time (otherwise it plays as the full track)."""
    return bool(song.start_ms or song.end_ms)


def sort_songs(songs: list, sort: str) -> list:
    """The songs in the chosen order; ties fall back to title then id, so the order is always stable."""
    base = lambda s: (s.title.lower(), s.id)  # noqa: E731
    if sort == "title_desc":
        return sorted(songs, key=base, reverse=True)
    if sort == "artist":
        return sorted(songs, key=lambda s: (not s.artist, s.artist.lower(), *base(s)))  # songs with no artist last
    if sort == "added":
        return sorted(songs, key=lambda s: (s.created_at, s.id), reverse=True)
    if sort == "edited":
        return sorted(songs, key=lambda s: (s.updated_at or s.created_at, s.id), reverse=True)
    if sort == "window":
        return sorted(songs, key=lambda s: (has_window(s), *base(s)))
    return sorted(songs, key=base)


def filter_show(songs: list, show: str) -> list:
    if show == "todo":
        return [s for s in songs if not has_window(s)]
    if show == "done":
        return [s for s in songs if has_window(s)]
    return songs

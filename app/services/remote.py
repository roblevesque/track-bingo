"""Phone remote: pairing codes, command checking and the slimmed-down state a phone needs.

Pure Python, no framework or database. The remote works by relaying commands through the server to the
host's console (which plays the audio), so everything here is about deciding what may be relayed.
"""

import secrets
import time
from collections import deque
from collections.abc import Callable, Collection

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I, which are easy to mix up when typing
CODE_LENGTH = 6
COMMANDS = ("next", "replay", "pause", "skip", "start", "next_round", "effect", "stop_effect")
MAX_COUNT = 100_000


def new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def normalize_code(raw: str) -> str:
    return "".join(ch for ch in raw.upper() if ch.isalnum())


class AttemptLimiter:
    """Stops someone guessing pairing codes: after `max_attempts` wrong tries within the window, that
    key (a client address) is blocked until the old attempts age out. In memory, which suits one worker."""

    def __init__(self, max_attempts: int = 8, window_seconds: float = 300.0, clock: Callable[[], float] = time.monotonic):
        self.max_attempts, self.window, self._clock = max_attempts, window_seconds, clock
        self._failures: dict[str, deque[float]] = {}

    def _recent(self, key: str) -> deque[float]:
        attempts = self._failures.get(key)
        if attempts is None:
            return deque()
        cutoff = self._clock() - self.window
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()
        if not attempts:
            del self._failures[key]
            return deque()
        return attempts

    def blocked(self, key: str) -> bool:
        return len(self._recent(key)) >= self.max_attempts

    def record_failure(self, key: str) -> None:
        self._recent(key)  # tidy up first
        self._failures.setdefault(key, deque()).append(self._clock())

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)


def _count(text: str, what: str) -> int:
    if not text.isdigit() or int(text) > MAX_COUNT:
        raise ValueError(f"{what} is not a valid number.")
    return int(text)


def validate_command(
    action: str, effect: str = "", expect: str = "", expect_next: str = "", effect_ids: Collection[str] = ()
) -> dict:
    """Check a command from a phone and return the clean version to relay to the console."""
    if action not in COMMANDS:
        raise ValueError("Unknown command.")
    command: dict = {"action": action}
    if action == "effect":
        if effect not in effect_ids:
            raise ValueError("Unknown sound effect.")
        command["effect"] = effect
    if action == "next" and expect != "":
        command["expect"] = _count(expect, "The song count")  # only advance if the game is still at this count
    if action == "skip" and expect_next != "":
        command["expect_next"] = _count(expect_next, "The song")  # only skip if this is still the next song
    return command


MAX_CLIP_SECONDS = 6 * 3600


def _seconds(text: str, what: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise ValueError(f"{what} is not a number.") from None
    if not 0 <= value <= MAX_CLIP_SECONDS:  # also refuses nan and inf
        raise ValueError(f"{what} is out of range.")
    return value


def parse_playback(song_id: int, elapsed: str, length: str, paused: str) -> dict:
    """Check a clip-position report from the host console. `length` may be blank while it isn't known yet."""
    seconds = _seconds(elapsed or "0", "The position")
    total = _seconds(length, "The clip length") if length.strip() else None
    if total is not None:
        seconds = min(seconds, total)
    return {"song_id": song_id, "elapsed": round(seconds, 2), "length": total, "paused": bool(paused)}


def playback_now(report: dict, reported_at: float, now: float) -> dict:
    """A report brought up to `now`: a clip that was playing has moved on since it was sent."""
    elapsed = report["elapsed"]
    if not report["paused"]:
        elapsed += max(0.0, now - reported_at)
        if report["length"] is not None:
            elapsed = min(elapsed, report["length"])
    return {**report, "elapsed": round(elapsed, 2)}


def remote_view(host: dict, console_online: bool) -> dict:
    """What a phone needs from the host snapshot: no songs still to come (beyond the next one), no teams, no join or
    remote codes."""
    current, upcoming, round_ = host.get("current_song"), host.get("next_song"), host.get("round")
    wins = [c for c in host.get("claims", []) if c["status"] == "win"]
    return {
        "name": host["game"]["name"],
        "status": host["game"]["status"],
        "round": {"number": round_["number"], "name": round_["name"], "text": round_["text"]} if round_ else None,
        "has_next_round": bool(round_) and any(r["number"] == round_["number"] + 1 for r in host.get("rounds", [])),
        "songs_played": host["songs_played"],
        "total_songs": host["total_songs"],
        "current": {"id": current["id"], "title": current["title"], "artist": current["artist"], "fun_fact": current.get("fun_fact", "")} if current else None,
        "next": {"id": upcoming["id"], "title": upcoming["title"], "artist": upcoming["artist"], "fun_fact": upcoming.get("fun_fact", "")}
        if upcoming else None,
        # Songs already heard, newest first (the first is the one playing now). Nothing still to come.
        "played": [{"n": p["n"], "title": p["title"], "artist": p["artist"]} for p in host.get("played", [])],
        "wins": [  # oldest first, so ties read in order
            {"team": c["team"], "ticket": c["ticket"], "songs_played": c["songs_played"], "detail": c["detail"]}
            for c in reversed(wins)
        ],
        "effects": [{"id": e["id"], "label": e["label"], "loop": e["loop"]} for e in host.get("effects", [])],
        "console_online": console_online,
    }

"""Evening out clip volumes: how much louder or quieter the console plays each song.

The loudness of a song's clip window is measured in the browser (`app/static/loudness.js`, in LUFS, the broadcast
standard) and stored with the window it was measured for, so moving the start or end makes it out of date. The
console then plays each clip at `playback_gain_db`: the difference from a common target, plus the host's own nudge.
Nothing re-encodes the audio file.
"""

import math

TARGET_LUFS = -16.0  # most commercial songs are louder than this, so most are turned down rather than up
MAX_BOOST_DB = 10.0  # a very quiet (or silent) clip is raised this much at most
MAX_CUT_DB = 20.0
MAX_ADJUST_DB = 12.0  # the host's own nudge, either way
QUIETEST_LUFS = -70.0


def window_key(start_ms: int, end_ms: int | None) -> str:
    """Which clip window a measurement belongs to, e.g. '30000:60000' ('30000:' plays to the end)."""
    return f"{start_ms}:{'' if end_ms is None else end_ms}"


def is_measured(song) -> bool:
    """Has this song's current clip window been measured?"""
    return song.loudness_db is not None and song.loudness_for == window_key(song.start_ms, song.end_ms)


def playback_gain_db(song) -> float:
    """dB to apply when the console plays this song: towards the target if measured, plus the host's nudge."""
    level = 0.0
    if is_measured(song):
        level = min(MAX_BOOST_DB, max(-MAX_CUT_DB, TARGET_LUFS - song.loudness_db))
    return round(level + (song.volume_adjust_db or 0.0), 1)


def _number(text: str, what: str) -> float:
    try:
        value = float(text)
    except (TypeError, ValueError):
        raise ValueError(f"{what} must be a number.") from None
    if not math.isfinite(value):
        raise ValueError(f"{what} must be a number.")
    return value


def parse_loudness(text: str) -> float:
    """A measurement from the browser, in LUFS. Silence is stored as the quietest value."""
    value = _number(text, "The loudness")
    if value > 0:
        raise ValueError("The loudness can't be above 0 LUFS.")
    return round(max(QUIETEST_LUFS, value), 2)


def parse_adjust(text: str) -> float:
    """The host's volume nudge in dB ('' means none)."""
    if not str(text).strip():
        return 0.0
    value = _number(text, "The volume adjustment")
    if abs(value) > MAX_ADJUST_DB:
        raise ValueError(f"The volume adjustment must be between -{MAX_ADJUST_DB:g} and +{MAX_ADJUST_DB:g} dB.")
    return round(value, 1)


def describe(song) -> str:
    """For the song's edit page, e.g. 'Measured at -9.8 LUFS, so it plays 6.2 dB quieter.'"""
    gain = playback_gain_db(song)
    if song.loudness_db is None:
        state = "Not measured yet."
    elif not is_measured(song):
        state = "Measured before the clip times last changed, so it needs measuring again."
    else:
        state = f"Measured at {song.loudness_db:.1f} LUFS."
    if abs(gain) < 0.05:
        return f"{state} Plays at its own volume."
    return f"{state} Plays {abs(gain):.1f} dB {'louder' if gain > 0 else 'quieter'}."

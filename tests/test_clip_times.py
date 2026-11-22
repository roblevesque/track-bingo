import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.services.parsing import format_time_ms, parse_time_ms

HERE = Path(__file__).parent
TEXTS = [
    "75", "75.5", "1:15", "1:15.5", "0:30.1", "1:30.1", "1:30", "30.1", "30", "0:30", "1:15,5", "30,1", "12:34:56.7",
    "0:00.0", ".5", "5.", " 1:30.1 ", "", "   ", "abc", "1:2:3:4", "-5", "1::2", "1:", ":30", "1:30.1.5", "1:xx", "0:60", "99:59.9",
]
MILLIS = [0, 100, 900, 59900, 60000, 60100, 90100, 119900, 120000, 3599900, 30100, 30000, 1000, 61000]


def python_reads(text):
    try:
        ms = parse_time_ms(text)
    except ValueError:
        return "error"
    return ms


def test_a_minute_and_a_second_with_a_decimal_is_read_like_any_other_time():
    assert parse_time_ms("0:30.1") == 30100
    assert parse_time_ms("1:30.1") == 90100
    assert parse_time_ms("1:30") == 90000
    assert parse_time_ms("30.1") == 30100
    assert parse_time_ms("1:30,1") == 90100  # a decimal comma
    assert parse_time_ms("") is None and parse_time_ms("  ") is None
    for bad in ("1:2:3:4", "-5", "abc", "1:", ":30"):
        with pytest.raises(ValueError):
            parse_time_ms(bad)


def test_times_are_written_back_the_way_they_are_read():
    for text in ("0:30.1", "1:30.1", "1:30.0", "0:00.1"):
        assert format_time_ms(parse_time_ms(text)) == text


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js isn't installed (only needed for this check)")
def test_the_browser_reads_and_writes_times_exactly_like_the_server(tmp_path):
    texts, millis = tmp_path / "texts.json", tmp_path / "millis.json"
    texts.write_text(json.dumps(TEXTS))
    millis.write_text(json.dumps(MILLIS))
    out = subprocess.run(["node", str(HERE / "js" / "time_check.mjs"), str(texts), str(millis)],
                         capture_output=True, text=True, timeout=60, check=True)
    result = json.loads(out.stdout)
    for text, seconds in zip(TEXTS, result["parsed"]):
        expected = python_reads(text)
        got = "error" if seconds is None and text.strip() else (None if seconds is None else round(seconds * 1000))
        assert got == expected, text
    assert result["formatted"] == [format_time_ms(ms) for ms in MILLIS]

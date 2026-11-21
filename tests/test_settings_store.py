import pytest

from app.services.settings_store import DEFAULT_CLIP_SECONDS, MAX_CLIP_SECONDS, MIN_CLIP_SECONDS, parse_clip_seconds


def test_whole_seconds_are_accepted():
    assert parse_clip_seconds("30") == 30
    assert parse_clip_seconds(" 45 ") == 45
    assert parse_clip_seconds("12.9") == 12  # a stray decimal is cut, not refused


@pytest.mark.parametrize("raw", ["", "abc", "0", str(MAX_CLIP_SECONDS + 1), "-5", "nan"])
def test_unusable_values_are_refused_with_a_readable_message(raw):
    with pytest.raises(ValueError) as caught:
        parse_clip_seconds(raw)
    assert "seconds" in str(caught.value)


def test_the_default_is_inside_the_allowed_range():
    assert MIN_CLIP_SECONDS <= DEFAULT_CLIP_SECONDS <= MAX_CLIP_SECONDS

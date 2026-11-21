import json
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).parent


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js isn't installed (only needed for this check)")
def test_the_section_finder_picks_the_choruses_of_a_synthetic_song():
    """A 150 s song: quiet verses with changing notes, and two loud 30 s choruses (38-68 s and 98-128 s)."""
    out = subprocess.run(["node", str(HERE / "js" / "suggest_check.mjs")], capture_output=True, text=True, timeout=60, check=True)
    result = json.loads(out.stdout)
    top_two = result["found"][:2]
    starts = sorted(round(w["start"]) for w in top_two)
    assert [abs(s - t) <= 2 for s, t in zip(starts, (38, 98))] == [True, True]
    assert all(abs((w["end"] - w["start"]) - 30) < 0.01 for w in result["found"])
    assert result["found"][0]["loud"] > 0.9 and result["found"][0]["repeat"] > 0.9
    starts_all = [w["start"] for w in result["found"]]
    assert all(abs(a - b) >= 30 for i, a in enumerate(starts_all) for b in starts_all[i + 1:])  # no overlaps
    assert result["tooShort"] == []  # a song shorter than the clip gets no suggestions

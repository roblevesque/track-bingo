import json
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).parent


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js isn't installed (only needed for this check)")
def test_the_loudness_meter_matches_the_broadcast_standard():
    """BS.1770 calibration: a full-scale 997 Hz sine reads -3.01 LUFS on one channel and 0 LUFS on two."""
    out = subprocess.run(["node", str(HERE / "js" / "loudness_check.mjs")], capture_output=True, text=True, timeout=60, check=True)
    r = json.loads(out.stdout)
    assert r["monoFull"] == pytest.approx(-3.01, abs=0.05)
    assert r["stereoFull"] == pytest.approx(0.0, abs=0.05)
    assert r["stereoHalf"] == pytest.approx(-6.02, abs=0.05)  # half the amplitude is 6 dB quieter
    assert r["at44k"] == pytest.approx(-3.01, abs=0.05)  # same answer at another sample rate
    assert r["quietWindow"] == pytest.approx(-23.01, abs=0.05) and r["loudWindow"] == pytest.approx(-3.01, abs=0.05)
    assert r["silent"] == r["SILENT"] and r["tooShort"] == r["SILENT"]

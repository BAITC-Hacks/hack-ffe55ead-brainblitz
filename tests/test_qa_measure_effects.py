"""Independent numerical checks for measures not isolated by the A/B examples.

Expected deltas are hand-calculated from the original DOCX, not simulation.py:
M3: (16, 20, 4) * 4/8; M5: (14, 4) * 5/8;
M8: 14 * 5/8; M13: (18, 2) * 4/8.
The controlled all-50 city makes every affected and unaffected cell observable.
Single measures intentionally exercise the mathematical helper, not HTTP rules.
"""

from copy import deepcopy

import pytest

from app.models import Selection
from app.simulation import apply_effects


@pytest.mark.parametrize("measure_id,realized", [
    ("M3", {"T1": 8.0, "T2": 10.0, "E2": 2.0}),
    ("M5", {"E2": 8.75, "C1": 2.5}),
    ("M8", {"S2": 8.75}),
    ("M13", {"C1": 9.0, "E2": 1.0}),
])
def test_remaining_local_measures_have_exact_lagged_effects(
    expected_config, measure_id, realized,
):
    config = deepcopy(expected_config)
    for district in config["districts"]:
        district["indicators"] = {key: 50.0 for key in config["indicators"]}
    original = deepcopy(config)

    after, effects, synergies = apply_effects(
        [Selection(measure_id=measure_id, district_id="nura")], config,
    )

    assert len(effects) == 1
    assert effects[0].measure_id == measure_id
    assert effects[0].scope == "district"
    assert effects[0].district_id == "nura"
    assert effects[0].realized_effects == pytest.approx(realized, abs=1e-8, rel=0)
    assert synergies == []
    assert set(after) == {"esil", "almaty", "saryarka", "baikonur", "nura"}
    for district_id, indicators in after.items():
        expected = {
            key: 50.0 + (realized.get(key, 0.0) if district_id == "nura" else 0.0)
            for key in ("T1", "T2", "E1", "E2", "S1", "S2", "B1", "B2", "C1", "C2")
        }
        assert indicators == pytest.approx(expected, abs=1e-8, rel=0)
    assert config == original

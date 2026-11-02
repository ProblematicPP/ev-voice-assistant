"""Real NASA cells are converted into the same 10 BMS features the SOH model uses."""
import pandas as pd
import pytest

from app.battery_core.ageing import SOH_FEATURES
from app.config import DATA_DIR

NASA = DATA_DIR / "nasa_cycles.csv"
pytestmark = pytest.mark.skipif(not NASA.exists(), reason="run python -m data_gen.nasa_battery to download")


def test_nasa_cycles_have_the_model_features():
    df = pd.read_csv(NASA)
    assert set(SOH_FEATURES) <= set(df.columns)
    assert df.cell_id.nunique() == 34 and df[SOH_FEATURES].notna().all().all()
    assert df.soh.between(0.25, 1.1).all()
    classic = df[df.cell_id == "B0005"].sort_values("cycle")
    assert classic.soh.iloc[:10].mean() > classic.soh.iloc[-10:].mean() + 0.15      # the cell visibly ages
    assert classic.internal_resistance_mohm.iloc[-10:].mean() > classic.internal_resistance_mohm.iloc[:10].mean()


def test_real_trained_model_beats_baselines_on_unseen_real_cells():
    from training import validate_soh_nasa as v
    from app.battery_core.nn import TabularRegressor
    df = pd.read_csv(NASA)
    classic = df[df.cell_id.isin(v.CLASSIC)]
    s, _ = v.evaluate(classic, [["B0007"]], TabularRegressor.load(v.MODEL_PATH))
    assert s["real"]["mae_pct_points"] < s["cycle_only"]["mae_pct_points"]
    assert s["real"]["mae_pct_points"] < s["mean"]["mae_pct_points"]

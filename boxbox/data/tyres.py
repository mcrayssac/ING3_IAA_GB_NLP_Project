"""Tyre degradation per compound, measured on a race's own clean laps.

Lap time = driver effect + lap effect + compound offset + b x tyre age. The lap
effects absorb fuel burn and track evolution without a fuel model, so b comes from
cars on different tyre ages on the same lap. Before the first stops every car has
the same age offset, so b only becomes estimable once some cars have pitted.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DRY = ("SOFT", "MEDIUM", "HARD")
MIN_LAPS, MIN_STINTS = 20, 2  # per compound, below this the slope is not reported
OUTLIER = 1.07  # laps slower than 107% of the median clean lap are traffic or errors
RELIABLE_SE = 0.03  # s per lap of age; a race's own slope is used below this


def clean_dry_laps(table: pd.DataFrame) -> pd.DataFrame:
    """Green, dry, timed laps with a known tyre age, without pit laps or lap 1."""
    keep = (
        (table["lap"] > 1)
        & ~table["pit_in"]
        & ~table["pit_out"]
        & ~table["neutralised_in_lap"]
        & table["compound"].isin(DRY)
        & table["lap_seconds"].notna()
        & table["tyre_age_end"].notna()
    )
    laps = table[keep]
    return laps[laps["lap_seconds"] <= OUTLIER * laps["lap_seconds"].median()]


def _design(laps: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    """Driver dummies, lap dummies (first dropped), compound offsets, slopes."""
    columns, names = [], []
    for driver in sorted(laps["driver_number"].unique()):
        columns.append(laps["driver_number"] == driver)
        names.append(f"driver {driver}")
    for lap in sorted(laps["lap"].unique())[1:]:
        columns.append(laps["lap"] == lap)
        names.append(f"lap {lap}")
    compounds = [c for c in DRY if (laps["compound"] == c).any()]
    for compound in compounds[1:]:
        columns.append(laps["compound"] == compound)
        names.append(f"offset {compound}")
    for compound in compounds:
        columns.append((laps["compound"] == compound) * laps["tyre_age_end"])
        names.append(compound)
    return np.column_stack([np.asarray(c, dtype=float) for c in columns]), names


def _ols(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Coefficients, standard errors and an estimability mask for each column."""
    rank = np.linalg.matrix_rank(x)
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    residual = y - x @ beta
    dof = len(y) - rank
    variance = residual @ residual / dof if dof > 0 else np.nan
    inverse = np.linalg.pinv(x.T @ x)
    projection = inverse @ (x.T @ x)
    # a column is estimable when its unit vector lies in the row space of x
    estimable = np.isclose(np.diag(projection), 1) & np.isclose(
        np.abs(projection).sum(axis=0), 1
    )
    return beta, np.sqrt(variance * np.diag(inverse)), estimable


def degradation(laps: pd.DataFrame) -> dict[str, dict[str, float]]:
    """Slope b (s per lap of age) and its standard error for each dry compound."""
    if laps["driver_number"].nunique() < 2:
        return {}
    x, names = _design(laps)
    beta, se, estimable = _ols(x, laps["lap_seconds"].to_numpy(float))
    # tyre age minus lap number stays constant within a stint
    stint = (
        laps["driver_number"] + "/" + (laps["tyre_age_end"] - laps["lap"]).astype(str)
    )
    out = {}
    for compound in DRY:
        mine = laps["compound"] == compound
        if compound not in names or mine.sum() < MIN_LAPS:
            continue
        if stint[mine].nunique() < MIN_STINTS:
            continue
        i = names.index(compound)
        if estimable[i]:
            out[compound] = {
                "b": float(beta[i]),
                "se": float(se[i]),
                "laps": int(mine.sum()),
            }
    return out

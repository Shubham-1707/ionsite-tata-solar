"""
Tata Solar (TPSL Gangaikondan) — RO Stage 1 Diagnostic Engine
=============================================================

Per the call with Baskar Mohan (12 May 2026):

  • Scope:     RO Stage 1 only (RO 1A, 1B, 1C — three parallel trains, each
               with its own dedicated HP-pump energy meter).
  • Period:    February → April 2026.  January is excluded because there is
               no energy data for January.
  • Feb file:  its internal "Month" cell is wrongly stamped 2026-01-01 but
               the data is February.  We auto-override based on filename.
  • Baseline:  empirical (mean of first 7 days per train), NOT OEM design.
               Baskar will replace these numbers when he hands over the
               site-specific baselines; the override block is at the bottom.
  • CIP:       same thresholds as the rest of IONSiTE:
                  NPF ≤ −10 %  | NSP ≥ 15 %  | DP ≥ 15 %  | Feed ≥ 10 %
               Drift % is measured against the EMPIRICAL BASELINE, not
               day-over-day (Baskar's correction).
  • Energy:    daily kWh = today − yesterday on cumulative HP-pump meter.
               SEC = daily kWh / (NPF × operating-hours).

The build_all() entry point loads every Excel in the dropbox folder, stitches
them, applies the Feb override, computes baselines, returns one long DataFrame.
"""
from __future__ import annotations
import re
from pathlib import Path
from typing import Iterable
import numpy as np
import pandas as pd

SHEET           = "RO Stage 1"
DATA_START_ROW  = 7                          # rows 0..6 are headers/units
TRAIN_OFFSETS   = {"RO A": 1, "RO B": 17, "RO C": 33}
RELATIVE_COLS   = {
    "mcf_inlet_p":  0, "mcf_outlet_p": 1, "mcf_dp":       2,
    "ph":           3, "orp":          4,
    "feed_p":       5, "hp_pump_p":    6, "reject_p":     7, "dp":           8,
    "feed_flow":    9, "perm_flow":   10, "reject_flow": 11, "recovery":    12,
    "feed_cond":   13, "perm_cond":   14, "reject_cond": 15,
}

CIP_THRESH = {
    "Due":               dict(npf=-5,  nsp=10, dp=10, feed=10),
    "Cleaning Required": dict(npf=-10, nsp=15, dp=15, feed=10),
    "Critical":          dict(npf=-15, nsp=25, dp=20, feed=20),
}
SEV_ORDER = ["", "Due", "Cleaning Required", "Critical"]
SEV_COLOR = {
    "":                  "#E0F2F1",
    "Due":               "#FFD54F",
    "Cleaning Required": "#FB8C00",
    "Critical":          "#C62828",
}

# ---------------------------------------------------------------------
# Per-train empirical baselines.
# Computed as mean of the first 7 days of available data — placeholder
# until Baskar gives the site-specific numbers.  When he does, set
# OVERRIDE_BASELINES = True and fill the dictionary below.
# ---------------------------------------------------------------------
OVERRIDE_BASELINES = False
BASELINES_OVERRIDE = {
    # "RO A": {"NPF": 21.0, "NSP": 1.4, "DP": 1.9, "FEED": 2.4},
    # "RO B": {"NPF": 20.7, "NSP": 1.3, "DP": 1.9, "FEED": 2.4},
    # "RO C": {"NPF": 20.8, "NSP": 1.4, "DP": 2.0, "FEED": 2.4},
}


# ---------------------------------------------------------------------
# Filename → month override
# ---------------------------------------------------------------------
_MONTH_TOKENS = {
    "JANUARY":  1, "JAN": 1,
    "FEBRUARY": 2, "FEB": 2,
    "MARCH":    3, "MAR": 3,
    "APRIL":    4, "APR": 4,
    "MAY":      5,
    "JUNE":     6, "JUN": 6,
    "JULY":     7, "JUL": 7,
    "AUGUST":   8, "AUG": 8,
    "SEPTEMBER":9, "SEP": 9, "SEPT": 9,
    "OCTOBER": 10, "OCT": 10,
    "NOVEMBER":11, "NOV": 11,
    "DECEMBER":12, "DEC": 12,
}

def _month_from_filename(fname: str) -> int | None:
    """Look for a month token in the filename. Returns None if not found."""
    up = fname.upper()
    for tok, m in _MONTH_TOKENS.items():
        if re.search(rf"\b{tok}\b", up):
            return m
    return None


# ---------------------------------------------------------------------
# Single-Excel parser
# ---------------------------------------------------------------------
def _parse_one(xlsx_path: str | Path) -> pd.DataFrame:
    """Parse one UPW Plant Daily Report Excel into long-format rows."""
    path = Path(xlsx_path)
    raw = pd.read_excel(path, sheet_name=SHEET, header=None)
    if raw.empty or len(raw) <= DATA_START_ROW:
        return pd.DataFrame()

    df = raw.iloc[DATA_START_ROW:].reset_index(drop=True)
    dates = pd.to_datetime(df.iloc[:, 0], errors="coerce")

    # Determine the canonical month for this file
    filename_month = _month_from_filename(path.name)
    # Internal "Month" tag from row 2 col 1
    try:
        internal_month_val = pd.to_datetime(raw.iloc[2, 1], errors="coerce")
        internal_month = internal_month_val.month if pd.notna(internal_month_val) else None
    except Exception:
        internal_month = None

    # Override: if filename says one month but the dates inside say another,
    # trust the filename (per Baskar's Feb-mislabelled-as-Jan correction)
    target_month = filename_month or internal_month
    if target_month is not None:
        # Build new timestamps that keep day-of-month but force the month/year
        ts = []
        for d in dates:
            if pd.isna(d):
                ts.append(pd.NaT)
                continue
            try:
                ts.append(pd.Timestamp(year=d.year if filename_month is None else 2026,
                                       month=target_month, day=d.day))
            except (ValueError, OverflowError):
                ts.append(pd.NaT)
        dates = pd.Series(ts)

    frames = []
    for train, base in TRAIN_OFFSETS.items():
        cols = {"Timestamp": dates, "Train": train}
        for name, rel in RELATIVE_COLS.items():
            ci = base + rel
            cols[name] = (pd.to_numeric(df.iloc[:, ci], errors="coerce")
                          if ci < df.shape[1] else np.nan)
        sub = pd.DataFrame(cols).dropna(subset=["Timestamp"])
        # Drop "AVERAGE" / summary rows whose date can't be parsed sensibly
        # (already handled by dropna above)
        frames.append(sub)
    out = pd.concat(frames, ignore_index=True)
    out["_source"] = path.name
    return out


# ---------------------------------------------------------------------
# Discover & load all monthly Excels in a folder
# ---------------------------------------------------------------------
def load_raw(xlsx_paths: str | Path | Iterable[str | Path]) -> pd.DataFrame:
    """Accepts a single path or iterable.  If a directory is passed, all
    *.xls / *.xlsx files in it are loaded."""
    if isinstance(xlsx_paths, (str, Path)):
        p = Path(xlsx_paths)
        if p.is_dir():
            files = sorted(list(p.glob("*.xls")) + list(p.glob("*.xlsx")))
        else:
            files = [p]
    else:
        files = [Path(x) for x in xlsx_paths]

    if not files:
        return pd.DataFrame()

    frames = []
    for f in files:
        try:
            frames.append(_parse_one(f))
        except Exception as e:
            print(f"[tata_solar_engine] WARN: failed to parse {f.name}: {e}")
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    # Dedupe (in case Feb is loaded both from explicit path and folder)
    out = out.drop_duplicates(subset=["Timestamp", "Train"]).sort_values(["Train", "Timestamp"])
    return out.reset_index(drop=True)


# ---------------------------------------------------------------------
# Derived KPIs
# ---------------------------------------------------------------------
def derive_kpis(raw: pd.DataFrame) -> pd.DataFrame:
    g = raw.copy()
    g["NPF"]       = g["perm_flow"]
    g["FEED"]      = g["feed_p"]
    g["DP"]        = g["dp"]
    g["FeedPress"] = g["feed_p"]
    g["NSP"]       = np.where((g["feed_cond"] > 0),
                              g["perm_cond"] / g["feed_cond"] * 100.0,
                              np.nan)
    g["SaltRej"]  = 100.0 - g["NSP"]
    g["Recovery"] = g["recovery"]
    return g


# ---------------------------------------------------------------------
# Empirical baseline — mean of FIRST DAY per train.
# Matches the behaviour of first_solar_engine.py and tata_steel_engine.py
# (where "first day" is ~12 samples of 2-hourly data; here it's 1 sample
# of daily data — same window, same definition, just lower sample count).
# Will be overridden by Baskar's site-specific numbers when available.
# ---------------------------------------------------------------------
def compute_baselines(g: pd.DataFrame) -> dict:
    """Returns {train: {NPF: float, NSP: float, DP: float, FEED: float}}.
    Override with BASELINES_OVERRIDE when Baskar provides site numbers."""
    if OVERRIDE_BASELINES and BASELINES_OVERRIDE:
        return BASELINES_OVERRIDE
    out = {}
    for train, sub in g.groupby("Train"):
        sub = sub.sort_values("Timestamp")
        baseline_day = sub["Timestamp"].dt.date.min()
        mask = sub["Timestamp"].dt.date == baseline_day
        out[train] = {
            "NPF":  float(sub.loc[mask, "NPF"].mean()),
            "NSP":  float(sub.loc[mask, "NSP"].mean()),
            "DP":   float(sub.loc[mask, "DP"].mean()),
            "FEED": float(sub.loc[mask, "FEED"].mean()),
        }
    return out


# ---------------------------------------------------------------------
# Drift % vs empirical baseline + day-over-day pct_change
# ---------------------------------------------------------------------
def add_baseline_drift(g: pd.DataFrame, baselines: dict) -> pd.DataFrame:
    """Adds NPF_drift, NSP_drift, DP_drift, FEED_drift columns: signed % of
    each KPI vs its train's empirical baseline.  These drive CIP severity."""
    g = g.copy()
    for c in ["NPF", "NSP", "DP", "FEED"]:
        g[c + "_drift"] = np.nan
    for train, b in baselines.items():
        m = g["Train"] == train
        for c in ["NPF", "NSP", "DP", "FEED"]:
            base = b.get(c)
            if base and not pd.isna(base) and base != 0:
                g.loc[m, c + "_drift"] = (g.loc[m, c] - base) / abs(base) * 100.0
    return g


def add_pct_change(g: pd.DataFrame) -> pd.DataFrame:
    """Day-over-day pct change per train (used in the Fouling Indicators tab)."""
    g = g.sort_values(["Train", "Timestamp"]).copy()
    for c in ["NPF", "NSP", "DP", "FEED"]:
        g[c + "_pct"] = g.groupby("Train")[c].pct_change(fill_method=None) * 100.0
    return g


# ---------------------------------------------------------------------
# CIP recommendation (against EMPIRICAL BASELINE drift)
# ---------------------------------------------------------------------
def cip_required_only(npf_drift, nsp_drift, dp_drift, feed_drift):
    if any(pd.isnull(x) for x in (npf_drift, nsp_drift, dp_drift, feed_drift)):
        return None
    if npf_drift <= -10 or nsp_drift >= 15 or dp_drift >= 15 or feed_drift >= 10:
        return "CIP Required"
    return None


def classify_cip(npf_drift, nsp_drift, dp_drift, feed_drift) -> str:
    if any(pd.isnull(x) for x in (npf_drift, nsp_drift, dp_drift, feed_drift)):
        return ""
    for sev in ("Critical", "Cleaning Required", "Due"):
        t = CIP_THRESH[sev]
        if (npf_drift <= t["npf"] or nsp_drift >= t["nsp"]
                or dp_drift >= t["dp"]   or feed_drift >= t["feed"]):
            return sev
    return ""


# ---------------------------------------------------------------------
# Energy
# ---------------------------------------------------------------------
TRAIN_TO_ENERGY = {"RO A": "RO_A_kWh_cum", "RO B": "RO_B_kWh_cum", "RO C": "RO_C_kWh_cum"}


def load_energy(csv_path: str | Path) -> pd.DataFrame:
    if not Path(csv_path).exists():
        return pd.DataFrame(columns=["Timestamp", "Train", "Energy_kWh", "Energy_cum_kWh"])
    e = pd.read_csv(csv_path, parse_dates=["Date"], comment="#")
    e = e.rename(columns={"Date": "Timestamp"}).sort_values("Timestamp")
    out = []
    for train, col in TRAIN_TO_ENERGY.items():
        if col not in e.columns:
            continue
        sub = e[["Timestamp", col]].dropna(subset=[col]).copy()
        sub["Energy_cum_kWh"] = sub[col]
        sub["Energy_kWh"]     = sub[col].diff()
        sub["Train"]          = train
        out.append(sub[["Timestamp", "Train", "Energy_kWh", "Energy_cum_kWh"]])
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def add_energy(g: pd.DataFrame, energy: pd.DataFrame, op_hours_per_day: float = 24.0) -> pd.DataFrame:
    if energy.empty:
        for c in ("Energy_kWh", "Energy_cum_kWh", "SEC_kWh_per_m3"):
            g[c] = np.nan
        return g
    g = g.copy(); energy = energy.copy()
    g["_d"]      = pd.to_datetime(g["Timestamp"]).dt.normalize()
    energy["_d"] = pd.to_datetime(energy["Timestamp"]).dt.normalize()
    energy = energy.drop(columns=["Timestamp"])
    g = g.merge(energy, on=["_d", "Train"], how="left").drop(columns=["_d"])
    with np.errstate(divide="ignore", invalid="ignore"):
        g["SEC_kWh_per_m3"] = g["Energy_kWh"] / (g["NPF"] * op_hours_per_day)
    return g


# ---------------------------------------------------------------------
# Build all  (single entry point used by the Streamlit page)
# ---------------------------------------------------------------------
def build_all(xlsx_paths: str | Path | Iterable[str | Path],
              energy_csv: str | Path | None = None,
              op_hours_per_day: float = 24.0) -> tuple[pd.DataFrame, dict]:
    """Returns (df, baselines).  df has every KPI/drift/CIP column the page needs."""
    raw = load_raw(xlsx_paths)
    if raw.empty:
        return raw, {}

    g = derive_kpis(raw)
    baselines = compute_baselines(g)
    g = add_baseline_drift(g, baselines)
    g = add_pct_change(g)

    energy = load_energy(energy_csv) if energy_csv else pd.DataFrame()
    g = add_energy(g, energy, op_hours_per_day)

    g["CIP_Recommendation"] = [
        cip_required_only(r.NPF_drift, r.NSP_drift, r.DP_drift, r.FEED_drift)
        for r in g.itertuples()
    ]
    g["CIP_Severity"] = [
        classify_cip(r.NPF_drift, r.NSP_drift, r.DP_drift, r.FEED_drift)
        for r in g.itertuples()
    ]
    return g, baselines

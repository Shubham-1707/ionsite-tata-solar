"""
Tata Solar (TPSL Gangaikondan) — RO Stage 1 Diagnostic Engine
=============================================================

Mirrors the public interface of first_solar_engine.py / tata_steel_engine.py
so the Streamlit page can reuse the same 7-tab layout verbatim.

  • Frequency:        DAILY  (one row per day per train — UPW Daily Report format)
  • Trains:           RO A, RO B, RO C  (three parallel trains; row-15/16/17 HP-pump meters)
  • Scope:            RO Stage 1 only  (per Baskar Mohan 12-May-26 call)
  • Months:           Feb-2026 to Apr-2026 (Jan excluded — no energy data)
  • Baseline:         mean of FIRST DAY per train (same definition as FS / TS engines)
  • CIP thresholds:   identical to FS / TS  (Due / Cleaning Required / Critical)
  • Diagnosis:        12-category fouling decision tree (same as FS / TS)
  • Health score:     same composite formula (penalties on each KPI's deviation)
  • OEE:              Availability × Performance × Quality
  • Forecast:         linear regression of *_pct over the window, days-to-threshold

Tata-Solar-specific extras (don't break the FS interface):
  • Two "stages" surfaced as DP_Stage_1 (MCF filter) and DP_Stage_2 (RO membrane).
    DP_Stage_3 is set to NaN so the existing 3-stage chart code degrades gracefully.
  • Energy module — daily kWh per HP pump + SEC kWh/m³ (loaded from energy_log.csv).
"""
from __future__ import annotations
import re
from pathlib import Path
from typing import Iterable
import numpy as np
import pandas as pd

# ======================================================================
# CONFIG
# ======================================================================
SHEET           = "RO Stage 1"
DATA_START_ROW  = 7
TRAIN_OFFSETS   = {"RO A": 1, "RO B": 17, "RO C": 33}
RELATIVE_COLS   = {
    "mcf_inlet_p":  0, "mcf_outlet_p": 1, "mcf_dp":       2,
    "ph":           3, "orp":          4,
    "feed_p":       5, "hp_pump_p":    6, "reject_p":     7, "dp":           8,
    "feed_flow":    9, "perm_flow":   10, "reject_flow": 11, "recovery":    12,
    "feed_cond":   13, "perm_cond":   14, "reject_cond": 15,
}

ROLL_WIN = 3            # 3-day rolling smooth for daily data
LATCH    = 2            # 2 consecutive days to confirm a severity

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

DIAGNOSIS_ORDER = [
    "Normal Operation",
    "Early Stage Fouling",
    "Early Scaling",
    "Particulate / Colloidal Fouling",
    "Inorganic Scaling",
    "Organic Fouling",
    "Biofouling",
    "Membrane Compaction",
    "Oxidation / Chlorine Attack",
    "O-Ring Leak / Internal Bypass",
    "Membrane Rupture",
    "Pretreatment Restriction",
]
DIAG_CODE  = {d: i for i, d in enumerate(DIAGNOSIS_ORDER)}
DIAG_COLOR = {
    "Normal Operation":                 "#2E7D32",
    "Early Stage Fouling":              "#FDD835",
    "Early Scaling":                    "#FBC02D",
    "Particulate / Colloidal Fouling":  "#FB8C00",
    "Inorganic Scaling":                "#EF6C00",
    "Organic Fouling":                  "#E65100",
    "Biofouling":                       "#8D6E63",
    "Membrane Compaction":              "#6D4C41",
    "Oxidation / Chlorine Attack":      "#C62828",
    "O-Ring Leak / Internal Bypass":    "#AD1457",
    "Membrane Rupture":                 "#6A1B9A",
    "Pretreatment Restriction":         "#1565C0",
}

# Actual CIP events shared by Tata Solar (placeholder — empty until site shares)
ACTUAL_CIP = {"RO A": [], "RO B": [], "RO C": []}

# Per-train baseline override block — populate when Baskar shares site values.
OVERRIDE_BASELINES = False
BASELINES_OVERRIDE = {
    # "RO A": {"NPF": 21.0, "NSP": 1.5, "DP": 1.9, "FEED": 2.4},
}


# ======================================================================
# Filename → month override (handles the Feb-mislabelled-as-Jan file)
# ======================================================================
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
    up = fname.upper()
    for tok, m in _MONTH_TOKENS.items():
        if re.search(rf"\b{tok}\b", up):
            return m
    return None


# ======================================================================
# DATA LOAD
# ======================================================================
def _parse_one(xlsx_path: str | Path) -> pd.DataFrame:
    """Parse one UPW Plant Daily Report Excel into long-format rows."""
    path = Path(xlsx_path)
    raw = pd.read_excel(path, sheet_name=SHEET, header=None)
    if raw.empty or len(raw) <= DATA_START_ROW:
        return pd.DataFrame()

    df = raw.iloc[DATA_START_ROW:].reset_index(drop=True)
    dates = pd.to_datetime(df.iloc[:, 0], errors="coerce")

    filename_month = _month_from_filename(path.name)
    try:
        internal_month_val = pd.to_datetime(raw.iloc[2, 1], errors="coerce")
        internal_month = internal_month_val.month if pd.notna(internal_month_val) else None
    except Exception:
        internal_month = None

    target_month = filename_month or internal_month
    if target_month is not None:
        ts = []
        for d in dates:
            if pd.isna(d):
                ts.append(pd.NaT); continue
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
        frames.append(sub)

    out = pd.concat(frames, ignore_index=True)
    out["_source"] = path.name
    return out


def load_raw(xlsx_paths: str | Path | Iterable[str | Path]) -> pd.DataFrame:
    """Accepts a single path, iterable, or a directory (all *.xls* in it)."""
    if isinstance(xlsx_paths, (str, Path)):
        p = Path(xlsx_paths)
        files = (sorted(list(p.glob("*.xls")) + list(p.glob("*.xlsx")))
                 if p.is_dir() else [p])
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
    out = (out.drop_duplicates(subset=["Timestamp", "Train"])
              .sort_values(["Train", "Timestamp"])
              .reset_index(drop=True))
    return out


# ======================================================================
# DERIVED KPIS  (use the same column names the FS / TS engines expose)
# ======================================================================
def derive_kpis(raw: pd.DataFrame) -> pd.DataFrame:
    g = raw.copy()
    g["NPF"]       = g["perm_flow"]            # permeate flow m3/hr
    g["FEED"]      = g["feed_p"]               # alias
    g["FeedPress"] = g["feed_p"]               # FS-compatible name
    g["DP"]        = g["dp"]                   # RO membrane DP
    g["PermFlow"]  = g["perm_flow"]            # FS-compatible alias
    g["NSP"]       = np.where((g["feed_cond"] > 0),
                              g["perm_cond"] / g["feed_cond"] * 100.0,
                              np.nan)
    g["SaltRej"]  = 100.0 - g["NSP"]
    g["Recovery"] = g["recovery"]

    # Tata-Solar treats MCF DP as "Stage 1" and the RO membrane DP as "Stage 2".
    # Stage 3 is left NaN — the FS page code degrades gracefully when a stage
    # has all-NaN values.
    g["DP_Stage_1"] = g["mcf_dp"]
    g["DP_Stage_2"] = g["dp"]
    g["DP_Stage_3"] = np.nan
    return g


# ======================================================================
# BASELINE + SMOOTHING + DRIFT
# ======================================================================
_SMOOTH_COLS = ["NPF", "NSP", "DP", "FEED", "FeedPress", "Recovery", "SaltRej",
                "DP_Stage_1", "DP_Stage_2", "DP_Stage_3"]


def compute_baselines(g: pd.DataFrame) -> dict:
    """Baseline = mean of FIRST DAY per train. Matches FS / TS methodology."""
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


def add_smoothed_and_pct(g: pd.DataFrame, baselines: dict, win: int = ROLL_WIN) -> pd.DataFrame:
    g = g.sort_values(["Train", "Timestamp"]).copy()
    # Smoothing
    for c in _SMOOTH_COLS:
        if c in g.columns:
            g[c + "_sm"] = g.groupby("Train")[c].transform(
                lambda s: s.rolling(win, min_periods=1).mean())

    # % vs baseline (smoothed)
    for c, key in [("NPF", "NPF"), ("NSP", "NSP"), ("DP", "DP"),
                   ("FEED", "FEED"), ("FeedPress", "FEED")]:
        smcol = c + "_sm"
        out_col = c + "_pct"
        g[out_col] = np.nan
        for train, b in baselines.items():
            base = b.get(key)
            if base and not pd.isna(base) and base != 0:
                m = g["Train"] == train
                g.loc[m, out_col] = (g.loc[m, smcol] - base) / abs(base) * 100.0

    # Feed_pct alias (used by FS exec table)
    g["Feed_pct"] = g["FeedPress_pct"]

    # Stage-DP % vs baseline (use first-day mean per train per stage)
    for stage in ["DP_Stage_1", "DP_Stage_2", "DP_Stage_3"]:
        sm = stage + "_sm"
        if sm not in g.columns:
            g[stage + "_pct"] = np.nan; continue
        g[stage + "_pct"] = np.nan
        for train, sub in g.groupby("Train"):
            sub = sub.sort_values("Timestamp")
            first_day = sub["Timestamp"].dt.date.min()
            base = sub.loc[sub["Timestamp"].dt.date == first_day, sm].mean()
            if pd.notna(base) and base != 0:
                m = g["Train"] == train
                g.loc[m, stage + "_pct"] = (g.loc[m, sm] - base) / abs(base) * 100.0

    return g


# ======================================================================
# CIP SEVERITY + LATCH
# ======================================================================
def classify_cip(npf, nsp, dp, feed) -> str:
    """3-tier severity — matches FS / TS engines exactly."""
    if any(pd.isnull(x) for x in (npf, nsp, dp, feed)):
        return ""
    for sev in ("Critical", "Cleaning Required", "Due"):
        t = CIP_THRESH[sev]
        if npf <= t["npf"] or nsp >= t["nsp"] or dp >= t["dp"] or feed >= t["feed"]:
            return sev
    return ""


def latch_sev(values, n: int = LATCH):
    out, run, last = [], 0, ""
    for v in values:
        if v == last and v:
            run += 1
        else:
            run, last = (1 if v else 0), v
        out.append(v if run >= n else "")
    return out


def cip_required_only(npf, nsp, dp, feed):
    if any(pd.isnull(x) for x in (npf, nsp, dp, feed)):
        return None
    if npf <= -10 or nsp >= 15 or dp >= 15 or feed >= 10:
        return "CIP Required"
    return None


# ======================================================================
# TREND CLASSIFICATION + DIAGNOSIS (12-category)
# ======================================================================
def _trend(series: pd.Series, window: int = ROLL_WIN,
           slight: float = 0.02, moderate: float = 0.05, sharp: float = 0.10) -> pd.Series:
    pct = (series - series.shift(window)) / series.shift(window).abs()
    pct = pct.replace([np.inf, -np.inf], np.nan)
    def _cls(x):
        if pd.isna(x):       return "STABLE"
        if x >=  sharp:      return "SHARP_UP"
        if x >=  moderate:   return "MODERATE_UP"
        if x >=  slight:     return "SLIGHT_UP"
        if x <= -sharp:      return "SHARP_DOWN"
        if x <= -moderate:   return "MODERATE_DOWN"
        if x <= -slight:     return "SLIGHT_DOWN"
        return "STABLE"
    return pct.apply(_cls)


def _latch_bool(series: pd.Series, count: int = LATCH) -> pd.Series:
    return (series.groupby((series != series.shift()).cumsum())
                  .transform("count") >= count)


def add_trends(g: pd.DataFrame) -> pd.DataFrame:
    g = g.copy()
    def sm(c):  return g[c + "_sm"] if c + "_sm" in g.columns else g[c]
    specs = [
        ("Flow_trend",  "NPF",        0.01, 0.03, 0.07),
        ("NSP_trend",   "NSP",        0.02, 0.05, 0.10),
        ("DP_trend",    "DP",         0.01, 0.03, 0.07),
        ("FP_trend",    "FeedPress",  0.01, 0.03, 0.07),
        ("DP1_trend",   "DP_Stage_1", 0.02, 0.05, 0.10),
        ("DP2_trend",   "DP_Stage_2", 0.02, 0.05, 0.10),
    ]
    for attr, col, sl, mo, sh in specs:
        if col in g.columns:
            g[attr] = g.groupby("Train")[sm(col).name if hasattr(sm(col), "name") else col].transform(
                lambda s: _trend(s, ROLL_WIN, sl, mo, sh))
        else:
            g[attr] = "STABLE"
        g[attr + "_latch"] = g.groupby("Train")[attr].transform(_latch_bool)

    g["DP3_trend"] = "STABLE"; g["DP3_trend_latch"] = False
    return g


def diagnose_row(row: pd.Series) -> str:
    latches = [row.get("NSP_trend_latch", False),
               row.get("Flow_trend_latch", False),
               row.get("DP_trend_latch",  False),
               row.get("FP_trend_latch",  False)]
    if sum(bool(x) for x in latches) < 2:
        return "Normal Operation"

    n, f   = row.get("NSP_trend","STABLE"),  row.get("Flow_trend","STABLE")
    d, p   = row.get("DP_trend","STABLE"),   row.get("FP_trend","STABLE")
    dp1    = row.get("DP1_trend","STABLE")
    last_dp= row.get("DP2_trend","STABLE")

    DOWN   = {"SLIGHT_DOWN","MODERATE_DOWN","SHARP_DOWN"}
    UP     = {"SLIGHT_UP","MODERATE_UP","SHARP_UP"}
    UP_MOD = {"MODERATE_UP","SHARP_UP"}
    FLAT   = {"STABLE","SLIGHT_UP","SLIGHT_DOWN"}
    FLAT_UP= {"STABLE","SLIGHT_UP","MODERATE_UP"}

    if n == "SHARP_UP" and f in ("SHARP_UP","SHARP_DOWN") and d in FLAT and p in FLAT:
        return "Membrane Rupture"
    if n == "SHARP_UP" and f in FLAT and d in FLAT and p in FLAT:
        return "Oxidation / Chlorine Attack"
    if f in UP and n in UP and d in FLAT and p in FLAT:
        return "O-Ring Leak / Internal Bypass"
    if f in DOWN and p == "SHARP_UP" and d in FLAT and n in FLAT:
        return "Pretreatment Restriction"
    if f in DOWN and n in UP and last_dp in UP_MOD and p in FLAT_UP:
        return "Early Scaling"
    if f in DOWN and n in FLAT and dp1 in UP_MOD and p in FLAT_UP:
        return "Early Stage Fouling"
    if f in DOWN and n in UP_MOD and d in UP and p in FLAT_UP:
        return "Inorganic Scaling"
    if f in DOWN and n == "SLIGHT_UP" and d in UP and p in UP:
        return "Organic Fouling"
    if f in DOWN and n in FLAT and d in UP_MOD and p in UP:
        return "Biofouling"
    if f in DOWN and n in FLAT and d in UP and p in UP:
        return "Particulate / Colloidal Fouling"
    if f in DOWN and n in FLAT and d in FLAT_UP and p in UP:
        return "Membrane Compaction"
    if d in UP_MOD and f not in DOWN:
        return "Early Scaling" if last_dp in UP_MOD else "Particulate / Colloidal Fouling"
    return "Normal Operation"


# ======================================================================
# HEALTH + OEE
# ======================================================================
def health_score(row: pd.Series) -> float:
    pen = 0.0
    pen += max(0, -(row.get("NPF_pct") or 0))      * 2.0
    pen += max(0,  (row.get("NSP_pct") or 0))      * 1.5
    pen += max(0,  (row.get("DP_pct")  or 0))      * 1.2
    pen += max(0,  (row.get("FeedPress_pct") or 0))* 1.0
    return float(max(0, min(100, 100 - pen)))


def oee(train_df: pd.DataFrame) -> dict:
    flow = train_df["NPF"]
    avail = float((flow.notna() & (flow > 0)).mean())
    bday  = train_df["Timestamp"].dt.date.min()
    smcol = "NPF_sm" if "NPF_sm" in train_df.columns else "NPF"
    base  = train_df.loc[train_df["Timestamp"].dt.date == bday, smcol].mean()
    cur   = train_df[smcol].mean()
    perf  = float(min(1.0, cur / base)) if base and not pd.isna(base) else np.nan
    # Quality: % rows with permeate conductivity within "acceptable" range
    # Use the perm_cond column (μs/cm or PPM). 500 is a reasonable common ceiling.
    pcond = train_df.get("perm_cond")
    qual  = float((pcond < 500).mean()) if pcond is not None and pcond.notna().any() else np.nan
    overall = (avail * perf * qual) if all(pd.notna(x) for x in (avail, perf, qual)) else np.nan
    return dict(availability=avail, performance=perf, quality=qual, oee=overall,
                base_npf=base, current_npf=cur)


# ======================================================================
# FORECAST
# ======================================================================
def _days_to_severity(sub: pd.DataFrame, severity: str) -> dict:
    th = CIP_THRESH[severity]
    t0 = sub["Timestamp"].iloc[0]
    x  = (sub["Timestamp"] - t0).dt.total_seconds() / 86400.0
    current, slopes, days = {}, {}, {}
    for kpi, col, target, sign in [
        ("NPF",  "NPF_pct",       th["npf"],  "down"),
        ("NSP",  "NSP_pct",       th["nsp"],  "up"),
        ("DP",   "DP_pct",        th["dp"],   "up"),
        ("Feed", "FeedPress_pct", th["feed"], "up"),
    ]:
        if col not in sub.columns: continue
        y = sub[col].values
        if np.all(np.isnan(y)) or len(y) < 4: continue
        m, b = np.polyfit(x[~np.isnan(y)], y[~np.isnan(y)], 1)
        current[kpi] = float(y[-1])
        slopes[kpi]  = float(m)
        last_x = float(x.iloc[-1])
        if sign == "down":
            days[kpi] = max(0.0, (target - b) / m - last_x) if m < 0 and y[-1] > target else (0.0 if y[-1] <= target else np.inf)
        else:
            days[kpi] = max(0.0, (target - b) / m - last_x) if m > 0 and y[-1] < target else (0.0 if y[-1] >= target else np.inf)
    return dict(current=current, slopes=slopes, days=days)


def forecast_days_to_cip(train_df: pd.DataFrame, severity: str = "Cleaning Required") -> dict:
    cols = ["NPF_pct","NSP_pct","DP_pct","FeedPress_pct"]
    sub  = train_df.dropna(subset=[c for c in cols if c in train_df.columns])
    if len(sub) < 4:
        return dict(days_to_cip=np.nan, limiting_kpi=None, current={}, slopes={},
                    severity=severity, already_breached=False)
    result = _days_to_severity(sub, severity)
    days   = result["days"]
    if not days:
        return dict(days_to_cip=np.nan, limiting_kpi=None,
                    current=result["current"], slopes=result["slopes"],
                    severity=severity, already_breached=False)
    lim = min(days, key=days.get)
    already_breached = days[lim] == 0.0
    if already_breached:
        nsi = SEV_ORDER.index(severity) + 1
        if nsi < len(SEV_ORDER) and SEV_ORDER[nsi]:
            esc = _days_to_severity(sub, SEV_ORDER[nsi])
            if esc["days"]:
                el = min(esc["days"], key=esc["days"].get)
                return dict(days_to_cip=esc["days"][el], limiting_kpi=el,
                            current=esc["current"], slopes=esc["slopes"],
                            severity=SEV_ORDER[nsi], already_breached=True,
                            all_days=esc["days"])
    return dict(days_to_cip=days[lim], limiting_kpi=lim,
                current=result["current"], slopes=result["slopes"],
                severity=severity, already_breached=already_breached, all_days=days)


# ======================================================================
# ENERGY
# ======================================================================
TRAIN_TO_ENERGY = {"RO A": "RO_A_kWh_cum", "RO B": "RO_B_kWh_cum", "RO C": "RO_C_kWh_cum"}


def load_energy(csv_path: str | Path) -> pd.DataFrame:
    if not Path(csv_path).exists():
        return pd.DataFrame(columns=["Timestamp", "Train", "Energy_kWh", "Energy_cum_kWh"])
    e = pd.read_csv(csv_path, parse_dates=["Date"], comment="#")
    e = e.rename(columns={"Date": "Timestamp"}).sort_values("Timestamp")
    out = []
    for train, col in TRAIN_TO_ENERGY.items():
        if col not in e.columns: continue
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


# ======================================================================
# BUILD ALL — single entry point used by the Streamlit page
# ======================================================================
def build_all(xlsx_paths: str | Path | Iterable[str | Path],
              energy_csv: str | Path | None = None,
              temp_c: float | None = None,            # unused, FS API parity
              roll_win: int = ROLL_WIN,
              op_hours_per_day: float = 24.0) -> pd.DataFrame:
    """
    Returns ONE DataFrame with every column the FS-style page expects.
    Matches first_solar_engine.build_all() shape so the page is copy-paste.
    """
    raw = load_raw(xlsx_paths)
    if raw.empty:
        return raw

    g = derive_kpis(raw)
    baselines = compute_baselines(g)
    g = add_smoothed_and_pct(g, baselines, roll_win)
    g = add_trends(g)
    g["Diagnosis"]      = g.apply(diagnose_row, axis=1)
    g["Diagnosis_code"] = g["Diagnosis"].map(DIAG_CODE)
    g["Health"]         = g.apply(health_score, axis=1)

    # CIP severity per-row + latched
    g["CIP_raw"] = [classify_cip(a, b, c, d) for a, b, c, d in
                    zip(g.get("NPF_pct", pd.Series(np.nan, index=g.index)),
                        g.get("NSP_pct", pd.Series(np.nan, index=g.index)),
                        g.get("DP_pct",  pd.Series(np.nan, index=g.index)),
                        g.get("FeedPress_pct", pd.Series(np.nan, index=g.index)))]
    # Latch per train
    g["CIP"] = ""
    for train, sub in g.groupby("Train"):
        idx = sub.index
        g.loc[idx, "CIP"] = latch_sev(sub["CIP_raw"].tolist())

    # Promote diagnosis if CIP says we should be cleaning but diagnosis is normal
    mismatch = (g["CIP"] != "") & (g["Diagnosis"] == "Normal Operation")
    g.loc[mismatch, "Diagnosis"] = "Early Stage Fouling"

    # Single-tier recommendation column (for the simple table view)
    g["CIP_Recommendation"] = [
        cip_required_only(r.NPF_pct, r.NSP_pct, r.DP_pct, r.FeedPress_pct)
        for r in g.itertuples()
    ]

    # Energy
    energy = load_energy(energy_csv) if energy_csv else pd.DataFrame()
    g = add_energy(g, energy, op_hours_per_day)

    # Expose baselines as an attribute for the page (st.cache doesn't survive
    # tuple unpacking nicely; using a hidden col so callers can read it)
    g.attrs["baselines"] = baselines
    return g

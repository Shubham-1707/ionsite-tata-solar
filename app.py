"""
IONSiTE OS — Tata Solar (TPSL Gangaikondan) RO Stage 1 Dashboard
=================================================================
Standalone Streamlit Cloud version.

Single-file app + engine, ships its own data. Deploys to Streamlit
Community Cloud in 2 minutes — push this folder to GitHub, point
share.streamlit.io at app.py, done.

Three months of operational data (Feb / Mar / Apr 2026) plus a
partial energy logbook are bundled in data/.  Sales engineers can
also upload their own data via the sidebar.
"""
from __future__ import annotations
import os
from pathlib import Path
from io import BytesIO

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import engine as eng


# =====================================================================
# Page config + theme
# =====================================================================
st.set_page_config(
    page_title="IONSiTE OS — Tata Solar Dashboard",
    layout="wide",
    initial_sidebar_state="expanded",
)
import plotly.io as pio
pio.templates["ion"] = go.layout.Template(
    layout=go.Layout(
        font=dict(family="Inter, Segoe UI, Arial", size=13, color="#111827"),
        colorway=["#0B2545", "#EF6C00", "#13315C", "#6A1B9A", "#2E7D32", "#C62828"],
        plot_bgcolor="white", paper_bgcolor="white",
        xaxis=dict(showgrid=False, showline=True, linecolor="#E4E9F2", ticks="outside",
                   tickcolor="#E4E9F2"),
        yaxis=dict(showgrid=True, gridcolor="#F1F3F5", showline=True, linecolor="#E4E9F2"),
        margin=dict(l=10, r=10, t=40, b=10), legend=dict(bgcolor="rgba(0,0,0,0)"),
    )
)
pio.templates.default = "ion"

st.markdown("""
<style>
.block-container {padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1380px;}
h1 {color: #0B2545; font-weight: 600; letter-spacing: -0.5px;}
h2, h3 {color: #13315C; font-weight: 600;}
.metric-card {background:#fff; padding:14px 18px; border-radius:4px;
              border:1px solid #E4E9F2; border-left:3px solid #0B2545;}
.metric-card .label {font-size:0.78rem; color:#6B7280; text-transform:uppercase; letter-spacing:0.5px;}
.metric-card .value {font-size:1.7rem; font-weight:600; color:#0B2545; margin-top:4px;}
.metric-card .sub   {font-size:0.78rem; color:#6B7280;}
.brand {font-size:0.8rem; color:#6B7280; letter-spacing:1px; text-transform:uppercase;}
hr {margin: 0.8rem 0; border-color:#E4E9F2;}
[data-testid="stSidebar"] {background:#F7F9FC;}
</style>
""", unsafe_allow_html=True)


# =====================================================================
# Data source — bundled folder OR uploads
# =====================================================================
DATA_DIR = Path(__file__).parent / "data"

st.sidebar.markdown(
    "<div style='padding:8px 0 12px 0;'>"
    "<div style='font-size:1.15rem; font-weight:600; color:#0B2545;'>Ion Exchange (India) Ltd.</div>"
    "<div style='font-size:0.8rem; color:#6B7280;'>IONSiTE OS</div>"
    "<div style='font-size:0.8rem; color:#6B7280;'>Client: TPSL — Gangaikondan</div>"
    "<div style='font-size:0.8rem; color:#6B7280;'>Scope: RO Stage 1 (3 trains)</div>"
    "</div>", unsafe_allow_html=True)
st.sidebar.markdown("---")

st.sidebar.markdown("#### Data source")
use_uploads = st.sidebar.toggle("Upload my own data", value=False,
    help="OFF = bundled Feb/Mar/Apr 2026 data. ON = upload your own UPW reports + energy log.")

excel_paths = []
energy_csv  = None

if use_uploads:
    ups = st.sidebar.file_uploader("UPW Plant Daily Reports (.xls / .xlsx)",
                                    type=["xls", "xlsx"], accept_multiple_files=True)
    elog = st.sidebar.file_uploader("Energy log (.csv)", type=["csv"])
    if ups:
        tmp_dir = Path("/tmp/ix_uploads")
        tmp_dir.mkdir(exist_ok=True)
        for u in ups:
            (tmp_dir / u.name).write_bytes(u.getbuffer())
            excel_paths.append(tmp_dir / u.name)
    if elog:
        ep = Path("/tmp/ix_uploads/energy_log.csv")
        ep.parent.mkdir(exist_ok=True)
        ep.write_bytes(elog.getbuffer())
        energy_csv = ep
else:
    excel_paths = sorted(list(DATA_DIR.glob("*.xls")) + list(DATA_DIR.glob("*.xlsx")))
    if (DATA_DIR / "energy_log.csv").exists():
        energy_csv = DATA_DIR / "energy_log.csv"

if not excel_paths:
    st.error("No operational Excel files available. Toggle uploads ON and add files."); st.stop()

st.sidebar.markdown(f"**Reports loaded:** {len(excel_paths)} file(s)")
with st.sidebar.expander("File list", expanded=False):
    for p in excel_paths:
        st.markdown(f"- {p.name}")
st.sidebar.markdown(f"**Energy logbook:** {'✅' if energy_csv else '⚠️ missing'}")

op_hours = st.sidebar.number_input("RO operating hours / day", 1.0, 24.0, 24.0, 1.0)
water_price  = st.sidebar.number_input("Water value (₹ / m³)", 0.0, 500.0, 50.0, 5.0)
energy_price = st.sidebar.number_input("Energy tariff (₹ / kWh)", 0.0, 30.0, 8.5, 0.5)


# =====================================================================
# Load
# =====================================================================
@st.cache_data(show_spinner=True)
def load(paths_tuple, energy_path, oh):
    return eng.build_all(list(paths_tuple), energy_path, op_hours_per_day=oh)

df, baselines = load(tuple(str(p) for p in excel_paths),
                     str(energy_csv) if energy_csv else None,
                     op_hours)

if df.empty:
    st.error("Could not parse RO Stage 1 sheet. Confirm file format."); st.stop()

trains_all = sorted(df["Train"].unique())
min_d, max_d = df["Timestamp"].min().date(), df["Timestamp"].max().date()
date_range = st.sidebar.date_input("Date range", value=(min_d, max_d),
                                   min_value=min_d, max_value=max_d)
if isinstance(date_range, tuple) and len(date_range) == 2:
    d0, d1 = date_range
    df = df[(df["Timestamp"].dt.date >= d0) & (df["Timestamp"].dt.date <= d1)].copy()

train_pick = st.sidebar.multiselect("RO trains", trains_all, default=trains_all)
df = df[df["Train"].isin(train_pick)].copy()


# =====================================================================
# Header
# =====================================================================
col_a, col_b = st.columns([4, 1])
with col_a:
    st.markdown("<div class='brand'>Ion Exchange (India) Ltd. &nbsp;·&nbsp; Tata Power Solar Ltd. — Gangaikondan</div>",
                unsafe_allow_html=True)
    st.title("RO Stage 1 — Performance Diagnostic Report")
    st.caption("Daily KPI tracking · drift vs empirical baseline · CIP decision support · "
               "Specific Energy Consumption (SEC) · linear extrapolation to next CIP.")
with col_b:
    st.markdown(
        f"<div style='text-align:right; padding-top:12px;'>"
        f"<div style='font-size:0.75rem; color:#6B7280; text-transform:uppercase; letter-spacing:0.5px;'>Reporting Window</div>"
        f"<div style='font-weight:600; color:#0B2545;'>{df['Timestamp'].min():%d %b %Y} — {df['Timestamp'].max():%d %b %Y}</div>"
        f"</div>", unsafe_allow_html=True)
st.markdown("---")


def kpi_card(col, label, value, sub=""):
    col.markdown(
        f"<div class='metric-card'><div class='label'>{label}</div>"
        f"<div class='value'>{value}</div><div class='sub'>{sub}</div></div>",
        unsafe_allow_html=True)


# =====================================================================
# Snapshot
# =====================================================================
st.subheader("System Health Snapshot")
snap_cols = st.columns(max(1, len(train_pick)))
for i, t in enumerate(train_pick):
    sub = df[df["Train"] == t]
    if sub.empty:
        kpi_card(snap_cols[i], t, "—"); continue
    cip_days = int((sub["CIP_Recommendation"] == "CIP Required").sum())
    npf_mean = sub["NPF"].mean(); nsp_mean = sub["NSP"].mean(); rec_mean = sub["Recovery"].mean()
    kpi_card(snap_cols[i], t, f"{cip_days} day(s) flagged",
             f"NPF avg {npf_mean:.1f} m³/h · NSP {nsp_mean:.2f}% · Recovery {rec_mean:.0f}%")

with st.expander("Empirical baselines (mean of first 7 days per train) — Baskar to replace with site-specific numbers", expanded=False):
    bl_df = pd.DataFrame(baselines).T.round(3)
    bl_df.index.name = "Train"
    st.dataframe(bl_df, use_container_width=True)
    st.caption("CIP severity is computed against these baselines: "
               "NPF ≤ −10 % · NSP ≥ 15 % · DP ≥ 15 % · Feed ≥ 10 %.")


# =====================================================================
# Tabs
# =====================================================================
tab_overview, tab_fouling, tab_diag, tab_cip, tab_energy, tab_forecast, tab_exec = st.tabs([
    "Overview", "Fouling Indicators", "Diagnosis",
    "CIP Decision", "Energy & SEC",
    "Forecast & Recovery", "Executive Summary",
])
TRAIN_COLOR = {"RO A": "#0B3D91", "RO B": "#EF6C00", "RO C": "#2E7D32"}


with tab_overview:
    st.markdown("### Daily KPI trends")
    for kpi, title in [
        ("NPF",  "Permeate flow (m³/hr)"),
        ("NSP",  "Salt passage — Perm/Feed × 100 (%)"),
        ("DP",   "Differential pressure (kg/cm²)"),
        ("FEED", "Feed pressure (kg/cm²)"),
    ]:
        fig = go.Figure()
        for t in train_pick:
            sub = df[df["Train"] == t]
            fig.add_trace(go.Scatter(x=sub["Timestamp"], y=sub[kpi],
                                     mode="lines+markers", name=t,
                                     line=dict(color=TRAIN_COLOR.get(t, "#888"), width=1.8),
                                     marker=dict(size=4)))
        # Plot baseline line per train as dashed
        for t in train_pick:
            b = baselines.get(t, {}).get(kpi)
            if b and not pd.isna(b):
                fig.add_hline(y=b, line_dash="dot", line_color=TRAIN_COLOR.get(t, "#888"),
                              line_width=1, opacity=0.6)
        fig.update_layout(height=260, title=title,
                          margin=dict(l=10, r=10, t=45, b=10),
                          legend=dict(orientation="h", y=1.12, x=0))
        st.plotly_chart(fig, use_container_width=True)


with tab_fouling:
    st.markdown("### Drift vs empirical baseline")
    st.caption("% deviation from each train's own baseline. CIP triggers when threshold crossed.")
    for kpi, title, thr in [
        ("NPF",  "NPF drift % (drop = fouling)",   -10),
        ("NSP",  "NSP drift % (rise = scaling)",   +15),
        ("DP",   "DP drift % (rise = bed fouling)", +15),
        ("FEED", "Feed drift % (rise = restriction)", +10),
    ]:
        col = kpi + "_drift"
        fig = go.Figure()
        for t in train_pick:
            sub = df[df["Train"] == t]
            fig.add_trace(go.Scatter(x=sub["Timestamp"], y=sub[col],
                                     mode="lines+markers", name=t,
                                     line=dict(color=TRAIN_COLOR.get(t, "#888"), width=1.8)))
        fig.add_hline(y=thr, line_dash="dash", line_color="#C62828",
                      annotation_text=f"CIP threshold {thr:+}%", annotation_position="bottom right")
        fig.add_hline(y=0, line_dash="dot", line_color="#9CA3AF", line_width=1)
        fig.update_layout(height=260, title=title,
                          margin=dict(l=10, r=10, t=45, b=10),
                          legend=dict(orientation="h", y=1.12, x=0))
        st.plotly_chart(fig, use_container_width=True)


with tab_diag:
    st.markdown("### Diagnostic table")
    st.caption("Drift % is vs empirical baseline. CIP_Severity = Critical / Cleaning Required / Due / blank.")
    cols = ["Timestamp", "Train", "NPF", "NSP", "DP", "FEED",
            "NPF_drift", "NSP_drift", "DP_drift", "FEED_drift",
            "Recovery", "CIP_Recommendation", "CIP_Severity"]
    cols = [c for c in cols if c in df.columns]
    view = df[cols].copy()
    view["Timestamp"] = pd.to_datetime(view["Timestamp"]).dt.strftime("%d %b %Y")
    view = view.rename(columns={
        "NPF_drift": "NPF Δ%", "NSP_drift": "NSP Δ%",
        "DP_drift":  "DP Δ%",  "FEED_drift": "Feed Δ%"})
    fmt = {c: "{:.2f}" for c in ("NPF", "NSP", "DP", "FEED", "Recovery")}
    fmt.update({c: "{:+.1f}" for c in ("NPF Δ%", "NSP Δ%", "DP Δ%", "Feed Δ%")})
    st.dataframe(view.style.format(fmt, na_rep="—"),
                 use_container_width=True, height=480, hide_index=True)


with tab_cip:
    st.markdown("### CIP recommendation calendar")
    full_range = pd.DataFrame({
        "Date": pd.date_range(start=df["Timestamp"].min().normalize(),
                              end=df["Timestamp"].max().normalize())})
    for t in train_pick:
        st.markdown(f"---\n#### {t}")
        sub = df[df["Train"] == t].copy()
        if sub.empty: st.info("no data"); continue
        sub["Date"] = pd.to_datetime(sub["Timestamp"]).dt.normalize()
        cal = full_range.merge(
            sub[["Date", "NPF_drift", "NSP_drift", "DP_drift", "FEED_drift",
                 "CIP_Recommendation"]], on="Date", how="left"
        ).rename(columns={"NPF_drift": "NPF Δ%", "NSP_drift": "NSP Δ%",
                          "DP_drift":  "DP Δ%",  "FEED_drift": "Feed Δ%",
                          "CIP_Recommendation": "Recommended"})
        cal["Recommended"] = cal["Recommended"].fillna("")
        cal["Date"] = cal["Date"].dt.strftime("%d %b %Y")

        def _row_style(r):
            base = [""] * len(r)
            if r.get("Recommended") == "CIP Required":
                base = ["background-color:#FFF3E0; color:#E65100"] * len(r)
            return base

        st.dataframe(
            cal.style.apply(_row_style, axis=1)
                     .format({c: "{:+.1f}" for c in ("NPF Δ%", "NSP Δ%", "DP Δ%", "Feed Δ%")},
                             na_rep="—"),
            use_container_width=True, hide_index=True,
            height=min(560, 36 * (len(cal) + 2)))


with tab_energy:
    st.markdown("### Energy & Specific Energy Consumption (SEC)")
    if not energy_csv:
        st.warning("Energy log not loaded. Toggle uploads or add `energy_log.csv` to /data.")
    else:
        st.caption(f"Daily kWh derived from cumulative HP-pump meter readings · "
                   f"SEC = kWh / (NPF × {op_hours:.0f} h)")
        e_cols = st.columns(len(train_pick) or 1)
        for i, t in enumerate(train_pick):
            sub = df[df["Train"] == t]
            kwh_total = sub["Energy_kWh"].sum(skipna=True)
            sec_mean  = sub["SEC_kWh_per_m3"].mean(skipna=True)
            cost = kwh_total * energy_price
            sub_txt = (f"avg SEC {sec_mean:.2f} kWh/m³" if pd.notna(sec_mean) else "no overlap")
            kpi_card(e_cols[i], f"{t}", f"{kwh_total:,.0f} kWh · ₹{cost:,.0f}", sub_txt)

        for title, ycol in [("Daily kWh (HP pumps)", "Energy_kWh"),
                            ("Specific Energy Consumption (kWh / m³)", "SEC_kWh_per_m3")]:
            fig = go.Figure()
            for t in train_pick:
                sub = df[df["Train"] == t]
                fig.add_trace(go.Scatter(x=sub["Timestamp"], y=sub[ycol],
                                         mode="lines+markers", name=t,
                                         line=dict(color=TRAIN_COLOR.get(t, "#888"), width=2)))
            fig.update_layout(height=280, title=title,
                              margin=dict(l=10, r=10, t=45, b=10),
                              legend=dict(orientation="h", y=1.12, x=0))
            st.plotly_chart(fig, use_container_width=True)


with tab_forecast:
    st.markdown("### Recovery & flow consistency")
    fig = go.Figure()
    for t in train_pick:
        sub = df[df["Train"] == t]
        fig.add_trace(go.Scatter(x=sub["Timestamp"], y=sub["Recovery"],
                                 mode="lines+markers", name=t,
                                 line=dict(color=TRAIN_COLOR.get(t, "#888"), width=1.8)))
    fig.update_layout(height=280, title="Recovery % per day",
                      margin=dict(l=10, r=10, t=45, b=10),
                      legend=dict(orientation="h", y=1.12, x=0))
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("### Linear extrapolation to next CIP")
    st.caption("Slope from `y = m·x + c` fitted to NPF drift % over the visible window.")
    rows = []
    for t in train_pick:
        sub = df[df["Train"] == t].dropna(subset=["NPF_drift"])
        if len(sub) < 4:
            rows.append(dict(Train=t, slope="—", current="—", days_to_CIP="—")); continue
        x = (sub["Timestamp"] - sub["Timestamp"].iloc[0]).dt.total_seconds().values / 86400.0
        y = sub["NPF_drift"].values
        ok = ~np.isnan(y)
        if ok.sum() < 4:
            rows.append(dict(Train=t, slope="—", current="—", days_to_CIP="—")); continue
        m, b = np.polyfit(x[ok], y[ok], 1)
        last_x = float(x[-1])
        days_left = (-10 - b) / m - last_x if m < 0 else float("inf")
        rows.append(dict(
            Train=t, slope=f"{m:+.2f}%/day", current=f"{y[ok][-1]:+.1f}%",
            days_to_CIP=("already breached" if days_left <= 0 else
                         "no projected" if days_left == float("inf") else
                         f"{days_left:.0f} days")))
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


with tab_exec:
    st.markdown("### Executive Summary — Tata Solar Gangaikondan RO Stage 1")
    bullets = []
    for t in train_pick:
        sub = df[df["Train"] == t]
        if sub.empty: continue
        cip_days  = int((sub["CIP_Recommendation"] == "CIP Required").sum())
        sec_mean  = sub["SEC_kWh_per_m3"].mean(skipna=True)
        kwh_total = sub["Energy_kWh"].sum(skipna=True)
        rec_mean  = sub["Recovery"].mean(skipna=True)
        bullets.append(
            f"- **{t}** &nbsp; CIP flagged on **{cip_days} day(s)** · "
            f"avg recovery **{rec_mean:.1f}%** · "
            f"period energy **{kwh_total:,.0f} kWh** "
            f"(₹{kwh_total*energy_price:,.0f} at ₹{energy_price:.1f}/kWh) · "
            f"avg SEC **{sec_mean:.2f} kWh/m³**")
    st.markdown("\n".join(bullets) if bullets else "_no data_")

    st.markdown("### Methodology notes")
    st.markdown(
        "- Baselines are **empirical** (mean of first 7 days per train), not OEM design values.\n"
        "- Drift % per KPI is measured against that empirical baseline.\n"
        "- CIP rule: any of  NPF ≤ −10 % · NSP ≥ 15 % · DP ≥ 15 % · Feed ≥ 10 %.\n"
        "- Days-to-CIP is a linear regression of NPF drift over the reporting window.\n"
        "- When Baskar shares the site-specific baselines, the engine's "
        "`OVERRIDE_BASELINES` block is toggled to use those numbers.")

    out = df.copy()
    out["Timestamp"] = pd.to_datetime(out["Timestamp"]).dt.strftime("%Y-%m-%d")
    st.download_button("Download KPI table (CSV)",
                       out.to_csv(index=False).encode("utf-8"),
                       file_name="tata_solar_ro_stage1_kpi.csv", mime="text/csv")

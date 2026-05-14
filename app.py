"""
Tata Solar (TPSL Gangaikondan) — RO Stage 1 Diagnostic Dashboard
==================================================================
Mirrors the 7-tab layout of 2_First_Solar.py exactly. Differences:

  • 3 trains (RO A / B / C) instead of 2
  • Daily data instead of 2-hourly
  • "Stage Analysis" shows MCF DP (Stage 1) and Membrane DP (Stage 2)
  • Forecast & OEE tab adds an Energy & SEC sub-section at the end
"""
from __future__ import annotations
from datetime import timedelta
import sys, os

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import streamlit as st

import engine as eng
import importlib; importlib.reload(eng)

from pathlib import Path
DATA_DIR = str(Path(__file__).parent / "data")

# Plotly theme
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

st.set_page_config(
    page_title="Tata Solar – RO Stage 1 Diagnostic",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
.block-container {padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1380px;}
h1 {color: #0B2545; font-weight: 600; letter-spacing: -0.5px;}
h2, h3 {color: #13315C; font-weight: 600;}
.metric-card {
    background: #ffffff;
    padding: 14px 18px; border-radius: 4px;
    border: 1px solid #E4E9F2; border-left: 3px solid #0B2545;
}
.metric-card .label {font-size:0.78rem; color:#6B7280; text-transform:uppercase; letter-spacing:0.5px;}
.metric-card .value {font-size:1.7rem; font-weight:600; color:#0B2545; margin-top:4px;}
.metric-card .sub   {font-size:0.78rem; color:#6B7280;}
.badge {padding: 3px 10px; border-radius: 3px; color:white; font-weight:500; font-size:0.78rem; letter-spacing:0.3px;}
.brand {font-size:0.8rem; color:#6B7280; letter-spacing:1px; text-transform:uppercase;}
.footer {margin-top: 2rem; color:#9CA3AF; font-size:0.75rem; text-align:center; border-top:1px solid #E4E9F2; padding-top:1rem;}
hr {margin: 0.8rem 0; border-color:#E4E9F2;}
[data-testid="stSidebar"] {background: #F7F9FC;}
</style>
""", unsafe_allow_html=True)


# ======================================================================
# DATA CACHE
# ======================================================================
@st.cache_data(show_spinner=True)
def load_data(folder: str, energy_path: str | None, roll_win: int, op_hours: float) -> pd.DataFrame:
    return eng.build_all(folder, energy_path, roll_win=roll_win, op_hours_per_day=op_hours)


# ======================================================================
# SIDEBAR
# ======================================================================
st.sidebar.markdown(
    "<div style='padding:8px 0 12px 0;'>"
    "<div style='font-size:1.15rem; font-weight:600; color:#0B2545;'>Ion Exchange (India) Ltd.</div>"
    "<div style='font-size:0.8rem; color:#6B7280;'>RO Performance Diagnostic Report</div>"
    "<div style='font-size:0.8rem; color:#6B7280;'>Client: Tata Power Solar — Gangaikondan</div>"
    "</div>", unsafe_allow_html=True)
st.sidebar.markdown("---")

os.makedirs(DATA_DIR, exist_ok=True)

st.sidebar.markdown("#### Data source")
use_uploads = st.sidebar.toggle("Upload my own data", value=False,
    help="OFF = bundled Feb/Mar/Apr 2026 data. ON = upload customer files.")

if use_uploads:
    ups = st.sidebar.file_uploader("UPW Plant Daily Reports (.xls / .xlsx)",
                                    type=["xls", "xlsx"], accept_multiple_files=True)
    elog = st.sidebar.file_uploader("Energy log (.csv)", type=["csv"])
    tmp = Path("/tmp/ix_uploads")
    tmp.mkdir(exist_ok=True)
    if ups:
        for u in ups:
            (tmp / u.name).write_bytes(u.getbuffer())
        DATA_DIR = str(tmp)
    if elog:
        (tmp / "energy_log.csv").write_bytes(elog.getbuffer())

excel_files = sorted([f for f in os.listdir(DATA_DIR) if f.endswith((".xls", ".xlsx"))])
if not excel_files:
    st.error(f"No Excel files found in `{DATA_DIR}`. Toggle uploads ON and add files.")
    st.stop()

st.sidebar.markdown(f"**Reports loaded:** {len(excel_files)}")
with st.sidebar.expander("File list"):
    for f in excel_files:
        st.markdown(f"- {f}")

energy_csv = os.path.join(DATA_DIR, "energy_log.csv")
has_energy = os.path.exists(energy_csv)
st.sidebar.markdown(f"**Energy logbook:** {'✅ loaded' if has_energy else '⚠️ missing'}")

roll_win = st.sidebar.slider("Smoothing window (days)", 1, 7, 3,
                             help="Rolling-mean window for KPI smoothing.")
op_hours = st.sidebar.number_input("RO operating hours / day",
                                   min_value=1.0, max_value=24.0, value=24.0, step=1.0)

df = load_data(DATA_DIR, energy_csv if has_energy else None, roll_win, op_hours)
if df.empty:
    st.error("Could not parse RO Stage 1 sheet — verify column layout.")
    st.stop()

trains_all = sorted(df["Train"].unique())

min_d, max_d = df["Timestamp"].min().date(), df["Timestamp"].max().date()
date_range = st.sidebar.date_input("Date range", value=(min_d, max_d),
                                   min_value=min_d, max_value=max_d)
if isinstance(date_range, tuple) and len(date_range) == 2:
    d0, d1 = date_range
    mask = (df["Timestamp"].dt.date >= d0) & (df["Timestamp"].dt.date <= d1)
    df = df[mask].copy()

train_pick = st.sidebar.multiselect("RO trains", trains_all, default=trains_all)
df = df[df["Train"].isin(train_pick)].copy()

st.sidebar.markdown("---")
st.sidebar.markdown("#### Business assumptions")
water_price  = st.sidebar.number_input("Water value (₹ / m³)", 0.0, 500.0, 50.0, 5.0)
cip_cost     = st.sidebar.number_input("Unplanned CIP cost (₹ lakh)", 0.0, 50.0, 3.5, 0.5)
downtime_hrs = st.sidebar.number_input("Unplanned CIP downtime (hrs)", 0.0, 72.0, 8.0, 1.0)
energy_price = st.sidebar.number_input("Energy tariff (₹ / kWh)", 0.0, 30.0, 8.5, 0.5)


# ======================================================================
# HEADER
# ======================================================================
col_a, col_b = st.columns([4, 1])
with col_a:
    st.markdown("<div class='brand'>Ion Exchange (India) Ltd. &nbsp;·&nbsp; Prepared for Tata Power Solar — Gangaikondan</div>",
                unsafe_allow_html=True)
    st.title("RO Stage 1 — Performance Diagnostic Report")
    st.caption("Physics-based KPI monitoring, fouling diagnosis and CIP decision support.")
with col_b:
    st.markdown(
        f"<div style='text-align:right; padding-top:12px;'>"
        f"<div style='font-size:0.75rem; color:#6B7280; text-transform:uppercase; letter-spacing:0.5px;'>Reporting Window</div>"
        f"<div style='font-weight:600; color:#0B2545;'>{df['Timestamp'].min():%d %b %Y} — {df['Timestamp'].max():%d %b %Y}</div>"
        f"</div>", unsafe_allow_html=True)
st.markdown("---")


# ======================================================================
# HELPERS
# ======================================================================
def kpi_card(col, label, value, sub=""):
    col.markdown(
        f"<div class='metric-card'><div class='label'>{label}</div>"
        f"<div class='value'>{value}</div><div class='sub'>{sub}</div></div>",
        unsafe_allow_html=True)


def sev_badge(sev: str, diagnosis: str = "Normal Operation") -> str:
    if not sev and diagnosis != "Normal Operation":
        return "<span class='badge' style='background:#FFB300'>Watch</span>"
    col = eng.SEV_COLOR.get(sev, "#888")
    text = sev if sev else "Healthy"
    return f"<span class='badge' style='background:{col}'>{text}</span>"


TRAIN_COLOR = {"RO A": "#0B3D91", "RO B": "#EF6C00", "RO C": "#2E7D32"}


# ======================================================================
# SYSTEM HEALTH SNAPSHOT
# ======================================================================
st.subheader("System Health Snapshot")

k1, k2, k3, k4, k5, k6 = st.columns(6)

# Daily data — total = sum(NPF) × hours, since each row is one day
total_prod_m3  = (df["NPF"].fillna(0) * op_hours).sum()
avg_recovery   = df["Recovery"].mean()
avg_salt_rej   = df["SaltRej"].mean()
avg_health     = df["Health"].mean()

last_per_train = df.sort_values("Timestamp").groupby("Train").tail(1)
worst_sev = ""
for s in last_per_train["CIP"]:
    if eng.SEV_ORDER.index(s or "") > eng.SEV_ORDER.index(worst_sev):
        worst_sev = s

non_normal = df[df["Diagnosis"] != "Normal Operation"].copy()
non_normal["Date"] = non_normal["Timestamp"].dt.date
fouling_days = non_normal.groupby("Train")["Date"].nunique().max() if len(non_normal) else 0

days_list = []
any_breached = False
for train in train_pick:
    g = df[df["Train"] == train]
    f = eng.forecast_days_to_cip(g)
    if f.get("already_breached"):
        any_breached = True
    if pd.notna(f.get("days_to_cip", np.nan)) and np.isfinite(f["days_to_cip"]):
        days_list.append((train, f["days_to_cip"], f["limiting_kpi"], f.get("severity", "")))
days_to_cip_val = min([d[1] for d in days_list]) if days_list else None

kpi_card(k1, "Total Permeate Produced",  f"{total_prod_m3:,.0f} m³", "Across selected window")
kpi_card(k2, "Avg Recovery",             f"{avg_recovery:.1f} %",   "Permeate / Feed")
kpi_card(k3, "Avg Salt Rejection",       f"{avg_salt_rej:.2f} %",   "1 − Permeate/Feed cond.")
kpi_card(k4, "Avg Health Score",         f"{avg_health:.0f} / 100", "Composite index")
kpi_card(k5, "Fouling Acc. Days",        f"{fouling_days}",         "Days with abnormal diagnosis")
if days_to_cip_val is None:
    _cip_val, _cip_sub = "—", "No trend data"
elif any_breached and days_to_cip_val == 0.0:
    _cip_val, _cip_sub = "Overdue", "Threshold already breached"
elif any_breached:
    best = min([x for x in days_list if pd.notna(x[1]) and np.isfinite(x[1])], key=lambda x: x[1], default=days_list[0])
    _cip_val = f"{days_to_cip_val:.1f}"
    _cip_sub = f"Days to {best[3]} (escalated)"
else:
    _cip_val, _cip_sub = f"{days_to_cip_val:.1f}", "Linear forecast"
kpi_card(k6, "Days to next CIP", _cip_val, _cip_sub)

st.markdown("")
current_status_cols = st.columns(len(train_pick) if train_pick else 1)
for i, train in enumerate(train_pick):
    row = last_per_train[last_per_train["Train"] == train]
    if row.empty: continue
    row = row.iloc[0]
    current_status_cols[i].markdown(
        f"### {train}\n"
        f"- **CIP status:** {sev_badge(row['CIP'], row['Diagnosis'])}\n"
        f"- **Diagnosis:** <span style='color:{eng.DIAG_COLOR.get(row['Diagnosis'], '#333')}'>"
        f"<b>{row['Diagnosis']}</b></span>\n"
        f"- Health: **{row['Health']:.0f}/100**  ·  NPF Δ **{row['NPF_pct']:+.1f}%**  ·  "
        f"NSP Δ **{row['NSP_pct']:+.1f}%**  ·  ΔP Δ **{row['DP_pct']:+.1f}%**",
        unsafe_allow_html=True)

st.markdown("---")


# ======================================================================
# TABS
# ======================================================================
(tab_overview, tab_fouling, tab_stage, tab_diag, tab_cip,
 tab_forecast, tab_energy, tab_exec) = st.tabs([
    "Overview", "Fouling Indicators", "Stage Analysis",
    "Diagnosis", "CIP Decision", "Forecast & OEE",
    "Energy & SEC", "Executive Summary"
])


# -----------------------------------------------------------------
# OVERVIEW TAB
# -----------------------------------------------------------------
with tab_overview:
    st.markdown("### Health score trend (daily mean)")
    daily = (df.assign(Date=df["Timestamp"].dt.date)
               .groupby(["Train", "Date"])
               .agg(Health=("Health", "mean"),
                    NPF_pct=("NPF_pct", "mean"),
                    NSP_pct=("NSP_pct", "mean"),
                    DP_pct=("DP_pct", "mean"),
                    Feed_pct=("FeedPress_pct", "mean"),
                    CIP=("CIP", lambda s: max((v for v in s if v in eng.SEV_ORDER), key=lambda v: eng.SEV_ORDER.index(v)) if any(v for v in s) else ""),
                    Diagnosis=("Diagnosis", lambda s: (pd.Series([x for x in s if x != "Normal Operation"]).mode().iloc[0]
                                                      if any(x != "Normal Operation" for x in s) else "Normal Operation")))
               .reset_index())

    fig = px.line(daily, x="Date", y="Health", color="Train",
                  markers=True, line_shape="spline",
                  color_discrete_map=TRAIN_COLOR)
    fig.add_hrect(y0=80, y1=100, fillcolor="#2E7D32", opacity=0.08, line_width=0,
                  annotation_text="Healthy", annotation_position="top left")
    fig.add_hrect(y0=60, y1=80,  fillcolor="#FFB300", opacity=0.08, line_width=0,
                  annotation_text="Watch",   annotation_position="top left")
    fig.add_hrect(y0=0,  y1=60,  fillcolor="#C62828", opacity=0.08, line_width=0,
                  annotation_text="Risk",    annotation_position="top left")
    fig.update_layout(height=360, yaxis_title="Health score", yaxis_range=[0, 105],
                      margin=dict(l=10, r=10, t=20, b=10), legend_title="")
    st.plotly_chart(fig, use_container_width=True)

    cL, cR = st.columns(2)
    with cL:
        st.markdown("### Recovery (%) — train comparison")
        fig = px.line(df, x="Timestamp", y="Recovery_sm", color="Train",
                      color_discrete_map=TRAIN_COLOR)
        fig.update_layout(height=320, yaxis_title="Recovery (%)",
                          margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)
    with cR:
        st.markdown("### Salt rejection (%) — train comparison")
        fig = px.line(df, x="Timestamp", y="SaltRej_sm", color="Train",
                      color_discrete_map=TRAIN_COLOR)
        fig.update_layout(height=320, yaxis_title="Salt rejection (%)",
                          margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)


# -----------------------------------------------------------------
# FOULING INDICATORS TAB
# -----------------------------------------------------------------
with tab_fouling:
    st.markdown("### Core KPIs — % change vs baseline (smoothed)")
    kpi_cols = [("NPF_pct", "NPF (↓ = flux loss)", "#0B3D91"),
                ("NSP_pct", "NSP (↑ = rejection loss)", "#6A1B9A"),
                ("DP_pct",  "ΔP (↑ = fouling / scaling)", "#2E7D32"),
                ("FeedPress_pct", "Feed Pressure (↑ = pretreatment strain)", "#EF6C00")]

    for train in train_pick:
        g = df[df["Train"] == train].sort_values("Timestamp")
        fig = make_subplots(rows=2, cols=2,
                            subplot_titles=[t[1] for t in kpi_cols],
                            shared_xaxes=True, vertical_spacing=0.12, horizontal_spacing=0.08)
        for i, (col, _, color) in enumerate(kpi_cols):
            r, c = divmod(i, 2); r += 1; c += 1
            fig.add_trace(go.Scatter(x=g["Timestamp"], y=g[col], mode="lines",
                                     line=dict(color=color, width=2),
                                     name=col, showlegend=False), row=r, col=c)
            fig.add_hline(y=0, line=dict(color="black", width=0.6, dash="dot"), row=r, col=c)
            if col == "NPF_pct":
                fig.add_hline(y=-5,  line=dict(color="#FFB300", dash="dash"), row=r, col=c)
                fig.add_hline(y=-10, line=dict(color="#FB8C00", dash="dash"), row=r, col=c)
                fig.add_hline(y=-15, line=dict(color="#C62828", dash="dash"), row=r, col=c)
            elif col == "NSP_pct":
                fig.add_hline(y=10, line=dict(color="#FFB300", dash="dash"), row=r, col=c)
                fig.add_hline(y=15, line=dict(color="#FB8C00", dash="dash"), row=r, col=c)
                fig.add_hline(y=25, line=dict(color="#C62828", dash="dash"), row=r, col=c)
            else:
                fig.add_hline(y=10, line=dict(color="#FFB300", dash="dash"), row=r, col=c)
                fig.add_hline(y=20, line=dict(color="#C62828", dash="dash"), row=r, col=c)
        fig.update_layout(height=520, title=f"{train} — Physics KPIs",
                          margin=dict(l=20, r=10, t=60, b=20))
        st.plotly_chart(fig, use_container_width=True)

    st.info("Dashed lines mark the CIP-action thresholds from the Ion Exchange RO "
            "performance calculations: amber = **Due**, orange = **Cleaning Required**, red = **Critical**.")


# -----------------------------------------------------------------
# STAGE ANALYSIS TAB
# -----------------------------------------------------------------
with tab_stage:
    st.markdown("### Stage-wise ΔP — localises where fouling / scaling starts")
    st.caption("For Tata Solar RO Stage 1 we surface two physical 'stages': "
               "**Stage 1 = MCF (micro-cartridge filter) ΔP** — early indicator of particulate load; "
               "**Stage 2 = RO membrane ΔP** — indicator of biofouling / scaling. "
               "A rise in Stage 1 points to **particulate or pre-treatment issue**; "
               "a rise in Stage 2 points to **membrane fouling**.")

    for train in train_pick:
        g = df[df["Train"] == train].sort_values("Timestamp")
        cols = ["DP_Stage_1_sm", "DP_Stage_2_sm"]
        labels = ["Stage 1 (MCF)", "Stage 2 (Membrane)"]
        colors = ["#0B3D91", "#EF6C00"]
        fig = go.Figure()
        for c, lab, clr in zip(cols, labels, colors):
            if g[c].notna().any():
                fig.add_trace(go.Scatter(x=g["Timestamp"], y=g[c], mode="lines",
                                         line=dict(color=clr, width=2), name=lab))
        fig.update_layout(height=330, title=f"{train} — Stage ΔP (smoothed, kg/cm²)",
                          yaxis_title="ΔP (kg/cm²)", legend_title="",
                          margin=dict(l=10, r=10, t=50, b=10))
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("### Stage ΔP — % change from baseline")
    for train in train_pick:
        g = df[df["Train"] == train].sort_values("Timestamp")
        rows = []
        for c, lab in zip(["DP_Stage_1_pct", "DP_Stage_2_pct"],
                          ["Stage 1 (MCF)", "Stage 2 (Membrane)"]):
            if c in g.columns and g[c].notna().any():
                rows.append(dict(train=train, stage=lab,
                                 cur=g[c].dropna().iloc[-1],
                                 mean=g[c].mean()))
        if rows:
            sdf = pd.DataFrame(rows)
            fig = px.bar(sdf, x="stage", y="cur", text="cur",
                         color="stage",
                         color_discrete_map={"Stage 1 (MCF)":"#0B3D91","Stage 2 (Membrane)":"#EF6C00"},
                         labels={"cur":"% change vs baseline"})
            fig.update_traces(texttemplate="%{text:+.1f}%", textposition="outside")
            fig.update_layout(height=280, title=f"{train} — current stage ΔP deviation",
                              showlegend=False, margin=dict(l=10, r=10, t=40, b=10))
            st.plotly_chart(fig, use_container_width=True)


# -----------------------------------------------------------------
# DIAGNOSIS TAB
# -----------------------------------------------------------------
with tab_diag:
    st.markdown("### Fouling diagnosis timeline")
    st.caption("Each confirmed (latched) abnormal pattern is labelled per the 12-category decision tree "
               "from the Ion Exchange RO performance standard.")

    for train in train_pick:
        g = df[df["Train"] == train].copy()
        g["Diagnosis_code"] = g["Diagnosis"].map(eng.DIAG_CODE)
        fig = px.scatter(g, x="Timestamp", y="Diagnosis",
                         color="Diagnosis",
                         color_discrete_map=eng.DIAG_COLOR,
                         height=340)
        fig.update_traces(marker=dict(size=7))
        fig.update_layout(title=f"{train} — diagnosis over time",
                          margin=dict(l=10, r=10, t=40, b=10), showlegend=False,
                          yaxis=dict(categoryorder="array",
                                     categoryarray=eng.DIAGNOSIS_ORDER))
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("### Diagnosis mix (non-normal only)")
    ab = df[df["Diagnosis"] != "Normal Operation"]
    if ab.empty:
        st.success("No abnormal patterns detected in the selected window — all diagnoses = Normal Operation.")
    else:
        mix = ab.groupby(["Train", "Diagnosis"]).size().reset_index(name="Samples")
        fig = px.bar(mix, x="Samples", y="Diagnosis", color="Train", orientation="h",
                     color_discrete_map=TRAIN_COLOR, barmode="group")
        fig.update_layout(height=380, yaxis=dict(categoryorder="total ascending"),
                          margin=dict(l=10, r=10, t=20, b=10))
        st.plotly_chart(fig, use_container_width=True)


# -----------------------------------------------------------------
# CIP DECISION TAB
# -----------------------------------------------------------------
with tab_cip:
    st.markdown("### CIP severity — calendar view")
    daily_kpi = (df.assign(Date=df["Timestamp"].dt.date)
                   .groupby(["Train","Date"])[["NPF_pct","NSP_pct","DP_pct","FeedPress_pct"]]
                   .median().reset_index())
    daily_kpi["CIP"] = [eng.classify_cip(a, b, c, d)
                        for a, b, c, d in zip(daily_kpi["NPF_pct"], daily_kpi["NSP_pct"],
                                              daily_kpi["DP_pct"],  daily_kpi["FeedPress_pct"])]
    daily_kpi["CIP"] = eng.latch_sev(daily_kpi["CIP"].tolist())
    daily_cip = daily_kpi[["Train","Date","CIP"]]
    pv = daily_cip.pivot(index="Date", columns="Train", values="CIP").fillna("")
    sev_to_num = {"":0, "Due":1, "Cleaning Required":2, "Critical":3}
    z = pv.replace(sev_to_num).values
    fig = go.Figure(data=go.Heatmap(
        z=z, x=list(pv.columns), y=[str(d) for d in pv.index],
        colorscale=[[0, "#E0F2F1"], [0.33, "#FFD54F"], [0.66, "#FB8C00"], [1, "#C62828"]],
        zmin=0, zmax=3, showscale=False,
        text=pv.values, hovertemplate="%{y} | %{x}<br>Severity: %{text}<extra></extra>",
    ))
    fig.update_layout(height=max(380, 20*len(pv)), margin=dict(l=10, r=10, t=20, b=10))
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("### Recommended CIP actions")
    recs = daily_cip[daily_cip["CIP"] != ""].merge(
        daily.drop(columns=["CIP"], errors="ignore"), on=["Train","Date"], how="left")
    if recs.empty:
        st.success("No CIP action flagged in the selected window.")
    else:
        recs["Date"] = pd.to_datetime(recs["Date"]).dt.strftime("%d %b %Y")
        st.dataframe(
            recs[["Date","Train","CIP","Diagnosis",
                  "NPF_pct","NSP_pct","DP_pct","Feed_pct","Health"]]
                .rename(columns={"NPF_pct":"ΔNPF %","NSP_pct":"ΔNSP %",
                                 "DP_pct":"ΔΔP %","Feed_pct":"ΔFeed %",
                                 "Health":"Health"})
                .style.format({"ΔNPF %":"{:+.1f}","ΔNSP %":"{:+.1f}",
                               "ΔΔP %":"{:+.1f}","ΔFeed %":"{:+.1f}","Health":"{:.0f}"}),
            use_container_width=True, height=340)

    st.markdown("---")
    st.markdown("### Recommended vs Actual CIP")
    st.caption("Blue markers are CIP events actually performed by the site team. "
               "Orange shading marks the days our engine recommended cleaning.")

    actual_cip = {t: pd.to_datetime(eng.ACTUAL_CIP.get(t, [])) for t in train_pick}

    for train in train_pick:
        g = df[df["Train"] == train].sort_values("Timestamp")
        if g.empty: continue
        rec_dates = daily_cip[(daily_cip["Train"]==train) & (daily_cip["CIP"]!="")]
        rec_dates = pd.to_datetime(rec_dates["Date"])

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=g["Timestamp"], y=g["NPF_pct"], mode="lines",
            line=dict(color="#0B2545", width=1.8), name="NPF % change"))
        for d in rec_dates:
            fig.add_vrect(x0=d, x1=d + pd.Timedelta(hours=20),
                          fillcolor="#FB8C00", opacity=0.22, line_width=0,
                          layer="below")
        for d in actual_cip.get(train, []):
            fig.add_vline(x=d, line=dict(color="#1565C0", width=2, dash="solid"))
            fig.add_annotation(x=d, y=1.02, yref="paper", showarrow=False,
                               text="Actual CIP", font=dict(size=10, color="#1565C0"),
                               bgcolor="#E3F2FD", borderpad=2)

        fig.add_hline(y=-5,  line=dict(color="#9CA3AF", dash="dot", width=1))
        fig.add_hline(y=-10, line=dict(color="#FB8C00", dash="dot", width=1))
        fig.add_hline(y=-15, line=dict(color="#C62828", dash="dot", width=1))
        fig.update_layout(height=340, title=f"{train} — NPF deterioration with CIP events",
                          yaxis_title="NPF % change vs baseline",
                          margin=dict(l=10, r=10, t=60, b=10),
                          plot_bgcolor="white", paper_bgcolor="white",
                          showlegend=False)
        fig.update_xaxes(showgrid=False, showline=True, linecolor="#E4E9F2")
        fig.update_yaxes(showgrid=True, gridcolor="#F1F3F5", showline=True, linecolor="#E4E9F2")
        st.plotly_chart(fig, use_container_width=True)

    rows = []
    for train in train_pick:
        rec_dates = daily_cip[(daily_cip["Train"]==train) & (daily_cip["CIP"]!="")]
        rec_dates = pd.to_datetime(rec_dates["Date"])
        for d in actual_cip.get(train, []):
            if rec_dates.empty:
                rows.append(dict(Train=train, **{"Actual CIP": d.strftime("%d %b %Y"),
                                                 "Nearest Recommendation": "—",
                                                 "Days (rec → act)": "—",
                                                 "Assessment": "No recommendation in window"}))
                continue
            deltas = (d - rec_dates).dt.days
            ahead = deltas[deltas >= 0]
            if not ahead.empty:
                idx = ahead.idxmin()
                lag = int(ahead.min())
                assess = ("On-time" if lag <= 1 else
                          "Site cleaned within 3 days of recommendation" if lag <= 3 else
                          f"Site cleaned {lag} days after recommendation")
            else:
                idx = deltas.abs().idxmin()
                lag = int(deltas[idx])
                assess = f"Recommendation came {abs(lag)} days after actual clean"
            rows.append(dict(Train=train,
                             **{"Actual CIP": d.strftime("%d %b %Y"),
                                "Nearest Recommendation": rec_dates.loc[idx].strftime("%d %b %Y"),
                                "Days (rec → act)": lag,
                                "Assessment": assess}))

    if rows:
        st.markdown("#### Alignment between our recommendation and site execution")
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.caption("Positive *Days (rec → act)* means our engine flagged the need to clean that many days "
                   "before the site actually performed it — the larger the number, the greater the avoidable "
                   "flux loss. Negative values indicate the recommendation was not available in time.")
    else:
        st.info("No actual CIP events recorded yet for Tata Solar — "
                "once the site shares their flushing log, this table populates automatically.")


# -----------------------------------------------------------------
# FORECAST & OEE TAB
# -----------------------------------------------------------------
with tab_forecast:
    st.markdown("### 15-Day CIP Risk Forecast")
    st.caption("Linear extrapolation of each KPI over the next 15 days against all three CIP action thresholds.")

    FORECAST_DAYS = 15
    SEV_STYLE     = {
        "Due":               dict(color="#FFB300", dash="dot"),
        "Cleaning Required": dict(color="#FB8C00", dash="dash"),
        "Critical":          dict(color="#C62828", dash="dashdot"),
    }
    KPI_CONFIGS = [
        ("NPF_pct",       "NPF % vs baseline",         "down",
         {s: eng.CIP_THRESH[s]["npf"]  for s in eng.SEV_ORDER[1:]}),
        ("NSP_pct",       "NSP % vs baseline",         "up",
         {s: eng.CIP_THRESH[s]["nsp"]  for s in eng.SEV_ORDER[1:]}),
        ("DP_pct",        "ΔP % vs baseline",          "up",
         {s: eng.CIP_THRESH[s]["dp"]   for s in eng.SEV_ORDER[1:]}),
        ("FeedPress_pct", "Feed Pressure % vs baseline","up",
         {s: eng.CIP_THRESH[s]["feed"] for s in eng.SEV_ORDER[1:]}),
    ]

    summary_rows = []
    for train in train_pick:
        g = df[df["Train"] == train].sort_values("Timestamp")
        sub = g.dropna(subset=["NPF_pct","NSP_pct","DP_pct","FeedPress_pct"])
        if len(sub) < 4:
            continue
        xd = (sub["Timestamp"] - sub["Timestamp"].iloc[0]).dt.total_seconds() / 86400.0
        last_x = float(xd.iloc[-1])
        for col, label, sign, thresholds in KPI_CONFIGS:
            y = sub[col].values
            m, b = np.polyfit(xd, y, 1)
            cur = float(y[-1])
            row = {"Train": train, "KPI": label.split(" %")[0], f"Current": f"{cur:+.1f}%"}
            for sev, target in thresholds.items():
                if sign == "down":
                    if cur <= target:                cell = "🔴 Overdue"
                    elif m < 0:
                        d = (target - b) / m - last_x
                        cell = "🔴 Overdue" if d <= 0 else (f"{d:.1f} d" if d <= FORECAST_DAYS else ">15 d")
                    else:                            cell = "Stable ✅"
                else:
                    if cur >= target:                cell = "🔴 Overdue"
                    elif m > 0:
                        d = (target - b) / m - last_x
                        cell = "🔴 Overdue" if d <= 0 else (f"{d:.1f} d" if d <= FORECAST_DAYS else ">15 d")
                    else:                            cell = "Stable ✅"
                row[sev] = cell
            summary_rows.append(row)

    if summary_rows:
        st.dataframe(pd.DataFrame(summary_rows).set_index(["Train", "KPI"]),
                     use_container_width=True)
    st.markdown("")

    fig = make_subplots(rows=2, cols=2,
                        subplot_titles=[c[1] for c in KPI_CONFIGS],
                        vertical_spacing=0.14, horizontal_spacing=0.08)
    legend_trains = set()
    for idx, (col, ylabel, sign, thresholds) in enumerate(KPI_CONFIGS):
        r, c = divmod(idx, 2); r += 1; c += 1
        for train in train_pick:
            g = df[df["Train"] == train].sort_values("Timestamp")
            sub = g.dropna(subset=[col])
            if len(sub) < 4: continue
            clr = TRAIN_COLOR.get(train, "#333")
            x   = sub["Timestamp"]; y = sub[col].values
            xd  = (x - x.iloc[0]).dt.total_seconds() / 86400
            m, b = np.polyfit(xd, y, 1)
            fig.add_trace(go.Scatter(x=x, y=y, mode="lines", name=train,
                                     line=dict(color=clr, width=2),
                                     legendgroup=train,
                                     showlegend=(train not in legend_trains)),
                          row=r, col=c)
            legend_trains.add(train)
            future = pd.date_range(x.iloc[-1], x.iloc[-1] + timedelta(days=FORECAST_DAYS), freq="12h")
            xf = (future - x.iloc[0]).total_seconds() / 86400
            yf = m * xf + b
            fig.add_trace(go.Scatter(x=future, y=yf, mode="lines",
                                     name=f"{train} (forecast)",
                                     line=dict(color=clr, width=1.5, dash="dot"),
                                     showlegend=False),
                          row=r, col=c)
        for sev, target in thresholds.items():
            st_s = SEV_STYLE[sev]
            fig.add_hline(y=target,
                          line=dict(color=st_s["color"], dash=st_s["dash"], width=1.2),
                          annotation_text=sev, annotation_position="bottom right",
                          annotation_font=dict(size=9, color=st_s["color"]),
                          row=r, col=c)

    fig.add_hline(y=0, line=dict(color="#9CA3AF", width=0.6, dash="dot"))
    fig.update_layout(height=640,
                      title=f"15-Day KPI Forecast — {', '.join(train_pick)}",
                      margin=dict(l=10, r=10, t=60, b=10),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Solid = historical · Dotted = 15-day linear forecast · "
               "Amber dotted = **Due** · Orange dashed = **Cleaning Required** · Red dash-dot = **Critical**")

    st.markdown("---")
    st.markdown("### Overall Equipment Effectiveness (OEE)")
    st.caption("OEE = Availability × Performance × Quality. Industry-standard composite of uptime, flux retention, and permeate-quality conformance.")
    ocols = st.columns(len(train_pick) if train_pick else 1)
    for i, train in enumerate(train_pick):
        o = eng.oee(df[df["Train"] == train])
        ocols[i].markdown(f"#### {train}")
        ocols[i].metric("OEE",
                        f"{o['oee']*100:.1f} %" if pd.notna(o['oee']) else "—",
                        help="Composite")
        sub = ocols[i].container()
        sub.markdown(
            f"- Availability: **{o['availability']*100:.1f}%**\n"
            f"- Performance: **{(o['performance'] or 0)*100:.1f}%**\n"
            f"- Quality: **{(o['quality'] or 0)*100:.1f}%**")


# -----------------------------------------------------------------
# ENERGY & SEC TAB  (Tata-Solar-specific addition to the FS template)
# -----------------------------------------------------------------
with tab_energy:
    st.markdown("### Energy & Specific Energy Consumption (SEC)")
    st.caption(
        "**Data mapping** — HP-pump energy meters from the handwritten plant logbook: "
        "row **15** → **RO A**, row **16** → **RO B**, row **17** → **RO C**. "
        "Each value is a cumulative kWh reading; the engine computes the daily delta. "
        "SEC = daily kWh ÷ (NPF × operating hours)."
    )

    if "Energy_kWh" not in df.columns or df["Energy_kWh"].notna().sum() == 0:
        st.warning(
            "Energy logbook not loaded or no overlapping dates. "
            "Drop a filled `energy_log.csv` into `data/dropbox/tata_solar/` "
            "(template + transcription guide live in the project root)."
        )
    else:
        # ---- Top KPI cards per train -------------------------------
        ecols = st.columns(len(train_pick) or 1)
        for i, train in enumerate(train_pick):
            sub = df[df["Train"] == train]
            kwh_total = sub["Energy_kWh"].sum(skipna=True)
            sec_mean  = sub["SEC_kWh_per_m3"].mean(skipna=True)
            cost = kwh_total * energy_price
            sub_txt = (f"avg SEC {sec_mean:.2f} kWh/m³"
                       if pd.notna(sec_mean) else "no overlap with operational dates")
            kpi_card(ecols[i], f"{train}", f"{kwh_total:,.0f} kWh · ₹{cost:,.0f}", sub_txt)

        # ---- Daily kWh per train -----------------------------------
        st.markdown("##### Daily HP-pump energy (kWh)")
        fig = go.Figure()
        for t in train_pick:
            sub = df[df["Train"] == t]
            fig.add_trace(go.Scatter(x=sub["Timestamp"], y=sub["Energy_kWh"],
                                     mode="lines+markers", name=t,
                                     line=dict(color=TRAIN_COLOR.get(t, "#888"), width=2)))
        fig.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10),
                          legend=dict(orientation="h", y=1.12, x=0),
                          yaxis_title="kWh / day")
        st.plotly_chart(fig, use_container_width=True)

        # ---- SEC per train -----------------------------------------
        st.markdown("##### Specific Energy Consumption (kWh / m³ permeate)")
        fig = go.Figure()
        for t in train_pick:
            sub = df[df["Train"] == t]
            fig.add_trace(go.Scatter(x=sub["Timestamp"], y=sub["SEC_kWh_per_m3"],
                                     mode="lines+markers", name=t,
                                     line=dict(color=TRAIN_COLOR.get(t, "#888"), width=2)))
        fig.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10),
                          legend=dict(orientation="h", y=1.12, x=0),
                          yaxis_title="kWh / m³")
        st.plotly_chart(fig, use_container_width=True)

        # ---- Energy-vs-fouling correlation -------------------------
        st.markdown("##### Energy drift vs membrane fouling")
        st.caption("If membrane DP rises while energy stays flat, the HP pump is doing the same "
                   "work but losing flux — a fouling signature.  If energy climbs with DP, the "
                   "pump is compensating for resistance — a pre-treatment or scaling signature.")
        for t in train_pick:
            sub = df[df["Train"] == t]
            if sub["Energy_kWh"].notna().sum() < 3:
                continue
            fig = make_subplots(specs=[[{"secondary_y": True}]])
            fig.add_trace(go.Scatter(x=sub["Timestamp"], y=sub["DP_pct"],
                                     mode="lines", name="DP % vs baseline",
                                     line=dict(color="#C62828", width=2)),
                          secondary_y=False)
            fig.add_trace(go.Scatter(x=sub["Timestamp"], y=sub["Energy_kWh"],
                                     mode="lines+markers", name="Daily kWh",
                                     line=dict(color="#0B3D91", width=2)),
                          secondary_y=True)
            fig.update_layout(height=280, title=f"{t} — DP drift vs daily kWh",
                              margin=dict(l=10, r=10, t=50, b=10),
                              legend=dict(orientation="h", y=1.12, x=0))
            fig.update_yaxes(title_text="DP drift (%)", secondary_y=False)
            fig.update_yaxes(title_text="kWh / day",    secondary_y=True)
            st.plotly_chart(fig, use_container_width=True)

        # ---- Raw daily log -----------------------------------------
        st.markdown("##### Daily energy log (raw values from the transcription)")
        e_view = df[["Timestamp", "Train", "Energy_cum_kWh", "Energy_kWh",
                     "NPF", "SEC_kWh_per_m3"]].copy()
        e_view = e_view.rename(columns={
            "Timestamp": "Date", "Energy_cum_kWh": "Cumulative kWh",
            "Energy_kWh": "Daily kWh", "NPF": "NPF (m³/hr)",
            "SEC_kWh_per_m3": "SEC (kWh/m³)"})
        e_view["Date"] = pd.to_datetime(e_view["Date"]).dt.strftime("%d %b %Y")
        st.dataframe(
            e_view.style.format({"Cumulative kWh": "{:,.0f}",
                                  "Daily kWh": "{:,.1f}",
                                  "NPF (m³/hr)": "{:.2f}",
                                  "SEC (kWh/m³)": "{:.3f}"},
                                 na_rep="—"),
            use_container_width=True, height=360, hide_index=True)


# -----------------------------------------------------------------
# EXECUTIVE SUMMARY TAB
# -----------------------------------------------------------------
with tab_exec:
    st.markdown("## Executive Interpretation")
    bullets_assess, bullets_biz, bullets_reco = [], [], []

    flow_loss_pct = -df.groupby("Train")["NPF_pct"].last().min()
    flow_loss_pct = 0 if (flow_loss_pct is None or pd.isna(flow_loss_pct) or flow_loss_pct < 0) else flow_loss_pct
    mean_flow = df["NPF"].mean() or 0
    monthly_loss_m3 = mean_flow * op_hours * 30 * (flow_loss_pct/100)
    monthly_loss_inr = monthly_loss_m3 * water_price / 100000

    predicted_cips = (daily_cip["CIP"] != "").sum() if 'daily_cip' in dir() else 0
    saved_cip_inr = 0.5 * predicted_cips * cip_cost

    worst_diag = (df[df["Diagnosis"]!="Normal Operation"]
                     .groupby(["Train","Diagnosis"]).size().reset_index(name="n")
                     .sort_values("n", ascending=False))
    if worst_diag.empty:
        bullets_assess.append("All trains tracking **baseline** — no confirmed fouling pattern during the reporting window.")
    else:
        for _, r in worst_diag.head(3).iterrows():
            bullets_assess.append(f"**{r['Train']}** shows a dominant pattern of **{r['Diagnosis']}** ({r['n']} confirmed samples).")

    finite_days = [(t, d, k, s) for t, d, k, s in days_list if pd.notna(d) and np.isfinite(d)]
    if finite_days:
        t, d, k, *_ = min(finite_days, key=lambda x: x[1])
        bullets_assess.append(f"Projected **CIP window**: **{t}** in **{d:.1f} days**, limited by **{k}**.")
    else:
        bullets_assess.append("No KPI is presently trending toward the CIP threshold — system in **steady state**.")

    bullets_biz.append(f"Early fouling detection at current decline rate preserves ~**{monthly_loss_m3:,.0f} m³/month** of permeate "
                       f"(≈ **₹{monthly_loss_inr:.1f} lakh/month** at ₹{water_price:.0f}/m³).")
    if predicted_cips:
        bullets_biz.append(f"Predictive CIP scheduling is expected to avoid at least **~{predicted_cips//2} unplanned CIPs** "
                           f"(≈ **₹{saved_cip_inr:.1f} lakh** avoided and **~{(predicted_cips//2)*downtime_hrs:.0f} hrs** of downtime retained).")
    # Energy bullet (Tata Solar specific)
    if "Energy_kWh" in df.columns and df["Energy_kWh"].notna().sum() > 0:
        kwh_total = df["Energy_kWh"].sum(skipna=True)
        sec_mean = df["SEC_kWh_per_m3"].mean(skipna=True)
        bullets_biz.append(f"HP-pump energy in this window: **{kwh_total:,.0f} kWh** "
                           f"(₹{kwh_total*energy_price:,.0f} at ₹{energy_price}/kWh) · "
                           f"avg SEC **{sec_mean:.2f} kWh/m³**.")
    bullets_biz.append("Stage-wise ΔP localisation shortens root-cause diagnosis from days to hours — "
                       "reducing CIP chemistry wastage and operator load.")

    bullets_reco.append("Continue the **daily** KPI review cadence — trend-latched triggers eliminate false alarms from sensor noise.")
    if not worst_diag.empty:
        top = worst_diag.iloc[0]["Diagnosis"]
        if "Scaling" in top:
            bullets_reco.append("Increase **antiscalant dosing** and verify dose pump calibration; review LSI on raw feed.")
        elif "Organic" in top or "Biofouling" in top:
            bullets_reco.append("Review **chlorine residual/UV dose** upstream; schedule alkaline CIP before biofilm matures.")
        elif "Particulate" in top or "Colloidal" in top:
            bullets_reco.append("Audit **cartridge filters and upstream media filter backwash** — particulate break-through in progress.")
        elif "Oxidation" in top or "Chlorine" in top:
            bullets_reco.append("Immediately verify **SMBS dosing and free chlorine** at RO inlet — risk of irreversible membrane oxidation.")
        elif "Compaction" in top:
            bullets_reco.append("Review operating pressure envelope; sustained over-pressure causes irreversible compaction.")
    bullets_reco.append("Commission SDI, free-chlorine and feed-temperature tags into the daily log — unlocks the full decision tree and temperature-corrected TCF.")
    bullets_reco.append("Adopt a **predictive CIP schedule** driven by this dashboard to move from reactive to planned maintenance.")

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("### System Assessment")
        for b in bullets_assess:
            st.markdown(f"- {b}")
    with c2:
        st.markdown("### Business Impact")
        for b in bullets_biz:
            st.markdown(f"- {b}")
    with c3:
        st.markdown("### Strategic Recommendation")
        for b in bullets_reco:
            st.markdown(f"- {b}")

    st.markdown("---")
    st.markdown("### Export")
    cols_for_export = ["Timestamp","Train","NPF","NSP","DP","FeedPress","Recovery","SaltRej",
                      "NPF_pct","NSP_pct","DP_pct","FeedPress_pct",
                      "Diagnosis","CIP","Health","Energy_kWh","SEC_kWh_per_m3"]
    cols_for_export = [c for c in cols_for_export if c in df.columns]
    exp = df[cols_for_export].copy()
    csv = exp.to_csv(index=False).encode("utf-8")
    st.download_button("Download full KPI CSV", csv,
                       file_name="tata_solar_ro_stage1_kpi_export.csv",
                       mime="text/csv")

st.markdown(
    "<div class='footer'>© Ion Exchange (India) Ltd. · Prepared for Tata Power Solar — Gangaikondan · "
    "Methodology: RO Performance Calculations v1 · Dashboard v1.0</div>",
    unsafe_allow_html=True)

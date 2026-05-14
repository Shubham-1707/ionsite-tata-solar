# IONSiTE OS — Tata Solar Dashboard (Streamlit Cloud)

Self-contained Streamlit Cloud build of the Tata Solar (TPSL Gangaikondan)
RO Stage 1 diagnostic dashboard.

## What's inside

```
streamlit_cloud/
├── app.py                 # The Streamlit app (single page)
├── engine.py              # Data engine — Excel + energy parsing, drift, CIP
├── requirements.txt       # Python deps for Streamlit Cloud
├── README.md              # This file
└── data/
    ├── UPW Plant - Daily Report_as of FEB- 2026.xls
    ├── UPW Plant - Daily Report_Mar- 2026-2.xls
    ├── 1.UPW Plant - Daily Report_APRIL-24- 2026.xls
    └── energy_log.csv     # Partial Feb energy transcription
```

## Local sanity test

```bash
cd streamlit_cloud
pip install -r requirements.txt
streamlit run app.py
```

Opens at http://localhost:8501.

## Deploy to Streamlit Community Cloud (free tier)

1. Push **only this `streamlit_cloud/` folder** to a (private) GitHub repo,
   e.g. `ionexchange/ionsite-tata-solar`. From this folder:
   ```bash
   git init
   git add .
   git commit -m "IONSiTE OS — Tata Solar v1"
   git branch -M main
   git remote add origin https://github.com/<your-org>/ionsite-tata-solar.git
   git push -u origin main
   ```

2. Sign in to https://share.streamlit.io with the same GitHub account.

3. Click **Create app** → **Deploy a public app from GitHub** (or private,
   depending on your tier).

4. Fill in:
   - **Repository:** `ionexchange/ionsite-tata-solar`
   - **Branch:** `main`
   - **Main file path:** `app.py`
   - **App URL:** `ionsite-tata-solar` (yields `https://ionsite-tata-solar.streamlit.app`)

5. Click **Deploy**. First build takes ~2 min (installs deps). Subsequent
   pushes redeploy in ~30 s.

## Updating the data

Two ways:

**Option A — bundle in repo** (anyone with the URL sees the latest):
1. Drop a new `*.xls` into `data/`, or update `energy_log.csv`.
2. `git add . && git commit -m "data update" && git push`.
3. Streamlit Cloud auto-rebuilds.

**Option B — uploads at runtime** (for ad-hoc customer POCs):
1. In the deployed app, toggle **"Upload my own data"** in the sidebar.
2. Drag in the customer's monthly Excels + energy CSV.
3. The dashboard renders against those uploads without touching the bundled data.

## Replacing baselines with site-specific numbers

Open `engine.py`, find the `BASELINES_OVERRIDE` block near the top, set
`OVERRIDE_BASELINES = True` and fill in the per-train values Baskar
provides. Push the change — the dashboard switches over.

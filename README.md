# BioResearch Eval Dashboard

A Streamlit dashboard for tracking and evaluating biotech research pipeline predictions against real catalyst outcomes. Reads data from Supabase and displays live stock prices via yfinance.

## Features

### Watchlist
Track active predictions with urgency status (Overdue, Due Soon, Upcoming), live prices, and conviction scores. Filter by status, action, and minimum conviction.

### Scorecard
Six core evaluation metrics comparing predictions to outcomes:
- **Hit Rate** — % of BUY recommendations with positive returns
- **Avoidance Rate** — % of PASS/MONITOR that avoided >20% losses
- **PTS Calibration** — Brier score for science PTS vs binary outcome
- **PTS Gap Signal** — Spearman correlation between PTS gap and realized returns
- **rNPV Accuracy** — mean |rNPV - realized| / price_before
- **Risk Manager Save Rate** — % of rejections that avoided >30% losses

Includes per-event breakdown and stratified views by event type and conviction level.

### Dataset
Coverage summary showing outcomes, predictions, paired/unpaired counts, and a prediction timeline scatter chart.

## Setup

### Requirements

- Python 3.10+
- A Supabase project with `eval_outcomes` and `eval_predictions` tables

### Install

```bash
pip install -r requirements.txt
```

### Configuration

Create `.streamlit/secrets.toml` with your credentials:

```toml
[supabase]
url = "https://your-project.supabase.co"
service_key = "your-service-key"

[cookie]
name = "bio_eval_auth"
key = "a-random-signature-key"
expiry_days = 30

[credentials.usernames.your_username]
name = "Your Name"
password = "$2b$12$..."  # bcrypt hash
```

Generate a password hash:

```bash
python scripts/hash_password.py
```

### Run locally

```bash
streamlit run app.py
```

## Deployment

Deployed on [Streamlit Community Cloud](https://streamlit.io/cloud). Secrets are configured in the Community Cloud dashboard rather than in a local file.

## Project Structure

```
app.py            — Streamlit app with auth and three dashboard tabs
data_loader.py    — Supabase data loading + yfinance price fetching
models.py         — Pydantic models (outcomes, predictions, watchlist entries)
scorer.py         — Eval scorer computing 6 core metrics
watchlist.py      — Watchlist builder with urgency sorting
scripts/          — Utility scripts (password hashing)
```

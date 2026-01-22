# Narrative Tracker MVP - Streamlit Frontend

An analyst-grade Streamlit dashboard for tracking macro narratives with intensity metrics, sentiment analysis, and alerting capabilities.

## Overview

The Narrative Tracker MVP provides daily monitoring of macro narratives with:
- **Intensity**: Z-score vs trailing baseline (60-day rolling window)
- **Sentiment**: Mean value in range [-1, 1]
- **Rolling Percentiles**: 1-year percentiles for intensity & sentiment
- **Horizon Moves**: Intensity deltas across 1d, 2d, 5d, 10d, 20d horizons
- **Alerts**: Trigger when absolute moves exceed threshold (default 1.0 standard deviation)

### Narrative Taxonomy

The application tracks **11 predefined macro narratives** aligned with the backend API:

**Core Narratives (5):**
1. **Goldilocks Economy** — Growth steady, inflation cooling, risk-on/soft landing
2. **Market Crash** — Sharp selloffs; crisis/contagion; systemic stress
3. **Inflation** — Prices rising/sticky; CPI/PCE; inflation expectations
4. **US Growth Slowdown** — Weakening fundamentals: GDP slowing, recession risk
5. **Stagflation** — High inflation PLUS weak/contracting growth

**Supplementary Narratives (6):**
1. **Worker Layoffs** — Job cuts, restructurings, downsizing
2. **Labor Market** — Hiring, jobs, wages, unemployment trends
3. **International Conflict** — State-level military conflict, geopolitical escalation
4. **Trade War** — Tariffs, export controls, sanctions, trade measures
5. **Fiscal Sustainability** — Government deficits, debt, debt ceiling
6. **Markets / Rate-Watch** — Market positioning, rate speculation

## Prerequisites

- Python 3.9 or higher
- Access to the backend API (HuggingFace Spaces endpoint)
- Environment variables configured (see below)

## Installation

1. **Install dependencies:**
```bash
cd st_app
pip install -r requirements.txt
```

2. **Set up environment variables:**

Create a `.env` file in the parent directory (`/dags/`) with:

```bash
# Backend API Configuration
BACKEND_BASE_URL=https://narrativeshf-narrativesbackend.hf.space
HF_TOKEN=your_huggingface_token_here

# HTTP Timeout Configuration (seconds)
METRICS_TIMEOUT=60
```

Or copy from the example:
```bash
cp ../.env.example ../.env
# Then edit .env with your actual values
```

## Running the Application

From the `st_app/` directory:

```bash
streamlit run app.py
```

Or from the parent directory:

```bash
streamlit run st_app/app.py
```

The application will open in your default web browser at `http://localhost:8501`.

## Features

### Global Controls
- **Date Selector**: Choose the date for viewing metrics (defaults to latest available)
- **Time Range**: Select lookback period: 30d / 90d / 180d / 365d / Custom
- **Narrative Group**: Filter by All / Core / Supplementary narratives
- **Search Box**: Filter narratives by name
- **Narrative Selector**: Multi-select to choose which narratives to analyze
- **Run Analysis Button**: Trigger data fetching and metric calculation
- **Stop Button**: Interrupt running analysis
- **Reload Button**: Reset analysis and start fresh

### Main Interactive Table
Sortable table displaying key metrics:
- **Narrative**: Name of the macro narrative
- **Intensity Z**: Z-score vs trailing 60-day baseline
- **Intensity %ile**: Rolling 1-year percentile (0-100%)
- **Sentiment**: Mean sentiment score (-1 to +1)
- **Sentiment %ile**: Rolling 1-year percentile (0-100%)
- **Horizon Moves (1d, 2d, 5d, 10d, 20d)**: Intensity deltas (z_today - z_(t-h))
- **Alert Indicators**: 🚨 shown when |move| > 1.0

### Narrative Detail View
- **Quick Stats**: Intensity Z, Intensity Percentile, Sentiment, Sentiment Percentile
- **Horizon Moves**: 1d, 2d, 5d, 10d, 20d moves with alert indicators
- **Time Series Charts**: 
  - Intensity Z-Score over time with percentile overlay
  - Sentiment over time with percentile overlay
- **Interactive Plotly Charts**: Zoom, pan, hover tooltips

### Today's Alerts
- Shows narratives where absolute horizon moves exceed 1.0 standard deviation
- Grouped by narrative with all breaching horizons displayed

## Performance & Reliability

### Caching Strategy
- **5-minute TTL cache** on API calls to reduce backend load
- Manual cache clear available via "Reload" button

### Error Handling
- **Graceful degradation**: App continues if individual narratives fail to load
- **Timeout protection**: Configurable timeout (default 60s, scales with date range)
- **Retry logic**: Automatic retries with exponential backoff for transient failures
- **Request throttling**: 500ms delay between requests to avoid overwhelming backend

### Progress Feedback
- **Real-time progress bar** during multi-narrative analysis
- Shows which narrative is currently loading
- Updates incrementally as each narrative completes

## Deployment

### Streamlit Cloud

1. Push code to GitHub repository
2. Go to https://share.streamlit.io/
3. Sign in with GitHub
4. Click "New app"
5. Configure:
   - Repository: `YOUR_USERNAME/REPO_NAME`
   - Branch: `main`
   - Main file path: `st_app/app.py`
6. Set environment variables in Streamlit Cloud Secrets:
   ```
   BACKEND_BASE_URL = "https://narrativeshf-narrativesbackend.hf.space"
   HF_TOKEN = "your_token_here"
   METRICS_TIMEOUT = "60"
   ```

## Architecture

```
st_app/
├── app.py              # Main Streamlit application
├── api_client.py       # Backend API client with retry logic
├── utils.py            # Helper functions (calculations, formatting)
├── requirements.txt    # Python dependencies
└── README.md          # This file
```

### Component Overview

**`app.py`**: Main Streamlit application
- Global controls and UI
- Interactive metrics table
- Narrative detail view with charts
- Alerts summary

**`api_client.py`**: Data layer
- `get_narrative_metrics()`: Fetches metrics from backend API with caching
- `get_available_narratives()`: Returns predefined SUPPORTED_NARRATIVES taxonomy
- `get_available_dates()`: Returns hardcoded date range (2024-09-01 to 2026-01-14)
- Handles authentication, timeouts, retries, and error recovery

**`utils.py`**: Calculation helpers
- `calculate_horizon_moves()`: Computes z_today - z_(t-h) for horizons [1,2,5,10,20]
- `detect_alerts()`: Identifies moves exceeding threshold (default 1.0σ)
- `format_metric()`: Formats numeric values for display
- `get_date_range_for_period()`: Converts period strings to date ranges

## Troubleshooting

### Backend timeout errors
**Symptom**: `Read timed out` or `Remote end closed connection` errors

**Solutions**:
- Try a **shorter time range** (30d or 90d instead of 365d)
- Analyze **fewer narratives** at once
- Increase `METRICS_TIMEOUT` in `.env` (default: 60 seconds)
- Wait a moment and retry — backend may be cold-starting or under load

### No data available
**Symptom**: "No data available for the selected date range"

**Solutions**:
- Backend may not have computed metrics for that date yet
- Try selecting a more recent date (defaults to latest available: 2026-01-14)
- Check if backend API is accessible

### Import errors
**Symptom**: Module not found errors

**Solutions**:
- Ensure all dependencies are installed: `pip install -r requirements.txt`
- Check Python version (3.9+ required)
- Verify file structure matches the repository

## License

Internal use only.


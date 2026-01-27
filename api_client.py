"""
API Client for Narrative Tracker MVP
Handles backend API calls for macro narrative tracking.

Backend Integration:
- Fetches narrative metrics (intensity, sentiment, percentiles) from HTTP API
  GET /narratives/{narrative}/metrics (window, percentile_window, start_date, end_date)
- Narrative IDs must match primary_label_v2 in the backend database
- Handles authentication (HF_TOKEN) and error recovery
"""

import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib.parse import quote
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta
from pathlib import Path
import streamlit as st
from dotenv import load_dotenv

# Load environment variables from .env file in parent directory
env_path = Path(__file__).parent.parent / '.env'
if env_path.exists():
    load_dotenv(dotenv_path=env_path)

# Backend API configuration
BACKEND_BASE_URL = os.environ.get(
    "BACKEND_BASE_URL", 
    "https://narrativeshf-narrativesbackend.hf.space"
)
HF_TOKEN = os.environ.get("HF_TOKEN")

# HTTP timeout for backend requests (seconds), configurable via env
METRICS_TIMEOUT = int(os.environ.get("METRICS_TIMEOUT", "60"))

# Retry strategy for API requests
retry_strategy = Retry(
    total=3,  # Maximum 3 retries
    backoff_factor=1,  # Exponential backoff: 1s, 2s, 4s
    status_forcelist=[429, 500, 502, 503, 504],  # Retry on these status codes
    allowed_methods=["GET"],  # Only retry GET requests
    raise_on_status=False  # Don't raise exception on retry exhaustion
)

# Create HTTP adapter with retry strategy
adapter = HTTPAdapter(max_retries=retry_strategy)

# Create session with retry adapter
_http_session = requests.Session()
_http_session.mount("https://", adapter)
_http_session.mount("http://", adapter)

# ==============================================================================
# NARRATIVE TAXONOMY
# ==============================================================================
# Predefined narratives that the backend API supports (aligned with topic_classifier.py)
# 
# Structure:
# - id: Backend identifier (matches primary_label_v2 in database)
# - label: User-facing display name
# - group: "Core" or "Supplementary"
#
# Core Narratives (5): Primary macro themes for tracking
# Supplementary Narratives (6): Additional macro themes
# ==============================================================================

SUPPORTED_NARRATIVES: List[Dict[str, str]] = [
    # ========== CORE NARRATIVES ==========
    # Growth steady, inflation cooling, risk-on/soft landing narrative
    {"id": "Goldilocks economy", "label": "Goldilocks Economy", "group": "Core"},
    
    # Sharp, broad selloffs; crisis/contagion; systemic stress
    {"id": "Market crash", "label": "Market Crash", "group": "Core"},
    
    # Prices rising/sticky; cost-of-living; CPI/PCE; inflation expectations
    {"id": "Inflation", "label": "Inflation", "group": "Core"},
    
    # Weakening macro: GDP slowing, recession risk, weak demand, falling output
    {"id": "Growth slowdown", "label": "US Growth Slowdown", "group": "Core"},
    
    # High inflation PLUS weak/contracting growth together
    {"id": "Stagflation", "label": "Stagflation", "group": "Core"},
    
    # ========== SUPPLEMENTARY NARRATIVES ==========
    # Job cuts/restructurings/downsizing announcements
    {"id": "Worker layoffs", "label": "Worker Layoffs", "group": "Supplementary"},
    
    # Hiring/jobs/wages/participation/unemployment trends
    {"id": "Labor market", "label": "Labor Market", "group": "Supplementary"},
    
    # State-level military conflict or major geopolitical escalation
    {"id": "International conflict", "label": "International Conflict", "group": "Supplementary"},
    
    # Tariffs, export controls, sanctions, retaliatory trade measures
    {"id": "Trade war", "label": "Trade War", "group": "Supplementary"},
    
    # Government deficits/debt/debt ceiling/sovereign downgrade
    {"id": "Fiscal sustainability", "label": "Fiscal Sustainability", "group": "Supplementary"},
    
    # DISABLED: "Markets/Rate-watch" contains "/" – URL path /narratives/{narrative}/metrics
    # routes fail (404) when narrative has a slash. Re-enable when backend supports it
    # (e.g. narrative as query param or path:path).
    # {"id": "Markets/Rate-watch", "label": "Markets / Rate-Watch", "group": "Supplementary"},
]


@st.cache_data(ttl=300)  # 5 minute cache
def get_narrative_metrics(
    narrative: str,
    start_date: str,
    end_date: str,
    window: int = 60,
    percentile_window: int = 365,
) -> List[Dict[str, Any]]:
    """
    Fetch narrative metrics from backend API.
    
    Args:
        narrative: Narrative ID (must match primary_label_v2, e.g. "Worker layoffs")
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        window: Rolling window for intensity baseline (default 60); backend 1–365.
        percentile_window: Trailing window for percentile ranks (default 365); backend 1–730.
        
    Returns:
        List of daily metrics with keys:
        date, article_count, rolling_mean, rolling_std, intensity (z-score),
        sentiment_mean, intensity_percentile, sentiment_percentile.
    """
    encoded_narrative = quote(narrative, safe="")
    url = f"{BACKEND_BASE_URL}/narratives/{encoded_narrative}/metrics"
    
    params = {
        "window": window,
        "percentile_window": percentile_window,
        "start_date": start_date,
        "end_date": end_date
    }
    
    headers = {}
    if HF_TOKEN:
        headers["Authorization"] = f"Bearer {HF_TOKEN}"
    
    # Calculate dynamic timeout based on date range
    # Longer date ranges need more time for backend processing
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        days = (end_dt - start_dt).days
        # Base timeout + 0.5s per day, capped at 120s
        dynamic_timeout = min(120, METRICS_TIMEOUT + (days * 0.5))
    except (ValueError, TypeError):
        # Fallback to default if date parsing fails
        dynamic_timeout = METRICS_TIMEOUT
    
    try:
        # Use session with retry logic instead of direct requests.get
        response = _http_session.get(
            url,
            params=params,
            headers=headers,
            timeout=dynamic_timeout,
        )
        response.raise_for_status()
        data = response.json()
        
        # Ensure data is a list
        if isinstance(data, dict):
            # If backend returns a dict with a 'data' key
            data = data.get("data", [data])
        elif not isinstance(data, list):
            data = [data]
            
        return data
    except requests.exceptions.Timeout:
        # Handle read / connect timeouts explicitly with a concise message
        st.warning(
            f"Backend timeout while fetching metrics for '{narrative}'. "
            "Try a shorter time range or fewer narratives, or retry in a moment."
        )
        return []
    except requests.exceptions.HTTPError as e:
        # Parse response body when available (e.g. FastAPI {"detail": "..."})
        detail = ""
        if e.response is not None:
            try:
                body = e.response.json()
                detail = body.get("detail", body) if isinstance(body, dict) else str(body)
            except Exception:
                detail = (e.response.text or "")[:500]
            if detail and not isinstance(detail, str):
                detail = str(detail)
        msg = f"Error fetching metrics for '{narrative}': {e.response.status_code}"
        if detail:
            msg += f" — {detail}"
        if e.response is not None and e.response.status_code >= 500:
            msg += (
                " Backend server error; may be temporary or data-specific. "
                "Try a shorter range, fewer narratives, or retry later."
            )
        elif e.response is not None and e.response.status_code == 404:
            msg += " Narrative not found (404). It may be missing in the backend."
        st.error(msg)
        return []
    except requests.exceptions.RequestException as e:
        st.error(f"Error fetching metrics for {narrative}: {e}")
        return []


def get_available_narratives() -> List[Dict[str, str]]:
    """
    Get list of available narratives that are supported by the backend API.
    Returns predefined list of narratives from SUPPORTED_NARRATIVES.
    
    Returns:
        List of dicts with keys: id (backend key), label (UI name), group ("Core"/"Supplementary")
    """
    return SUPPORTED_NARRATIVES


@st.cache_data(ttl=300)
def get_available_dates() -> Dict[str, Optional[datetime]]:
    """
    Get hardcoded min and max available dates.
    
    Returns:
        Dictionary with 'min_date' and 'max_date' keys (datetime objects)
    """
    return {
        "min_date": datetime(2024, 9, 1),
        "max_date": datetime(2026, 1, 14)
    }




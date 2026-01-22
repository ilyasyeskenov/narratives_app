"""
Utility functions for Narrative Tracker
Helper functions for calculations, formatting, and data processing.
"""

from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import pandas as pd


def calculate_horizon_moves(
    metrics_df: pd.DataFrame,
    target_date: str,
    horizons: List[int] = [1, 2, 5, 10, 20]
) -> Dict[int, Optional[float]]:
    """
    Calculate intensity z-score moves across different time horizons.
    
    Args:
        metrics_df: DataFrame with columns ['date', 'intensity']
        target_date: Target date in YYYY-MM-DD format
        horizons: List of horizon days (e.g., [1, 2, 5, 10, 20])
        
    Returns:
        Dictionary mapping horizon (int) to move (float or None if data unavailable)
    """
    moves = {}
    
    # Ensure date column is datetime
    if 'date' in metrics_df.columns:
        metrics_df = metrics_df.copy()
        metrics_df['date'] = pd.to_datetime(metrics_df['date'])
    
    # Get target date intensity
    target_dt = pd.to_datetime(target_date)
    target_row = metrics_df[metrics_df['date'] == target_dt]
    
    if target_row.empty:
        return {h: None for h in horizons}
    
    target_intensity = target_row['intensity'].iloc[0]
    
    # Calculate moves for each horizon
    for horizon in horizons:
        horizon_date = target_dt - timedelta(days=horizon)
        horizon_row = metrics_df[metrics_df['date'] == horizon_date]
        
        if horizon_row.empty:
            moves[horizon] = None
        else:
            horizon_intensity = horizon_row['intensity'].iloc[0]
            move = target_intensity - horizon_intensity
            moves[horizon] = move
    
    return moves


def detect_alerts(
    moves_dict: Dict[int, Optional[float]],
    threshold: float = 1.0
) -> List[Dict[str, Any]]:
    """
    Detect alerts where absolute move exceeds threshold.
    
    Args:
        moves_dict: Dictionary mapping horizon to move value
        threshold: Alert threshold (default 1.0)
        
    Returns:
        List of alert dictionaries with keys: horizon, move, abs_move
    """
    alerts = []
    for horizon, move in moves_dict.items():
        if move is not None and abs(move) > threshold:
            alerts.append({
                "horizon": horizon,
                "move": move,
                "abs_move": abs(move)
            })
    return alerts


def format_metric(value: Optional[float], decimals: int = 2) -> str:
    """
    Format a metric value with specified decimal places.
    
    Args:
        value: Numeric value (or None)
        decimals: Number of decimal places
        
    Returns:
        Formatted string (or "N/A" if None)
    """
    if value is None:
        return "N/A"
    return f"{value:.{decimals}f}"


def get_latest_date(dates_list: List[str]) -> Optional[str]:
    """
    Get the latest date from a list of date strings.
    
    Args:
        dates_list: List of date strings in YYYY-MM-DD format
        
    Returns:
        Latest date string or None if list is empty
    """
    if not dates_list:
        return None
    
    try:
        date_objects = [datetime.strptime(d, "%Y-%m-%d") for d in dates_list]
        latest = max(date_objects)
        return latest.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        # If parsing fails, try to sort as strings
        return sorted(dates_list, reverse=True)[0] if dates_list else None


def get_date_range_days(start_date: str, end_date: str) -> int:
    """
    Calculate number of days between two dates.
    
    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        
    Returns:
        Number of days (int)
    """
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        return (end - start).days
    except (ValueError, TypeError):
        return 0


def get_date_range_for_period(period: str, end_date: Optional[str] = None) -> tuple:
    """
    Get start and end dates for a time period.
    
    Args:
        period: One of "30d", "90d", "180d", "365d", "custom"
        end_date: End date (defaults to today if None)
        
    Returns:
        Tuple of (start_date, end_date) as strings in YYYY-MM-DD format
    """
    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")
    
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    
    if period == "30d":
        start_dt = end_dt - timedelta(days=30)
    elif period == "90d":
        start_dt = end_dt - timedelta(days=90)
    elif period == "180d":
        start_dt = end_dt - timedelta(days=180)
    elif period == "365d":
        start_dt = end_dt - timedelta(days=365)
    else:  # custom or default
        start_dt = end_dt - timedelta(days=180)  # Default to 180d
    
    return start_dt.strftime("%Y-%m-%d"), end_date


def color_intensity(value: float) -> str:
    """
    Get color for intensity z-score value.
    
    Args:
        value: Intensity z-score
        
    Returns:
        Color name for Streamlit styling
    """
    if value < -0.5:
        return "red"
    elif value > 0.5:
        return "green"
    else:
        return "gray"


def color_sentiment(value: float) -> str:
    """
    Get color for sentiment value.
    
    Args:
        value: Sentiment score (-1 to 1)
        
    Returns:
        Color name for Streamlit styling
    """
    if value < -0.3:
        return "red"
    elif value > 0.3:
        return "green"
    else:
        return "gray"


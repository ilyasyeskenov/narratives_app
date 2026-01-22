"""
Dashboard Page - Main narrative overview table
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api_client import get_narrative_metrics, get_available_narratives
from utils import (
    calculate_horizon_moves,
    detect_alerts,
    format_metric,
    get_date_range_for_period,
    color_intensity,
    color_sentiment
)


def render():
    """Render the dashboard page."""
    st.title("📊 Narrative Dashboard")
    
    # Get available narratives
    narratives = get_available_narratives()
    
    if not narratives:
        st.warning("No narratives found. Please check your connection.")
        return
    
    # --- Global controls (top) ---
    st.markdown("### Global Controls")
    
    # Define narrative groups based on taxonomy
    core_narratives = [
        "Goldilocks economy",
        "Market crash",
        "Inflation",
        "Growth slowdown",
        "Stagflation",
    ]
    supplementary_narratives = [
        "Worker layoffs",
        "Labor market",
        "International conflict",
        "Trade war",
        "Fiscal sustainability",
        "Markets/Rate-watch",
    ]
    
    col1, col2, col3 = st.columns([2, 2, 2])
    
    with col1:
        # Date selector (default to latest available, managed in app.py)
        selected_date = st.date_input(
            "Selected Date",
            value=datetime.strptime(st.session_state.selected_date, "%Y-%m-%d").date()
            if st.session_state.selected_date
            else datetime.now().date(),
            key="dashboard_date",
        )
        st.session_state.selected_date = selected_date.strftime("%Y-%m-%d")
    
    with col2:
        # Time range selector including Custom
        time_range = st.selectbox(
            "Time Range",
            ["30d", "90d", "180d", "365d", "Custom"],
            index=2,  # Default to 180d
        )
        
        custom_start_date = None
        if time_range == "Custom":
            custom_start_date = st.date_input(
                "Custom Start Date",
                value=selected_date - timedelta(days=180),
                key="dashboard_custom_start",
            )
    
    with col3:
        # Narrative group filter + search
        group = st.radio(
            "Narrative Group",
            ["All", "Core", "Supplementary"],
            horizontal=True,
        )
        search_query = st.text_input("Search narratives", "")
    
    # Apply group filter
    if group == "Core":
        base_narratives = [n for n in narratives if n in core_narratives]
    elif group == "Supplementary":
        base_narratives = [n for n in narratives if n in supplementary_narratives]
    else:
        base_narratives = narratives
    
    # Apply search filter
    if search_query:
        base_narratives = [
            n for n in base_narratives if search_query.lower() in n.lower()
        ]
    
    if not base_narratives:
        st.info("No narratives match the current filters.")
        return
    
    # Narrative selector (multiselect from filtered list)
    selected_narratives = st.multiselect(
        "Select Narratives",
        options=base_narratives,
        default=base_narratives,  # All filtered selected by default
        help="Choose which narratives to analyze",
        key="dashboard_narratives_multiselect",
    )
    
    # Action buttons
    col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 4])
    
    with col_btn1:
        run_analysis = st.button("📊 Run Analysis", type="primary", use_container_width=True)
    
    with col_btn2:
        if st.button("🔄 Clear Cache", use_container_width=True):
            st.cache_data.clear()
            st.success("Cache cleared!")
            st.rerun()
    
    # Check if user has selected narratives
    if not selected_narratives:
        st.info("👆 Please select at least one narrative and click 'Run Analysis' to begin.")
        return
    
    # Only run analysis if button is clicked or if analysis was already run
    if "dashboard_analysis_run" not in st.session_state:
        st.session_state.dashboard_analysis_run = False
    
    if run_analysis:
        st.session_state.dashboard_analysis_run = True
    
    if not st.session_state.dashboard_analysis_run:
        st.info("👆 Click 'Run Analysis' to load narrative metrics.")
        return
    
    # Get date range for fetching metrics
    if time_range == "Custom" and custom_start_date is not None:
        start_date = custom_start_date.strftime("%Y-%m-%d")
        end_date = st.session_state.selected_date
    else:
        start_date, end_date = get_date_range_for_period(
            time_range, st.session_state.selected_date
        )
    
    # Fetch metrics for selected narratives
    st.markdown("---")
    with st.spinner(f"Loading metrics for {len(selected_narratives)} narratives..."):
        filtered_narratives = selected_narratives
    
    dashboard_data = []
    all_alerts = []
    
    for narrative in filtered_narratives:
        try:
            # Fetch metrics
            metrics = get_narrative_metrics(
                narrative=narrative,
                start_date=start_date,
                end_date=end_date,
                window=60,
                percentile_window=90
            )
            
            if not metrics:
                continue
            
            # Convert to DataFrame
            df = pd.DataFrame(metrics)
            if df.empty:
                continue
            
            # Get metrics for selected date
            selected_date_str = st.session_state.selected_date
            date_row = df[df['date'] == selected_date_str]
            
            if date_row.empty:
                # Try to get latest available date
                date_row = df.iloc[-1:]
                if date_row.empty:
                    continue
            
            row = date_row.iloc[0]
            
            # Calculate horizon moves
            moves = calculate_horizon_moves(df, selected_date_str, horizons=[1, 2, 5, 10, 20])
            
            # Detect alerts
            alerts = detect_alerts(moves, threshold=1.0)
            if alerts:
                for alert in alerts:
                    all_alerts.append({
                        "narrative": narrative,
                        "horizon": alert["horizon"],
                        "move": alert["move"]
                    })
            
            # Build dashboard row
            # Percentiles are already 0-1, convert to percentage for display
            intensity_pct = row.get('intensity_percentile', 0) * 100 if row.get('intensity_percentile') is not None else 0
            sentiment_pct = row.get('sentiment_percentile', 0) * 100 if row.get('sentiment_percentile') is not None else 0
            
            dashboard_data.append({
                "Narrative": narrative,
                "Intensity Z": row.get('intensity', 0),
                "Intensity %ile": intensity_pct,
                "Sentiment": row.get('sentiment_mean', 0),
                "Sentiment %ile": sentiment_pct,
                "1d Move": moves.get(1),
                "2d Move": moves.get(2),
                "5d Move": moves.get(5),
                "10d Move": moves.get(10),
                "20d Move": moves.get(20),
                "Article Count": row.get('article_count', 0),
                "_narrative": narrative  # Hidden column for navigation
            })
        except Exception as e:
            st.warning(f"Error loading {narrative}: {e}")
            continue
    
    if not dashboard_data:
        st.warning("No data available for the selected date range.")
        return
    
    # Create DataFrame
    df_dashboard = pd.DataFrame(dashboard_data)
    
    # Display main table
    st.markdown("### Narrative Metrics")
    
    # Configure column display
    column_config = {
        "Narrative": st.column_config.TextColumn("Narrative", width="medium"),
        "Intensity Z": st.column_config.NumberColumn(
            "Intensity Z",
            format="%.2f",
            width="small"
        ),
        "Intensity %ile": st.column_config.NumberColumn(
            "Intensity %ile",
            format="%.1f",
            width="small"
        ),
        "Sentiment": st.column_config.NumberColumn(
            "Sentiment",
            format="%.3f",
            width="small"
        ),
        "Sentiment %ile": st.column_config.NumberColumn(
            "Sentiment %ile",
            format="%.1f",
            width="small"
        ),
        "1d Move": st.column_config.NumberColumn("1d", format="%.2f", width="small"),
        "2d Move": st.column_config.NumberColumn("2d", format="%.2f", width="small"),
        "5d Move": st.column_config.NumberColumn("5d", format="%.2f", width="small"),
        "10d Move": st.column_config.NumberColumn("10d", format="%.2f", width="small"),
        "20d Move": st.column_config.NumberColumn("20d", format="%.2f", width="small"),
        "Article Count": st.column_config.NumberColumn("Articles", width="small"),
        "_narrative": None  # Hide this column
    }
    
    # Display table
    st.dataframe(
        df_dashboard,
        column_config=column_config,
        use_container_width=True,
        hide_index=True
    )
    
    # Row selection using selectbox
    st.markdown("### Select Narrative to View Details")
    narrative_options = ["-- Select a narrative --"] + list(df_dashboard["Narrative"].values)
    selected_narrative_name = st.selectbox(
        "Choose narrative:",
        narrative_options,
        key="dashboard_narrative_select"
    )
    
    if selected_narrative_name != "-- Select a narrative --":
        selected_narrative = df_dashboard[df_dashboard["Narrative"] == selected_narrative_name]["_narrative"].iloc[0]
        if st.button("View Details", use_container_width=True):
            st.session_state.selected_narrative = selected_narrative
            st.session_state.selected_page = "Narrative Detail"
            st.rerun()
    
    # Alerts summary
    st.markdown("---")
    st.markdown("### 🚨 Today's Alerts")
    
    if all_alerts:
        # Group by narrative
        alert_summary = {}
        for alert in all_alerts:
            if alert['narrative'] not in alert_summary:
                alert_summary[alert['narrative']] = []
            alert_summary[alert['narrative']].append(f"{alert['horizon']}d: {alert['move']:+.2f}")
        
        # Display in columns
        num_cols = min(3, len(alert_summary))
        cols = st.columns(num_cols) if num_cols > 0 else [st]
        
        for idx, (narrative, moves) in enumerate(sorted(alert_summary.items())):
            with cols[idx % num_cols]:
                with st.container():
                    st.markdown(f"**{narrative}**")
                    for move in moves:
                        st.caption(move)
                    if st.button(f"View Details", key=f"alert_detail_{narrative}"):
                        st.session_state.selected_narrative = narrative
                        st.session_state.selected_page = "Narrative Detail"
                        st.rerun()
    else:
        st.info("No alerts detected for the selected date and narratives.")


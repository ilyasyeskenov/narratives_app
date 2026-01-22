"""
Alerts Page - View and filter narrative alerts
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api_client import get_narrative_metrics, get_available_narratives
from utils import calculate_horizon_moves, detect_alerts


def render():
    """Render the alerts page."""
    st.title("🚨 Narrative Alerts")
    
    st.markdown("### Alert Parameters")
    
    # Controls
    col1, col2 = st.columns(2)
    
    with col1:
        # Date range selector
        default_end = datetime.now().date()
        default_start = (datetime.now() - timedelta(days=14)).date()
        
        date_range = st.date_input(
            "Date Range",
            value=(default_start, default_end),
            key="alerts_date_range"
        )
        
        if isinstance(date_range, tuple) and len(date_range) == 2:
            start_date = date_range[0]
            end_date = date_range[1]
        elif isinstance(date_range, tuple) and len(date_range) == 1:
            # User selected only one date
            start_date = date_range[0]
            end_date = date_range[0]
        else:
            # Single date object
            start_date = date_range if date_range else default_start
            end_date = start_date
        
        # Threshold slider
        threshold = st.slider(
            "Alert Threshold (Standard Deviations)",
            min_value=0.5,
            max_value=3.0,
            value=1.0,
            step=0.1,
            help="Absolute move threshold for alerts"
        )
    
    with col2:
        # Get all narratives
        all_narratives = get_available_narratives()
        
        if not all_narratives:
            st.warning("No narratives found.")
            return
        
        # Narrative selector
        selected_narratives = st.multiselect(
            "Select Narratives to Monitor",
            options=all_narratives,
            default=all_narratives,
            help="Choose which narratives to scan for alerts"
        )
        
        # Horizon multiselect
        available_horizons = [1, 2, 5, 10, 20]
        selected_horizons = st.multiselect(
            "Time Horizons (days)",
            available_horizons,
            default=available_horizons,
            help="Select time horizons to monitor"
        )
    
    # Action button
    col_btn1, col_btn2 = st.columns([1, 5])
    with col_btn1:
        run_scan = st.button("🔍 Scan for Alerts", type="primary", use_container_width=True)
    
    # Validation
    if not selected_horizons:
        st.warning("⚠️ Please select at least one time horizon.")
        return
    
    if not selected_narratives:
        st.info("👆 Please select at least one narrative and click 'Scan for Alerts' to begin.")
        return
    
    # Only run scan if button is clicked or if scan was already run
    if "alerts_scan_run" not in st.session_state:
        st.session_state.alerts_scan_run = False
    
    if run_scan:
        st.session_state.alerts_scan_run = True
    
    if not st.session_state.alerts_scan_run:
        st.info("👆 Click 'Scan for Alerts' to begin analysis.")
        return
    
    # Fetch alerts
    st.markdown("---")
    narratives = selected_narratives
    
    alerts_data = []
    
    # Generate date range
    current_date = start_date
    date_list = []
    while current_date <= end_date:
        date_list.append(current_date)
        current_date += timedelta(days=1)
    
    # For each date and narrative, check for alerts
    progress_bar = st.progress(0)
    total_checks = len(date_list) * len(narratives)
    current_check = 0
    
    for date in date_list:
        date_str = date.strftime("%Y-%m-%d")
        
        # Get date range for metrics (need enough history for horizon moves)
        metrics_start = (date - timedelta(days=30)).strftime("%Y-%m-%d")
        metrics_end = date_str
        
        for narrative in narratives:
            try:
                # Fetch metrics
                metrics = get_narrative_metrics(
                    narrative=narrative,
                    start_date=metrics_start,
                    end_date=metrics_end,
                    window=60,
                    percentile_window=90
                )
                
                if not metrics:
                    current_check += 1
                    progress_bar.progress(current_check / total_checks)
                    continue
                
                # Convert to DataFrame
                df = pd.DataFrame(metrics)
                if df.empty:
                    current_check += 1
                    progress_bar.progress(current_check / total_checks)
                    continue
                
                # Calculate horizon moves
                moves = calculate_horizon_moves(df, date_str, horizons=selected_horizons)
                
                # Detect alerts for selected horizons
                for horizon in selected_horizons:
                    move = moves.get(horizon)
                    if move is not None and abs(move) > threshold:
                        # Get current metrics
                        date_row = df[df['date'] == date_str]
                        if not date_row.empty:
                            row = date_row.iloc[0]
                            alerts_data.append({
                                "date": date_str,
                                "narrative": narrative,
                                "horizon": f"{horizon}d",
                                "move": move,
                                "abs_move": abs(move),
                                "intensity_z": row.get('intensity', 0),
                                "sentiment": row.get('sentiment_mean', 0),
                                "article_count": row.get('article_count', 0)
                            })
                
                current_check += 1
                progress_bar.progress(current_check / total_checks)
                
            except Exception as e:
                st.warning(f"Error processing {narrative} on {date_str}: {e}")
                current_check += 1
                progress_bar.progress(current_check / total_checks)
                continue
    
    progress_bar.empty()
    
    # Display alerts table
    if not alerts_data:
        st.success(f"No alerts found for the selected criteria (threshold: {threshold}, horizons: {selected_horizons}).")
        return
    
    df_alerts = pd.DataFrame(alerts_data)
    
    # Sort by date (desc) and abs_move (desc)
    df_alerts = df_alerts.sort_values(['date', 'abs_move'], ascending=[False, False])
    
    st.markdown(f"### Found {len(df_alerts)} Alerts")
    
    # Configure column display
    column_config = {
        "date": st.column_config.DateColumn("Date", width="small"),
        "narrative": st.column_config.TextColumn("Narrative", width="medium"),
        "horizon": st.column_config.TextColumn("Horizon", width="small"),
        "move": st.column_config.NumberColumn("Move", format="%.2f", width="small"),
        "abs_move": st.column_config.NumberColumn("|Move|", format="%.2f", width="small"),
        "intensity_z": st.column_config.NumberColumn("Intensity Z", format="%.2f", width="small"),
        "sentiment": st.column_config.NumberColumn("Sentiment", format="%.3f", width="small"),
        "article_count": st.column_config.NumberColumn("Articles", width="small")
    }
    
    # Display table
    st.dataframe(
        df_alerts,
        column_config=column_config,
        use_container_width=True,
        hide_index=True
    )
    
    # Alert selection
    st.markdown("### Select Alert to View Details")
    if len(df_alerts) > 0:
        alert_options = [
            f"{row['date']} - {row['narrative']} ({row['horizon']}: {row['move']:+.2f})"
            for _, row in df_alerts.iterrows()
        ]
        selected_alert = st.selectbox(
            "Choose alert:",
            ["-- Select an alert --"] + alert_options,
            key="alerts_select"
        )
        
        if selected_alert != "-- Select an alert --":
            selected_idx = alert_options.index(selected_alert)
            selected_row = df_alerts.iloc[selected_idx]
            if st.button("View Narrative Details", use_container_width=True):
                st.session_state.selected_narrative = selected_row['narrative']
                st.session_state.selected_date = selected_row['date']
                st.session_state.selected_page = "Narrative Detail"
                st.rerun()
    
    # Summary statistics
    st.markdown("---")
    st.markdown("### Summary Statistics")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Alerts", len(df_alerts))
    
    with col2:
        avg_move = df_alerts['abs_move'].mean()
        st.metric("Avg |Move|", f"{avg_move:.2f}")
    
    with col3:
        max_move = df_alerts['abs_move'].max()
        st.metric("Max |Move|", f"{max_move:.2f}")
    
    with col4:
        unique_narratives = df_alerts['narrative'].nunique()
        st.metric("Narratives", unique_narratives)
    
    # Top narratives by alert count
    st.markdown("### Top Narratives by Alert Count")
    narrative_counts = df_alerts['narrative'].value_counts().head(10)
    st.bar_chart(narrative_counts)


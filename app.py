"""
Narrative Tracker MVP - Streamlit Frontend
Analyst-grade macro narrative tracking dashboard with intensity, sentiment, and alerts.

Purpose:
- Track daily changes in macro narratives
- Monitor Intensity (z-score vs trailing baseline)
- Monitor Sentiment (mean value in [-1, 1])
- Calculate Rolling Percentiles (1-year percentiles)
- Detect Alerts (when moves exceed threshold standard deviations)

Core Narratives: Goldilocks economy, Market crash, Inflation, US growth slowdown, Stagflation
Supplementary Narratives: Worker layoffs, Labor market, International conflict, Trade war, Fiscal sustainability, Markets/Rate-watch
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import time
import sys
import os

# Add parent directory to path to import shared modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api_client import get_narrative_metrics, get_available_narratives, get_available_dates
from utils import (
    calculate_horizon_moves,
    detect_alerts,
    format_metric,
    get_date_range_for_period,
)

# Page configuration
st.set_page_config(
    page_title="Narrative Tracker MVP",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Initialize session state
if "selected_narrative" not in st.session_state:
    st.session_state.selected_narrative = None
if "selected_date" not in st.session_state:
    st.session_state.selected_date = None
if "dashboard_analysis_run" not in st.session_state:
    st.session_state.dashboard_analysis_run = False
if "analysis_stopped" not in st.session_state:
    st.session_state.analysis_stopped = False
if "dashboard_data_cached" not in st.session_state:
    st.session_state.dashboard_data_cached = []
if "all_alerts_cached" not in st.session_state:
    st.session_state.all_alerts_cached = []

# Set default selected date from backend
if st.session_state.selected_date is None:
    available_dates = get_available_dates()
    if available_dates["max_date"]:
        st.session_state.selected_date = available_dates["max_date"].strftime("%Y-%m-%d")
    else:
        st.session_state.selected_date = datetime.now().strftime("%Y-%m-%d")

# ============================================================================
# SIDEBAR
# ============================================================================
st.sidebar.title("📊 Narrative Tracker MVP")
st.sidebar.markdown("### About")
st.sidebar.info(
    "**Narrative Tracker** monitors macro narratives with:\n\n"
    "• **Intensity**: Z-score vs trailing baseline\n"
    "• **Sentiment**: Mean value [-1, 1]\n"
    "• **Percentiles**: Rolling 1-year percentiles\n"
    "• **Alerts**: Moves exceeding thresholds"
)
st.sidebar.markdown("---")
st.sidebar.markdown("**Core Narratives:**")
st.sidebar.caption("Goldilocks Economy, Market Crash, Inflation, US Growth Slowdown, Stagflation")
st.sidebar.markdown("**Supplementary Narratives:**")
st.sidebar.caption("Worker Layoffs, Labor Market, International Conflict, Trade War, Fiscal Sustainability, Markets/Rate-Watch")

# ============================================================================
# MAIN DASHBOARD
# ============================================================================
st.title("📊 Narrative Dashboard")
st.markdown("**Daily Macro Narrative Tracking** — Intensity, Sentiment & Alerts")
st.markdown("---")

# Get available narratives (metadata: id, label, group)
narratives_meta = get_available_narratives()

if not narratives_meta:
    st.warning("No narratives found. Please check your connection.")
    st.stop()

# Helper mappings between backend IDs and display labels
id_to_label = {n["id"]: n["label"] for n in narratives_meta}
label_to_id = {n["label"]: n["id"] for n in narratives_meta}

# ============================================================================
# GLOBAL CONTROLS
# ============================================================================
st.markdown("## 🎛️ Global Controls")

# First row: Date, Time Range, Group Filter
col1, col2, col3 = st.columns([2, 2, 2])

with col1:
    # Date selector (defaults to latest available date)
    selected_date = st.date_input(
        "📅 Selected Date",
        value=datetime.strptime(st.session_state.selected_date, "%Y-%m-%d").date()
        if st.session_state.selected_date
        else datetime.now().date(),
        key="dashboard_date",
        help="Select the date for viewing narrative metrics"
    )
    st.session_state.selected_date = selected_date.strftime("%Y-%m-%d")

with col2:
    # Time range selector: 30d/90d/180d/365d/Custom
    time_range = st.selectbox(
        "📆 Time Range",
        ["30d", "90d", "180d", "365d", "Custom"],
        index=2,  # Default to 180d
        help="Select lookback period for metrics calculation"
    )
    
    custom_start_date = None
    if time_range == "Custom":
        custom_start_date = st.date_input(
            "Custom Start Date",
            value=selected_date - timedelta(days=180),
            key="custom_start",
        )

with col3:
    # Narrative group filter: All/Core/Supplementary
    group_filter = st.radio(
        "🏷️ Narrative Group",
        ["All", "Core", "Supplementary"],
        horizontal=True,
        index=0,
        help="Filter narratives by category"
    )
    
    # Filter narratives by group (operate on metadata)
    if group_filter == "Core":
        filtered_by_group = [n for n in narratives_meta if n["group"] == "Core"]
    elif group_filter == "Supplementary":
        filtered_by_group = [
            n for n in narratives_meta if n["group"] == "Supplementary"
        ]
    else:
        filtered_by_group = narratives_meta

# Second row: Search box for narrative filtering
search_query = st.text_input(
    "🔍 Search Narratives", 
    "", 
    key="search_narratives",
    help="Filter narratives by name"
)

# Filter narratives by search
if search_query:
    filtered_narratives_meta = [
        n for n in filtered_by_group if search_query.lower() in n["label"].lower()
    ]
else:
    filtered_narratives_meta = filtered_by_group

if not filtered_narratives_meta:
    st.info(f"No narratives match '{search_query}'")
    st.stop()

# Third row: Narrative multiselect
available_labels = [n["label"] for n in filtered_narratives_meta]
selected_labels = st.multiselect(
    "📋 Select Narratives to Analyze",
    options=available_labels,
    default=available_labels,
    help="Choose which narratives to analyze. Multiple selections allowed.",
)

# Map selected labels back to backend narrative IDs
selected_narratives = [label_to_id[label] for label in selected_labels]

# Action buttons row
st.markdown("---")
col_btn1, col_btn2, col_btn3, col_btn4 = st.columns([1.5, 1.5, 1.5, 3.5])

with col_btn1:
    run_analysis = st.button(
        "📊 Run Analysis", 
        type="primary", 
        use_container_width=True,
        help="Fetch and display narrative metrics"
    )

with col_btn2:
    # Stop button - only show when analysis is running
    if st.session_state.dashboard_analysis_run and not st.session_state.analysis_stopped:
        if st.button(
            "⏹️ Stop", 
            use_container_width=True,
            help="Stop the current analysis (you can change parameters and run again)",
            type="secondary"
        ):
            # Set stop flag - loop will check this and break naturally
            st.session_state.analysis_stopped = True
            st.rerun()
    else:
        # Placeholder to maintain layout
        st.empty()

with col_btn3:
    if st.button(
        "🔄 Reload", 
        use_container_width=True,
        help="Reset analysis and start fresh (clears current results)"
    ):
        # Reset analysis state
        st.session_state.dashboard_analysis_run = False
        st.session_state.analysis_stopped = False
        st.session_state.dashboard_data_cached = []
        st.session_state.all_alerts_cached = []
        # Clear cache for fresh data
        st.cache_data.clear()
        st.success("✓ Analysis reset! Click 'Run Analysis' to start fresh.")
        st.rerun()

# Check if user has selected narratives
if not selected_narratives:
    st.info("👆 Please select at least one narrative and click 'Run Analysis' to begin.")
    st.stop()

# Handle Run Analysis button click
if run_analysis:
    st.session_state.dashboard_analysis_run = True
    st.session_state.analysis_stopped = False  # Reset stop flag when starting new analysis
    st.session_state.dashboard_data_cached = []  # Clear cached data for new analysis
    st.session_state.all_alerts_cached = []

# Only run analysis if button is clicked and not stopped
# But allow showing cached results if stopped
if not st.session_state.dashboard_analysis_run:
    st.info("👆 Click 'Run Analysis' to load narrative metrics.")
    st.stop()
    
# If stopped but we have cached data, we'll show it in the data fetching section
# If stopped and no cached data, show message
if st.session_state.analysis_stopped and not st.session_state.dashboard_data_cached:
    st.warning("⚠️ Analysis was stopped. Adjust parameters and click 'Run Analysis' to start again.")
    st.stop()

# ============================================================================
# DATA FETCHING & PROCESSING
# ============================================================================

# Calculate date range for metrics fetching
if time_range == "Custom" and custom_start_date:
    start_date = custom_start_date.strftime("%Y-%m-%d")
else:
    start_date, end_date = get_date_range_for_period(
        time_range, st.session_state.selected_date
    )

end_date = st.session_state.selected_date

st.markdown("---")
st.markdown("## 📈 Narrative Metrics")

# Display analysis info
st.info(
    f"**Analyzing {len(selected_narratives)} narrative(s)** "
    f"from **{start_date}** to **{end_date}** "
    f"({(datetime.strptime(end_date, '%Y-%m-%d') - datetime.strptime(start_date, '%Y-%m-%d')).days} days)"
)

# Initialize progress bar and data structures
progress = st.progress(0.0, text="Loading narrative metrics...")

# Use cached data if analysis was stopped, otherwise start fresh
if st.session_state.analysis_stopped and st.session_state.dashboard_data_cached:
    dashboard_data = st.session_state.dashboard_data_cached.copy()
    all_alerts = st.session_state.all_alerts_cached.copy()
    progress.empty()
    st.info(f"ℹ️ Showing partial results from stopped analysis ({len(dashboard_data)} narrative(s) loaded).")
else:
    dashboard_data = []
    all_alerts = []
    st.session_state.dashboard_data_cached = []
    st.session_state.all_alerts_cached = []

# Process each selected narrative
for idx, narrative_id in enumerate(selected_narratives, start=1):
    # Check if user clicked stop
    if st.session_state.analysis_stopped:
        progress.empty()
        st.warning("⚠️ Analysis stopped by user.")
        st.session_state.dashboard_analysis_run = False
        break
    
    display_name = id_to_label.get(narrative_id, narrative_id)
    progress.progress(idx / len(selected_narratives), text=f"Loading {display_name}...")
    
    # Add small delay between requests to avoid overwhelming backend
    # (except for the first request)
    if idx > 1:
        time.sleep(0.5)  # 500ms delay between requests
    
    try:
        # Fetch metrics from backend API
        metrics = get_narrative_metrics(
            narrative=narrative_id,
            start_date=start_date,
            end_date=end_date,
            window=60,  # 60-day rolling window for intensity calculation
            percentile_window=90,  # 90-day window for percentile calculation
        )
        
        if not metrics:
            continue
        
        # Convert to DataFrame for processing
        df_metrics = pd.DataFrame(metrics)
        if df_metrics.empty:
            continue
        
        # Get metrics for the selected date
        selected_date_str = st.session_state.selected_date
        date_row = df_metrics[df_metrics["date"] == selected_date_str]
        
        if date_row.empty:
            # Fallback: use latest available date if selected date not found
            date_row = df_metrics.iloc[-1:]
            if date_row.empty:
                continue
        
        # Convert pandas Series to dict for proper .get() method behavior
        row = date_row.iloc[0].to_dict()
        
        # Calculate horizon moves (1d, 2d, 5d, 10d, 20d)
        # Horizon move = intensity_today - intensity_(t-h)
        moves = calculate_horizon_moves(
            df_metrics, selected_date_str, horizons=[1, 2, 5, 10, 20]
        )
        
        # Detect alerts (threshold: absolute move > 1.0 standard deviation)
        alerts = detect_alerts(moves, threshold=1.0)
        if alerts:
            for alert in alerts:
                all_alerts.append(
                    {
                        "narrative": display_name,
                        "horizon": alert["horizon"],
                        "move": alert["move"],
                    }
                )
        
        # Convert percentiles from [0, 1] to percentage for display
        intensity_pct = (
            row.get("intensity_percentile", 0) * 100
            if row.get("intensity_percentile") is not None
            else 0
        )
        sentiment_pct = (
            row.get("sentiment_percentile", 0) * 100
            if row.get("sentiment_percentile") is not None
            else 0
        )
        
        # Append to dashboard data
        dashboard_data.append(
            {
                "Narrative": display_name,
                "Intensity Z": row.get("intensity", 0),
                "Intensity %ile": intensity_pct,
                "Sentiment": row.get("sentiment_mean", 0),
                "Sentiment %ile": sentiment_pct,
                "1d Move": moves.get(1),
                "2d Move": moves.get(2),
                "5d Move": moves.get(5),
                "10d Move": moves.get(10),
                "20d Move": moves.get(20),
                "_narrative": narrative_id,  # Hidden column storing backend ID
            }
        )
        
        # Store in session state after each narrative (for stop functionality)
        st.session_state.dashboard_data_cached = dashboard_data.copy()
        st.session_state.all_alerts_cached = all_alerts.copy()
        
    except Exception as e:
        st.warning(f"⚠️ Error loading {display_name}: {e}")
        continue

# Clear progress bar (if it exists)
if 'progress' in locals():
    progress.empty()

# ============================================================================
# MAIN INTERACTIVE TABLE
# ============================================================================

if not dashboard_data:
    st.warning("⚠️ No data available for the selected date range and narratives.")
    st.stop()

# Create dashboard DataFrame
df_dashboard = pd.DataFrame(dashboard_data)

st.success(f"✓ Successfully loaded {len(df_dashboard)} narrative(s)")
st.markdown("### 📊 Interactive Metrics Table")
st.caption(
    "**Sortable columns** • Click headers to sort • "
    "Intensity Z: z-score vs trailing baseline • Sentiment: mean [-1, 1] • "
    "Percentiles: rolling 365d • Horizon Moves: z_today - z_(t-h) • Alert if |move| > 1.0"
)

# Configure column display with enhanced formatting
column_config = {
    "Narrative": st.column_config.TextColumn(
        "Narrative", 
        width="medium",
        help="Macro narrative category"
    ),
    "Intensity Z": st.column_config.NumberColumn(
        "Intensity Z", 
        format="%.2f", 
        width="small",
        help="Intensity z-score vs trailing baseline"
    ),
    "Intensity %ile": st.column_config.NumberColumn(
        "Intensity %ile", 
        format="%.1f%%", 
        width="small",
        help="Intensity percentile (rolling 1-year)"
    ),
    "Sentiment": st.column_config.NumberColumn(
        "Sentiment", 
        format="%.3f", 
        width="small",
        help="Mean sentiment [-1, 1]"
    ),
    "Sentiment %ile": st.column_config.NumberColumn(
        "Sentiment %ile", 
        format="%.1f%%", 
        width="small",
        help="Sentiment percentile (rolling 1-year)"
    ),
    "1d Move": st.column_config.NumberColumn(
        "1d Δ", 
        format="%.2f", 
        width="small",
        help="1-day intensity move"
    ),
    "2d Move": st.column_config.NumberColumn(
        "2d Δ", 
        format="%.2f", 
        width="small",
        help="2-day intensity move"
    ),
    "5d Move": st.column_config.NumberColumn(
        "5d Δ", 
        format="%.2f", 
        width="small",
        help="5-day intensity move"
    ),
    "10d Move": st.column_config.NumberColumn(
        "10d Δ", 
        format="%.2f", 
        width="small",
        help="10-day intensity move"
    ),
    "20d Move": st.column_config.NumberColumn(
        "20d Δ", 
        format="%.2f", 
        width="small",
        help="20-day intensity move"
    ),
    "_narrative": None,  # Hide backend ID column
}

# Display interactive table
st.dataframe(
    df_dashboard,
    column_config=column_config,
    use_container_width=True,
    hide_index=True,
    height=400,
)

# ============================================================================
# NARRATIVE SELECTION
# ============================================================================
st.markdown("---")
st.markdown("### 🔎 View Narrative Details")
st.caption("Select a narrative to view detailed information (detail page coming soon)")

narrative_options = ["— Select a narrative —"] + list(df_dashboard["Narrative"].values)
selected_narrative_name = st.selectbox(
    "Choose Narrative:",
    narrative_options,
    key="dashboard_narrative_select",
    help="Select to view detailed charts and articles"
)

if selected_narrative_name != "— Select a narrative —":
    selected_narrative_id = df_dashboard[df_dashboard["Narrative"] == selected_narrative_name][
        "_narrative"
    ].iloc[0]
    st.session_state.selected_narrative = selected_narrative_id
    
    # Get data from table
    selected_row = df_dashboard[df_dashboard["Narrative"] == selected_narrative_name].iloc[0]
    
    # ========================================================================
    # NARRATIVE DETAIL HEADER
    # ========================================================================
    st.markdown("---")
    st.markdown(f"## 📈 {selected_narrative_name}")
    st.caption(f"Detailed analysis for selected date: **{st.session_state.selected_date}**")
    
    # Quick stats row 1: Core metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric(
            "Intensity Z-Score", 
            f"{selected_row['Intensity Z']:.2f}",
            help="Z-score vs trailing 60-day baseline"
        )
    with col2:
        st.metric(
            "Intensity Percentile", 
            f"{selected_row['Intensity %ile']:.1f}%",
            help="Rolling 365-day percentile"
        )
    with col3:
        st.metric(
            "Sentiment", 
            f"{selected_row['Sentiment']:.3f}",
            help="Mean sentiment score [-1, 1]"
        )
    with col4:
        st.metric(
            "Sentiment Percentile", 
            f"{selected_row['Sentiment %ile']:.1f}%",
            help="Rolling 365-day percentile"
        )
    
    # Quick stats row 2: Horizon moves with alert indicators
    st.markdown("##### Horizon Moves (z_today - z_(t-h))")
    col1, col2, col3, col4, col5 = st.columns(5)
    
    moves_dict = {
        "1d": selected_row['1d Move'],
        "2d": selected_row['2d Move'],
        "5d": selected_row['5d Move'],
        "10d": selected_row['10d Move'],
        "20d": selected_row['20d Move'],
    }
    
    for idx, (col, (horizon, move)) in enumerate(zip([col1, col2, col3, col4, col5], moves_dict.items())):
        with col:
            if move is not None:
                # Check if this is an alert (|move| > 1.0)
                is_alert = abs(move) > 1.0
                alert_indicator = " 🚨" if is_alert else ""
                
                st.metric(
                    f"{horizon} Move{alert_indicator}", 
                    f"{move:+.2f}σ",
                    help=f"{horizon} intensity change" + (" - ALERT!" if is_alert else "")
                )
            else:
                st.metric(f"{horizon} Move", "N/A")
    
    # ========================================================================
    # TABBED INTERFACE: OVERVIEW
    # ========================================================================
    st.markdown("---")
    
    tab1, tab2 = st.tabs(["📊 Overview", "📋 Info"])
    
    with tab1:
        st.markdown("### Time Series Analysis")
        st.caption(f"Showing data from **{start_date}** to **{end_date}**")
        
        # Fetch full time series data for selected narrative
        with st.spinner(f"Loading time series data for {selected_narrative_name}..."):
            detail_metrics = get_narrative_metrics(
                narrative=selected_narrative_id,
                start_date=start_date,
                end_date=end_date,
                window=60,
                percentile_window=90,
            )
        
        if detail_metrics:
            df_detail = pd.DataFrame(detail_metrics)
            df_detail['date'] = pd.to_datetime(df_detail['date'])
            df_detail = df_detail.sort_values('date')
            
            # ================================================================
            # CHART 1: Intensity Z-Score over Time
            # ================================================================
            st.markdown("#### Intensity Z-Score")
            
            fig_intensity = make_subplots(
                rows=1, cols=1,
                specs=[[{"secondary_y": True}]]
            )
            
            # Primary y-axis: Intensity z-score
            fig_intensity.add_trace(
                go.Scatter(
                    x=df_detail['date'],
                    y=df_detail['intensity'],
                    name="Intensity Z-Score",
                    line=dict(color='#1f77b4', width=2),
                    mode='lines+markers',
                    marker=dict(size=4),
                    hovertemplate='<b>Date:</b> %{x|%Y-%m-%d}<br><b>Intensity:</b> %{y:.2f}<extra></extra>'
                ),
                secondary_y=False
            )
            
            # Secondary y-axis: Intensity percentile
            fig_intensity.add_trace(
                go.Scatter(
                    x=df_detail['date'],
                    y=df_detail['intensity_percentile'] * 100,
                    name="Intensity Percentile",
                    line=dict(color='rgba(31, 119, 180, 0.3)', width=1, dash='dash'),
                    mode='lines',
                    hovertemplate='<b>Date:</b> %{x|%Y-%m-%d}<br><b>Percentile:</b> %{y:.1f}%<extra></extra>'
                ),
                secondary_y=True
            )
            
            # Add horizontal line at z=0
            fig_intensity.add_hline(
                y=0, 
                line_dash="dot", 
                line_color="gray", 
                opacity=0.5,
                secondary_y=False
            )
            
            # Highlight selected date
            selected_date_dt = pd.to_datetime(st.session_state.selected_date)
            if selected_date_dt in df_detail['date'].values:
                selected_intensity = df_detail[df_detail['date'] == selected_date_dt]['intensity'].iloc[0]
                fig_intensity.add_trace(
                    go.Scatter(
                        x=[selected_date_dt],
                        y=[selected_intensity],
                        name="Selected Date",
                        mode='markers',
                        marker=dict(color='red', size=10, symbol='star'),
                        showlegend=True,
                        hovertemplate=f'<b>Selected: {st.session_state.selected_date}</b><br><b>Intensity:</b> {selected_intensity:.2f}<extra></extra>'
                    ),
                    secondary_y=False
                )
            
            # Update layout
            fig_intensity.update_xaxes(title_text="Date", showgrid=True)
            fig_intensity.update_yaxes(
                title_text="<b>Intensity Z-Score</b>", 
                secondary_y=False,
                showgrid=True
            )
            fig_intensity.update_yaxes(
                title_text="<b>Intensity Percentile (%)</b>", 
                secondary_y=True,
                showgrid=False,
                range=[0, 100]
            )
            fig_intensity.update_layout(
                height=450,
                hovermode='x unified',
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1
                )
            )
            
            st.plotly_chart(fig_intensity, use_container_width=True)
            
            # ================================================================
            # CHART 2: Sentiment over Time
            # ================================================================
            st.markdown("#### Sentiment")
            
            fig_sentiment = make_subplots(
                rows=1, cols=1,
                specs=[[{"secondary_y": True}]]
            )
            
            # Primary y-axis: Sentiment mean
            fig_sentiment.add_trace(
                go.Scatter(
                    x=df_detail['date'],
                    y=df_detail['sentiment_mean'],
                    name="Sentiment Mean",
                    line=dict(color='#2ca02c', width=2),
                    mode='lines+markers',
                    marker=dict(size=4),
                    hovertemplate='<b>Date:</b> %{x|%Y-%m-%d}<br><b>Sentiment:</b> %{y:.3f}<extra></extra>'
                ),
                secondary_y=False
            )
            
            # Secondary y-axis: Sentiment percentile
            fig_sentiment.add_trace(
                go.Scatter(
                    x=df_detail['date'],
                    y=df_detail['sentiment_percentile'] * 100,
                    name="Sentiment Percentile",
                    line=dict(color='rgba(44, 160, 44, 0.3)', width=1, dash='dash'),
                    mode='lines',
                    hovertemplate='<b>Date:</b> %{x|%Y-%m-%d}<br><b>Percentile:</b> %{y:.1f}%<extra></extra>'
                ),
                secondary_y=True
            )
            
            # Add horizontal line at sentiment=0
            fig_sentiment.add_hline(
                y=0, 
                line_dash="dot", 
                line_color="gray", 
                opacity=0.5,
                secondary_y=False
            )
            
            # Highlight selected date
            if selected_date_dt in df_detail['date'].values:
                selected_sentiment = df_detail[df_detail['date'] == selected_date_dt]['sentiment_mean'].iloc[0]
                fig_sentiment.add_trace(
                    go.Scatter(
                        x=[selected_date_dt],
                        y=[selected_sentiment],
                        name="Selected Date",
                        mode='markers',
                        marker=dict(color='red', size=10, symbol='star'),
                        showlegend=True,
                        hovertemplate=f'<b>Selected: {st.session_state.selected_date}</b><br><b>Sentiment:</b> {selected_sentiment:.3f}<extra></extra>'
                    ),
                    secondary_y=False
                )
            
            # Update layout
            fig_sentiment.update_xaxes(title_text="Date", showgrid=True)
            fig_sentiment.update_yaxes(
                title_text="<b>Sentiment [-1, 1]</b>", 
                secondary_y=False,
                showgrid=True,
                range=[-1, 1]
            )
            fig_sentiment.update_yaxes(
                title_text="<b>Sentiment Percentile (%)</b>", 
                secondary_y=True,
                showgrid=False,
                range=[0, 100]
            )
            fig_sentiment.update_layout(
                height=450,
                hovermode='x unified',
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1
                )
            )
            
            st.plotly_chart(fig_sentiment, use_container_width=True)
            
        else:
            st.warning("No time series data available for the selected narrative and date range.")
    
    with tab2:
        st.markdown("### Narrative Information")
        st.markdown(f"**Narrative ID:** `{selected_narrative_id}`")
        st.markdown(f"**Display Name:** {selected_narrative_name}")
        st.markdown(f"**Selected Date:** {st.session_state.selected_date}")
        st.markdown(f"**Date Range:** {start_date} to {end_date}")
        
        st.markdown("#### Metrics Summary")
        st.json({
            "intensity_z": float(selected_row['Intensity Z']),
            "intensity_percentile": float(selected_row['Intensity %ile']),
            "sentiment": float(selected_row['Sentiment']),
            "sentiment_percentile": float(selected_row['Sentiment %ile']),
            "horizon_moves": {
                "1d": float(selected_row['1d Move']) if selected_row['1d Move'] is not None else None,
                "2d": float(selected_row['2d Move']) if selected_row['2d Move'] is not None else None,
                "5d": float(selected_row['5d Move']) if selected_row['5d Move'] is not None else None,
                "10d": float(selected_row['10d Move']) if selected_row['10d Move'] is not None else None,
                "20d": float(selected_row['20d Move']) if selected_row['20d Move'] is not None else None,
            }
        })

# ============================================================================
# TODAY'S ALERTS
# ============================================================================
st.markdown("---")
st.markdown("### 🚨 Today's Alerts")
st.caption(f"Narratives with absolute horizon moves exceeding **1.0 standard deviation** on {st.session_state.selected_date}")

if all_alerts:
    # Group alerts by narrative
    alert_summary = {}
    for alert in all_alerts:
        if alert["narrative"] not in alert_summary:
            alert_summary[alert["narrative"]] = []
        alert_summary[alert["narrative"]].append(
            f"**{alert['horizon']}d**: {alert['move']:+.2f}σ"
        )
    
    # Display alerts in columns
    num_cols = min(3, len(alert_summary))
    cols = st.columns(num_cols) if num_cols > 0 else [st]
    
    for idx, (narrative, moves) in enumerate(sorted(alert_summary.items())):
        with cols[idx % num_cols]:
            with st.container(border=True):
                st.markdown(f"### 🔔 {narrative}")
                for move in moves:
                    st.markdown(move)
else:
    st.success("✓ No alerts detected for the selected date and narratives.")

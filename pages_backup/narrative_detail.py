"""
Narrative Detail Page - Detailed view with charts, articles, and explanations
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api_client import (
    get_narrative_metrics,
    get_narrative_articles,
    get_narrative_articles_date_range
)
from utils import (
    calculate_horizon_moves,
    detect_alerts,
    format_metric,
    get_date_range_for_period
)


def render():
    """Render the narrative detail page."""
    # Check if narrative is selected
    if not st.session_state.selected_narrative:
        st.warning("Please select a narrative from the Dashboard.")
        if st.button("Go to Dashboard"):
            st.session_state.selected_page = "Dashboard"
            st.rerun()
        return
    
    narrative = st.session_state.selected_narrative
    st.title(f"📈 {narrative}")
    
    # Get selected date
    if not st.session_state.selected_date:
        st.session_state.selected_date = datetime.now().strftime("%Y-%m-%d")
    
    selected_date = datetime.strptime(st.session_state.selected_date, "%Y-%m-%d")
    
    # Header: Quick stats
    st.markdown("### Quick Stats")
    
    # Fetch metrics for selected date
    start_date = (selected_date - timedelta(days=180)).strftime("%Y-%m-%d")
    end_date = selected_date.strftime("%Y-%m-%d")
    
    metrics = get_narrative_metrics(
        narrative=narrative,
        start_date=start_date,
        end_date=end_date,
        window=60,
        percentile_window=90
    )
    
    if not metrics:
        st.error(f"No metrics available for {narrative}")
        return
    
    df = pd.DataFrame(metrics)
    date_row = df[df['date'] == st.session_state.selected_date]
    
    if date_row.empty:
        st.warning(f"No data for {narrative} on {st.session_state.selected_date}")
        return
    
    row = date_row.iloc[0]
    
    # Calculate horizon moves
    moves = calculate_horizon_moves(df, st.session_state.selected_date, horizons=[1, 2, 5, 10, 20])
    alerts = detect_alerts(moves, threshold=1.0)
    
    # Display quick stats in columns
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        st.metric("Intensity Z", f"{row.get('intensity', 0):.2f}")
    
    with col2:
        intensity_pct = row.get('intensity_percentile', 0)
        if intensity_pct is not None:
            # Convert 0-1 to percentage if needed
            if intensity_pct <= 1.0:
                intensity_pct = intensity_pct * 100
            st.metric("Intensity %ile", f"{intensity_pct:.1f}%")
        else:
            st.metric("Intensity %ile", "N/A")
    
    with col3:
        st.metric("Sentiment", f"{row.get('sentiment_mean', 0):.3f}")
    
    with col4:
        sentiment_pct = row.get('sentiment_percentile', 0)
        if sentiment_pct is not None:
            # Convert 0-1 to percentage if needed
            if sentiment_pct <= 1.0:
                sentiment_pct = sentiment_pct * 100
            st.metric("Sentiment %ile", f"{sentiment_pct:.1f}%")
        else:
            st.metric("Sentiment %ile", "N/A")
    
    with col5:
        st.metric("Articles", row.get('article_count', 0))
    
    # Horizon moves with alert badges
    st.markdown("### Horizon Moves")
    move_cols = st.columns(5)
    horizon_labels = {1: "1d", 2: "2d", 5: "5d", 10: "10d", 20: "20d"}
    
    for idx, (horizon, label) in enumerate(horizon_labels.items()):
        with move_cols[idx]:
            move = moves.get(horizon)
            if move is not None:
                move_str = f"{move:+.2f}"
                if abs(move) > 1.0:
                    st.markdown(f"**{label}:** {move_str} 🚨")
                else:
                    st.markdown(f"**{label}:** {move_str}")
            else:
                st.markdown(f"**{label}:** N/A")
    
    # Tabs
    tab1, tab2, tab3 = st.tabs(["Overview", "Articles", "Explain"])
    
    with tab1:
        render_overview_tab(narrative, df)
    
    with tab2:
        render_articles_tab(narrative, selected_date)
    
    with tab3:
        render_explain_tab(narrative, selected_date, df, moves)


def render_overview_tab(narrative: str, df: pd.DataFrame):
    """Render the overview tab with charts."""
    st.markdown("#### Time Series Charts")
    
    # Time range selector for charts
    chart_range = st.radio(
        "Chart Range",
        ["30d", "90d", "180d", "365d"],
        horizontal=True,
        index=2
    )
    
    start_date, end_date = get_date_range_for_period(
        chart_range,
        df['date'].max() if not df.empty else datetime.now().strftime("%Y-%m-%d")
    )
    
    # Filter data for chart range
    df_chart = df[
        (df['date'] >= start_date) & 
        (df['date'] <= end_date)
    ].copy()
    
    if df_chart.empty:
        st.warning("No data available for the selected range.")
        return
    
    # Ensure date is datetime
    df_chart['date'] = pd.to_datetime(df_chart['date'])
    df_chart = df_chart.sort_values('date')
    
    # Intensity Z chart
    fig_intensity = go.Figure()
    fig_intensity.add_trace(go.Scatter(
        x=df_chart['date'],
        y=df_chart['intensity'],
        mode='lines+markers',
        name='Intensity Z',
        line=dict(color='blue', width=2)
    ))
    fig_intensity.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
    fig_intensity.update_layout(
        title="Intensity Z-Score Over Time",
        xaxis_title="Date",
        yaxis_title="Intensity Z-Score",
        hovermode='x unified',
        height=400
    )
    st.plotly_chart(fig_intensity, use_container_width=True)
    
    # Sentiment chart
    fig_sentiment = go.Figure()
    fig_sentiment.add_trace(go.Scatter(
        x=df_chart['date'],
        y=df_chart['sentiment_mean'],
        mode='lines+markers',
        name='Sentiment',
        line=dict(color='green', width=2)
    ))
    fig_sentiment.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
    fig_sentiment.update_layout(
        title="Sentiment Over Time",
        xaxis_title="Date",
        yaxis_title="Sentiment",
        hovermode='x unified',
        height=400
    )
    st.plotly_chart(fig_sentiment, use_container_width=True)
    
    # Optional: Combined chart with percentiles
    if st.checkbox("Show Percentiles"):
        fig_combined = make_subplots(
            rows=2, cols=1,
            subplot_titles=("Intensity Metrics", "Sentiment Metrics"),
            vertical_spacing=0.1
        )
        
        # Intensity
        fig_combined.add_trace(
            go.Scatter(x=df_chart['date'], y=df_chart['intensity'], name='Intensity Z'),
            row=1, col=1
        )
        fig_combined.add_trace(
            go.Scatter(x=df_chart['date'], y=df_chart['intensity_percentile'], name='Intensity %ile', yaxis='y2'),
            row=1, col=1
        )
        
        # Sentiment
        fig_combined.add_trace(
            go.Scatter(x=df_chart['date'], y=df_chart['sentiment_mean'], name='Sentiment'),
            row=2, col=1
        )
        fig_combined.add_trace(
            go.Scatter(x=df_chart['date'], y=df_chart['sentiment_percentile'], name='Sentiment %ile', yaxis='y4'),
            row=2, col=1
        )
        
        fig_combined.update_layout(height=600, title_text=f"{narrative} - All Metrics")
        st.plotly_chart(fig_combined, use_container_width=True)


def render_articles_tab(narrative: str, selected_date: datetime):
    """Render the articles tab."""
    st.markdown("#### Articles")
    
    # Fetch articles
    articles = get_narrative_articles(narrative, selected_date)
    
    if not articles:
        st.info(f"No articles found for {narrative} on {selected_date.strftime('%Y-%m-%d')}")
        return
    
    # Filters
    col1, col2 = st.columns(2)
    
    with col1:
        sources = sorted(set([a['source'] for a in articles]))
        selected_source = st.selectbox("Filter by Source", ["All"] + sources)
    
    with col2:
        keyword = st.text_input("Search in titles", "")
    
    # Filter articles
    filtered_articles = articles
    if selected_source != "All":
        filtered_articles = [a for a in filtered_articles if a['source'] == selected_source]
    if keyword:
        filtered_articles = [a for a in filtered_articles if keyword.lower() in a['title'].lower()]
    
    # Sort options
    sort_by = st.radio("Sort by", ["Time (Newest)", "Sentiment (Low to High)", "Sentiment (High to Low)"], horizontal=True)
    
    if sort_by == "Time (Newest)":
        filtered_articles.sort(key=lambda x: x['published_at'] if x['published_at'] else datetime.min, reverse=True)
    elif sort_by == "Sentiment (Low to High)":
        filtered_articles.sort(key=lambda x: x['sentiment_score'] if x['sentiment_score'] is not None else -999)
    else:
        filtered_articles.sort(key=lambda x: x['sentiment_score'] if x['sentiment_score'] is not None else -999, reverse=True)
    
    # Display articles table
    st.markdown(f"**{len(filtered_articles)} articles found**")
    
    for article in filtered_articles:
        with st.container():
            col1, col2 = st.columns([3, 1])
            
            with col1:
                published_str = article['published_at'].strftime("%Y-%m-%d %H:%M") if article['published_at'] else "Unknown"
                st.markdown(f"**{article['title']}**")
                st.caption(f"{article['source']} • {published_str}")
            
            with col2:
                sentiment = article.get('sentiment_score', 0)
                if sentiment is not None:
                    st.metric("Sentiment", f"{sentiment:.3f}")
                else:
                    st.write("N/A")
            
            if article['url']:
                st.markdown(f"[Read article →]({article['url']})")
            
            st.divider()


def render_explain_tab(narrative: str, selected_date: datetime, df: pd.DataFrame, moves: dict):
    """Render the explain tab."""
    st.markdown("#### Explain Latest Move")
    
    if st.button("Generate Explanation"):
        # Get latest move
        latest_move = None
        latest_horizon = None
        for horizon in [1, 2, 5, 10, 20]:
            move = moves.get(horizon)
            if move is not None and abs(move) > 0.5:
                if latest_move is None or abs(move) > abs(latest_move):
                    latest_move = move
                    latest_horizon = horizon
        
        if latest_move is None:
            st.info("No significant moves detected in the past 20 days.")
            return
        
        # Fetch articles from past 3 days
        start_date_range = selected_date - timedelta(days=3)
        articles = get_narrative_articles_date_range(narrative, start_date_range, selected_date)
        
        if not articles:
            st.warning("No articles found for explanation.")
            return
        
        # Sort articles by sentiment magnitude or recency
        articles_sorted = sorted(
            articles,
            key=lambda x: (
                abs(x['sentiment_score']) if x['sentiment_score'] is not None else 0,
                x['published_at'] if x['published_at'] else datetime.min
            ),
            reverse=True
        )
        
        # Generate explanation
        move_direction = "up" if latest_move > 0 else "down"
        move_magnitude = abs(latest_move)
        
        st.markdown("### Explanation")
        st.markdown(
            f"Over the past **{latest_horizon} days**, {narrative} intensity moved **{move_direction}** "
            f"by **{move_magnitude:.2f}** standard deviations."
        )
        
        st.markdown("### Key Drivers")
        
        # Show top 5 articles
        top_articles = articles_sorted[:5]
        for i, article in enumerate(top_articles, 1):
            sentiment_str = f" (sentiment: {article['sentiment_score']:.3f})" if article['sentiment_score'] is not None else ""
            url_str = f" [→]({article['url']})" if article['url'] else ""
            st.markdown(f"{i}. **{article['title']}**{sentiment_str}{url_str}")
            st.caption(f"{article['source']} • {article['published_at'].strftime('%Y-%m-%d') if article['published_at'] else 'Unknown'}")
        
        # Summary paragraph
        st.markdown("### Summary")
        sentiment_avg = sum(
            a['sentiment_score'] for a in top_articles 
            if a['sentiment_score'] is not None
        ) / len([a for a in top_articles if a['sentiment_score'] is not None]) if top_articles else 0
        
        sentiment_desc = "negative" if sentiment_avg < -0.3 else "positive" if sentiment_avg > 0.3 else "neutral"
        
        st.markdown(
            f"The recent {move_direction}ward movement in {narrative} intensity is driven by "
            f"{len(articles)} articles published over the past 3 days. The overall sentiment is {sentiment_desc}, "
            f"with key headlines focusing on recent developments in this narrative."
        )


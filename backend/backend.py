import os
import ssl
from contextlib import asynccontextmanager
from datetime import date, timedelta
from typing import List, Optional

import asyncpg
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://{user}:{password}@{host}:{port}/{database}".format(
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD"),
        host=os.getenv(
            "POSTGRES_HOST",
            "articles-rds.cp2yuauyo6lc.ap-southeast-1.rds.amazonaws.com",
        ),
        port=os.getenv("POSTGRES_PORT", "5432"),
        database=os.getenv("POSTGRES_DB", "articles-rds"),
    ),
)

if "POSTGRES_PASSWORD" not in os.environ and "DATABASE_URL" not in os.environ:
    raise RuntimeError("Missing POSTGRES_PASSWORD (set it in .env locally or as a Secret on Hugging Face).")


# ---- SSL helpers ----

def build_ssl_context() -> ssl.SSLContext | bool | str:
    """
    Forces encrypted connections.

    - Default: require SSL with system trust store.
    - If PGSSLROOTCERT is set, uses that CA bundle file.
    - If PGSSL_INSECURE=1, disables verification (DEV ONLY).
    """
    # asyncpg supports: True / SSLContext / 'disable'/'allow'/'prefer'
    # We want "require", so use True or SSLContext.
    cafile = os.getenv("PGSSLROOTCERT")
    insecure = os.getenv("PGSSL_INSECURE", "0") == "1"

    ctx = ssl.create_default_context(cafile=cafile) if cafile else ssl.create_default_context()

    if insecure:
        # DEV ONLY - do not use in production
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    return ctx


# ---- FastAPI app + pool ----

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create a connection pool once at startup
    app.state.db_pool = await asyncpg.create_pool(
        dsn=DATABASE_URL,
        min_size=int(os.getenv("PGPOOL_MIN_SIZE", "1")),
        max_size=int(os.getenv("PGPOOL_MAX_SIZE", "10")),
        ssl=build_ssl_context(),   # <-- key fix: forces encryption
        command_timeout=float(os.getenv("PGCOMMAND_TIMEOUT", "60")),
    )
    try:
        yield
    finally:
        await app.state.db_pool.close()


app = FastAPI(title="Narrative Metrics API", lifespan=lifespan)


async def get_connection(request: Request):
    """Yield an asyncpg connection from the pool."""
    pool: asyncpg.Pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        yield conn


# ---- Models ----

class Metric(BaseModel):
    """Response model for a single day's metrics."""

    date: date
    article_count: int = Field(..., description="Number of deduplicated articles on that date")
    rolling_mean: float = Field(..., description="Trailing mean of counts over prior W days (excludes today)")
    rolling_std: float = Field(..., description="Trailing std-dev of counts over prior W days (excludes today)")
    intensity: float = Field(..., description="Z-score intensity of article count vs prior W-day baseline")
    sentiment_mean: Optional[float] = Field(
        None,
        description="Unweighted mean sentiment of deduplicated items on that date; null when no items",
    )
    intensity_percentile: float = Field(
        ..., description="Percent-rank of intensity over trailing percentile window (computed in Python)"
    )
    sentiment_percentile: Optional[float] = Field(
        None,
        description="Percent-rank of sentiment over trailing percentile window (only on days with sentiment)",
    )


# ---- Endpoints ----

@app.get("/narratives", response_model=List[str])
async def list_narratives(conn: asyncpg.Connection = Depends(get_connection)):
    """Return a sorted list of distinct narratives (primary_label_v2 values)."""
    rows = await conn.fetch(
        "SELECT DISTINCT primary_label_v2 FROM articles WHERE primary_label_v2 IS NOT NULL ORDER BY primary_label_v2"
    )
    return [row["primary_label_v2"] for row in rows]


def _percent_rank(window_values: List[float], x: float) -> float:
    """
    Percent-rank like Postgres PERCENT_RANK():
      rank = 1 + count(values < x)   (RANK semantics for ties)
      percent_rank = (rank - 1) / (n - 1) when n > 1 else 0
    """
    n = len(window_values)
    if n <= 1:
        return 0.0
    less = sum(1 for v in window_values if v < x)
    rank = 1 + less
    return (rank - 1) / (n - 1)


@app.get(
    "/narratives/{narrative}/metrics",
    response_model=List[Metric],
    summary="Get metrics for a narrative",
)
async def narrative_metrics(
    narrative: str,
    start_date: Optional[date] = Query(
        None, description="Start of date range (inclusive). Defaults to 365 days ago."
    ),
    end_date: Optional[date] = Query(
        None, description="End of date range (inclusive). Defaults to today."
    ),
    window: int = Query(
        60,
        ge=1,
        le=365,
        description="W: number of prior days used for rolling mean/std (baseline excludes today).",
    ),
    percentile_window: int = Query(
        365,
        ge=1,
        le=730,
        description="Number of days in the trailing window for percentile ranks.",
    ),
    epsilon: float = Query(
        0.25,
        gt=0.0,
        le=10.0,
        description="Small floor in denominator to avoid blow-ups when std is very small.",
    ),
    conn: asyncpg.Connection = Depends(get_connection),
):
    """
    Intensity:
      N_t = deduplicated item count on day t (distinct id)
      mu_t, sigma_t computed from prior W days only: N_{t-1}..N_{t-W}
      z_t = (N_t - mu_t) / max(sigma_t, epsilon)

    Sentiment:
      sentiment_t = unweighted mean of per-item sentiment scores on day t
      (null when N_t == 0)
    """
    today = date.today()
    if end_date is None:
        end_date = today
    if start_date is None:
        start_date = end_date - timedelta(days=365)

    if start_date > end_date:
        raise HTTPException(status_code=400, detail="start_date must be on or before end_date")

    win = max(1, min(int(window), 365))
    pwin = max(1, min(int(percentile_window), 730))
    eps = float(epsilon)

    history_days = max(win, pwin)
    calc_start = start_date - timedelta(days=history_days)

    query = f"""
        WITH calendar AS (
            SELECT generate_series($2::date, $3::date, interval '1 day')::date AS narrative_date
        ),
        daily_items AS (
            SELECT DISTINCT
                id,
                published_at::date AS narrative_date,
                sentiment_score
            FROM articles
            WHERE primary_label_v2 = $1
              AND published_at::date BETWEEN $2 AND $3
        ),
        daily_agg AS (
            SELECT
                narrative_date,
                COUNT(*) AS article_count,
                AVG(sentiment_score) AS sentiment_mean
            FROM daily_items
            GROUP BY narrative_date
        ),
        daily_series AS (
            SELECT
                c.narrative_date,
                COALESCE(a.article_count, 0) AS article_count,
                a.sentiment_mean
            FROM calendar c
            LEFT JOIN daily_agg a
              ON c.narrative_date = a.narrative_date
        ),
        rolling_stats AS (
            SELECT
                narrative_date,
                article_count,
                sentiment_mean,
                COUNT(article_count) OVER (
                    ORDER BY narrative_date
                    ROWS BETWEEN {win} PRECEDING AND 1 PRECEDING
                ) AS baseline_n,
                AVG(article_count) OVER (
                    ORDER BY narrative_date
                    ROWS BETWEEN {win} PRECEDING AND 1 PRECEDING
                ) AS rolling_mean,
                STDDEV_SAMP(article_count) OVER (
                    ORDER BY narrative_date
                    ROWS BETWEEN {win} PRECEDING AND 1 PRECEDING
                ) AS rolling_std
            FROM daily_series
        )
        SELECT
            narrative_date,
            article_count,
            rolling_mean,
            rolling_std,
            CASE
                WHEN baseline_n = 0 THEN 0.0
                ELSE (article_count - COALESCE(rolling_mean, 0.0))
                     / GREATEST(COALESCE(rolling_std, 0.0), $4::double precision)
            END AS intensity,
            sentiment_mean
        FROM rolling_stats
        ORDER BY narrative_date;
    """

    rows = await conn.fetch(query, narrative, calc_start, end_date, eps)

    dates: List[date] = []
    counts: List[int] = []
    rmean: List[float] = []
    rstd: List[float] = []
    intensities: List[float] = []
    sentiments: List[Optional[float]] = []

    for row in rows:
        dates.append(row["narrative_date"])
        counts.append(int(row["article_count"]))
        rmean.append(float(row["rolling_mean"]) if row["rolling_mean"] is not None else 0.0)
        rstd.append(float(row["rolling_std"]) if row["rolling_std"] is not None else 0.0)
        intensities.append(float(row["intensity"]) if row["intensity"] is not None else 0.0)
        sentiments.append(float(row["sentiment_mean"]) if row["sentiment_mean"] is not None else None)

    intensity_pcts: List[float] = []
    sentiment_pcts: List[Optional[float]] = []

    for i in range(len(dates)):
        start_idx = max(0, i - pwin + 1)

        w_int = intensities[start_idx : i + 1]
        intensity_pcts.append(_percent_rank(w_int, intensities[i]))

        if sentiments[i] is None:
            sentiment_pcts.append(None)
        else:
            w_sent = [v for v in sentiments[start_idx : i + 1] if v is not None]
            sentiment_pcts.append(_percent_rank(w_sent, sentiments[i]))

    metrics: List[Metric] = []
    for i, d in enumerate(dates):
        if start_date <= d <= end_date:
            metrics.append(
                Metric(
                    date=d,
                    article_count=counts[i],
                    rolling_mean=rmean[i],
                    rolling_std=rstd[i],
                    intensity=intensities[i],
                    sentiment_mean=sentiments[i],
                    intensity_percentile=float(intensity_pcts[i]),
                    sentiment_percentile=sentiment_pcts[i],
                )
            )

    return metrics


# import os
# from datetime import date, timedelta
# from typing import List, Optional

# import asyncpg
# from fastapi import Depends, FastAPI, HTTPException, Query
# from pydantic import BaseModel, Field


# DATABASE_URL = os.getenv(
#     "DATABASE_URL",
#     "postgresql://{user}:{password}@{host}:{port}/{database}".format(
#         user=os.getenv("POSTGRES_USER", "postgres"),
#         password=os.getenv("POSTGRES_PASSWORD", "Narratives2026$"),
#         host=os.getenv(
#             "POSTGRES_HOST",
#             "articles-rds.cp2yuauyo6lc.ap-southeast-1.rds.amazonaws.com",
#         ),
#         port=os.getenv("POSTGRES_PORT", "5432"),
#         database=os.getenv("POSTGRES_DB", "articles-rds"),
#     ),
# )

# app = FastAPI(title="Narrative Metrics API")


# async def get_connection():
#     """Yield an asyncpg connection. The connection is closed after use."""
#     conn = await asyncpg.connect(DATABASE_URL)
#     try:
#         yield conn
#     finally:
#         await conn.close()


# class Metric(BaseModel):
#     """Response model for a single day's metrics."""

#     date: date
#     article_count: int = Field(..., description="Number of deduplicated articles on that date")
#     rolling_mean: float = Field(..., description="Trailing mean of counts over prior W days (excludes today)")
#     rolling_std: float = Field(..., description="Trailing std-dev of counts over prior W days (excludes today)")
#     intensity: float = Field(..., description="Z-score intensity of article count vs prior W-day baseline")
#     sentiment_mean: Optional[float] = Field(
#         None,
#         description="Unweighted mean sentiment of deduplicated items on that date; null when no items",
#     )
#     intensity_percentile: float = Field(
#         ..., description="Percent-rank of intensity over trailing percentile window (computed in Python)"
#     )
#     sentiment_percentile: Optional[float] = Field(
#         None,
#         description="Percent-rank of sentiment over trailing percentile window (only on days with sentiment)",
#     )


# @app.get("/narratives", response_model=List[str])
# async def list_narratives(conn: asyncpg.Connection = Depends(get_connection)):
#     """Return a sorted list of distinct narratives (primary_label values)."""
#     rows = await conn.fetch(
#         "SELECT DISTINCT primary_label FROM articles WHERE primary_label IS NOT NULL ORDER BY primary_label"
#     )
#     return [row["primary_label"] for row in rows]


# def _percent_rank(window_values: List[float], x: float) -> float:
#     """
#     Percent-rank like Postgres PERCENT_RANK():
#       rank = 1 + count(values < x)   (RANK semantics for ties)
#       percent_rank = (rank - 1) / (n - 1) when n > 1 else 0
#     """
#     n = len(window_values)
#     if n <= 1:
#         return 0.0
#     less = sum(1 for v in window_values if v < x)
#     rank = 1 + less
#     return (rank - 1) / (n - 1)


# @app.get(
#     "/narratives/{narrative}/metrics",
#     response_model=List[Metric],
#     summary="Get metrics for a narrative",
# )
# async def narrative_metrics(
#     narrative: str,
#     start_date: Optional[date] = Query(
#         None, description="Start of date range (inclusive). Defaults to 365 days ago."
#     ),
#     end_date: Optional[date] = Query(
#         None, description="End of date range (inclusive). Defaults to today."
#     ),
#     window: int = Query(
#         60,
#         ge=1,
#         le=365,
#         description="W: number of prior days used for rolling mean/std (baseline excludes today).",
#     ),
#     percentile_window: int = Query(
#         365,
#         ge=1,
#         le=730,
#         description="Number of days in the trailing window for percentile ranks.",
#     ),
#     epsilon: float = Query(
#         0.25,
#         gt=0.0,
#         le=10.0,
#         description="Small floor in denominator to avoid blow-ups when std is very small.",
#     ),
#     conn: asyncpg.Connection = Depends(get_connection),
# ):
#     """
#     Intensity matches your definition:
#       N_t = deduplicated item count on day t (distinct id)
#       mu_t, sigma_t computed from prior W days only: N_{t-1}..N_{t-W}
#       z_t = (N_t - mu_t) / max(sigma_t, epsilon)

#     Sentiment matches your definition on deduplicated items:
#       sentiment_t = unweighted mean of per-item sentiment scores on day t
#       (null when N_t == 0)
#     """
#     today = date.today()
#     if end_date is None:
#         end_date = today
#     if start_date is None:
#         start_date = end_date - timedelta(days=365)

#     if start_date > end_date:
#         raise HTTPException(status_code=400, detail="start_date must be on or before end_date")

#     win = max(1, min(int(window), 365))
#     pwin = max(1, min(int(percentile_window), 730))
#     eps = float(epsilon)

#     # Pull extra history so the first returned day has a proper trailing baseline / percentile window.
#     history_days = max(win, pwin)
#     calc_start = start_date - timedelta(days=history_days)

#     # Dynamic SQL only for ROWS bounds (cannot be parameterized). Values still parameterized for safety.
#     # Baseline window matches your spec (prior W days only): ROWS BETWEEN {win} PRECEDING AND 1 PRECEDING
    


#     query = f"""
#         WITH calendar AS (
#             SELECT generate_series($2::date, $3::date, interval '1 day')::date AS narrative_date
#         ),
#         -- Deduplicate at the item level (distinct id per day) before aggregating count/sentiment.
#         daily_items AS (
#             SELECT DISTINCT
#                 id,
#                 published_at::date AS narrative_date,
#                 sentiment_score
#             FROM articles
#             WHERE primary_label = $1
#               AND published_at::date BETWEEN $2 AND $3
#         ),
#         daily_agg AS (
#             SELECT
#                 narrative_date,
#                 COUNT(*) AS article_count,
#                 AVG(sentiment_score) AS sentiment_mean
#             FROM daily_items
#             GROUP BY narrative_date
#         ),
#         daily_series AS (
#             SELECT
#                 c.narrative_date,
#                 COALESCE(a.article_count, 0) AS article_count,
#                 a.sentiment_mean  -- keep NULL on no-article days
#             FROM calendar c
#             LEFT JOIN daily_agg a
#               ON c.narrative_date = a.narrative_date
#         ),
#         rolling_stats AS (
#             SELECT
#                 narrative_date,
#                 article_count,
#                 sentiment_mean,
#                 COUNT(article_count) OVER (
#                     ORDER BY narrative_date
#                     ROWS BETWEEN {win} PRECEDING AND 1 PRECEDING
#                 ) AS baseline_n,
#                 AVG(article_count) OVER (
#                     ORDER BY narrative_date
#                     ROWS BETWEEN {win} PRECEDING AND 1 PRECEDING
#                 ) AS rolling_mean,
#                 STDDEV_SAMP(article_count) OVER (
#                     ORDER BY narrative_date
#                     ROWS BETWEEN {win} PRECEDING AND 1 PRECEDING
#                 ) AS rolling_std
#             FROM daily_series
#         )
#         SELECT
#             narrative_date,
#             article_count,
#             rolling_mean,
#             rolling_std,
#             CASE
#                 WHEN baseline_n = 0 THEN 0.0
#                 ELSE (article_count - COALESCE(rolling_mean, 0.0))
#                      / GREATEST(COALESCE(rolling_std, 0.0), $4::double precision)
#             END AS intensity,
#             sentiment_mean
#         FROM rolling_stats
#         ORDER BY narrative_date;
#     """

#     rows = await conn.fetch(query, narrative, calc_start, end_date, eps)

#     # Build full series (including extra history), then compute *true trailing* percentiles in Python.
#     dates: List[date] = []
#     counts: List[int] = []
#     rmean: List[float] = []
#     rstd: List[float] = []
#     intensities: List[float] = []
#     sentiments: List[Optional[float]] = []

#     for row in rows:
#         dates.append(row["narrative_date"])
#         counts.append(int(row["article_count"]))
#         rmean.append(float(row["rolling_mean"]) if row["rolling_mean"] is not None else 0.0)
#         rstd.append(float(row["rolling_std"]) if row["rolling_std"] is not None else 0.0)
#         intensities.append(float(row["intensity"]) if row["intensity"] is not None else 0.0)
#         sentiments.append(float(row["sentiment_mean"]) if row["sentiment_mean"] is not None else None)

#     intensity_pcts: List[float] = []
#     sentiment_pcts: List[Optional[float]] = []

#     for i in range(len(dates)):
#         start_idx = max(0, i - pwin + 1)

#         w_int = intensities[start_idx : i + 1]
#         intensity_pcts.append(_percent_rank(w_int, intensities[i]))

#         # Sentiment percentiles only computed on days that have sentiment (N_t > 0)
#         if sentiments[i] is None:
#             sentiment_pcts.append(None)
#         else:
#             w_sent = [v for v in sentiments[start_idx : i + 1] if v is not None]
#             sentiment_pcts.append(_percent_rank(w_sent, sentiments[i]))

#     # Return only the requested date range
#     metrics: List[Metric] = []
#     for i, d in enumerate(dates):
#         if start_date <= d <= end_date:
#             metrics.append(
#                 Metric(
#                     date=d,
#                     article_count=counts[i],
#                     rolling_mean=rmean[i],
#                     rolling_std=rstd[i],
#                     intensity=intensities[i],
#                     sentiment_mean=sentiments[i],
#                     intensity_percentile=float(intensity_pcts[i]),
#                     sentiment_percentile=sentiment_pcts[i],
#                 )
#             )

#     return metrics
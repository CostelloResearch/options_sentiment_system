# =============================================================================
# dashboard/app.py — Interactive Plotly report
#
# LAYOUT (top to bottom, shared x-axis)
# ────────────────────────────────────
# Panel 1 (large): AAPL daily close price with coloured signal markers
#                  Green triangle-up  = BUY CALLS / BUY PUTS
#                  Red   triangle-down = SELL CALLS / SELL PUTS
# Panel 2: Sentiment score over time — line + horizontal ±0.25 threshold bands
# Panel 3: IV Rank over time — line + horizontal 0.30/0.70 threshold bands
# Panel 4: Cumulative P&L curve from the backtest trade log
#
# OUTPUT
# ──────
# Saves dashboard/report.html — a fully self-contained file that opens in
# any browser without an internet connection.
# =============================================================================

import os
import sys
import glob

import numpy as np
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config
from backtest.engine import load_price_history, _generate_synthetic_history
from backtest.metrics import load_trade_log, cumulative_pnl_series
from signals.signal_engine import (
    SIG_BUY_CALLS, SIG_SELL_PUTS, SIG_BUY_PUTS, SIG_SELL_CALLS,
    SIG_NEUTRAL, SIG_IV_CRUSH,
)
from signals.earnings_filter import fetch_earnings_dates, PRE_EARNINGS_DAYS, POST_EARNINGS_DAYS

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------
COLOUR_PRICE    = "#4C72B0"
COLOUR_BUY      = "#2ca02c"   # green — buying premium
COLOUR_SELL     = "#d62728"   # red   — selling premium
COLOUR_NEUTRAL  = "#7f7f7f"
COLOUR_SENT     = "#9467bd"
COLOUR_IV       = "#e377c2"
COLOUR_PNL_POS  = "#2ca02c"
COLOUR_PNL_NEG  = "#d62728"
COLOUR_THRESH   = "rgba(200,200,200,0.5)"


COLOUR_EARNINGS = "rgba(255, 165, 0, 0.12)"   # faint orange for earnings windows
COLOUR_IV_CRUSH = "#ff7f0e"                     # orange marker for IV CRUSH signal


def _signal_colour(signal: str) -> str:
    if signal in (SIG_BUY_CALLS, SIG_BUY_PUTS):
        return COLOUR_BUY
    if signal in (SIG_SELL_CALLS, SIG_SELL_PUTS):
        return COLOUR_SELL
    if signal == SIG_IV_CRUSH:
        return COLOUR_IV_CRUSH
    return COLOUR_NEUTRAL


def _signal_symbol(signal: str) -> str:
    """Plotly marker symbol name."""
    if signal in (SIG_BUY_CALLS, SIG_BUY_PUTS):
        return "triangle-up"
    if signal in (SIG_SELL_CALLS, SIG_SELL_PUTS):
        return "triangle-down"
    if signal == SIG_IV_CRUSH:
        return "star"
    return "circle"


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def _load_sentiment_all(ticker: str) -> pd.DataFrame:
    """
    Load any available real sentiment CSVs.  Returns empty DataFrame if none.
    """
    raw_dir = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "data", "raw")
    )
    pattern = os.path.join(raw_dir, f"sentiment_{ticker}_*.csv")
    files = sorted(glob.glob(pattern))
    if not files:
        return pd.DataFrame()
    frames = [pd.read_csv(f) for f in files]
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    df.drop_duplicates(subset=["ticker", "date"], keep="last", inplace=True)
    df.sort_values("date", inplace=True)
    return df


def _load_signals_all(ticker: str, demo_mode: bool) -> pd.DataFrame:
    """
    Load the signal history from the backtest trade log (one row per trade).
    """
    trades = load_trade_log(ticker, demo_mode)
    if trades.empty:
        return pd.DataFrame()
    trades["entry_date"] = pd.to_datetime(trades["entry_date"])
    return trades


def _load_combined_sentiment(ticker: str) -> pd.DataFrame:
    """
    Load the Path-A merger output: data/raw/combined_sentiment_{TICKER}.csv.

    Returns a DataFrame with columns:
        date, combined_sentiment,
        news_sentiment, sec_earnings_sentiment, sec_other_sentiment
    Returns empty DataFrame if the file doesn't exist (e.g. on tickers
    where merger.build_combined returned empty -- ETFs with no news yet,
    or any ticker pre-real-data backfill).
    """
    raw_dir = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "data", "raw")
    )
    path = os.path.join(raw_dir, f"combined_sentiment_{ticker.upper()}.csv")
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        df = pd.read_csv(path, parse_dates=["date"])
    except Exception as e:
        print(f"[dashboard] WARN: failed to read {path}: {e}")
        return pd.DataFrame()
    keep = ["date", "combined_sentiment",
            "news_sentiment", "sec_earnings_sentiment", "sec_other_sentiment"]
    have = [c for c in keep if c in df.columns]
    return df[have].copy()


def _load_live_signals(ticker: str) -> pd.DataFrame:
    """
    Load the live signal_engine emissions: data/raw/signals_{TICKER}.csv.

    These are the CURRENT signals produced by the daily run (one row
    accumulated per scheduler run), as opposed to the backtest trade log
    (one row per simulated trade across history).  Used to overlay live
    markers on the price panel so the user can compare backtest signals
    to what the live engine is currently saying.

    Returns a DataFrame with columns: signal_date (datetime), signal.
    Empty if file is missing.
    """
    raw_dir = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "data", "raw")
    )
    path = os.path.join(raw_dir, f"signals_{ticker.upper()}.csv")
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        # signals_{ticker}.csv grows new columns over time as the
        # signal_engine adds fields (earnings_warning, days_to_earnings
        # were added after the first runs).  on_bad_lines='skip' is the
        # pattern used elsewhere in the codebase (check_pipeline.py).
        df = pd.read_csv(path, on_bad_lines="skip")
    except Exception as e:
        print(f"[dashboard] WARN: failed to read {path}: {e}")
        return pd.DataFrame()
    if "signal_date" not in df.columns or "signal" not in df.columns:
        return pd.DataFrame()
    df = df.copy()
    df["signal_date"] = pd.to_datetime(df["signal_date"], errors="coerce")
    return df[["signal_date", "signal"]].dropna()


# ---------------------------------------------------------------------------
# Panel builders
# ---------------------------------------------------------------------------

def _add_earnings_vrects(
    fig: go.Figure,
    earnings_dates: list,
    price_df: pd.DataFrame,
) -> None:
    """
    Shade the earnings sensitivity window on every panel.

    We draw one vertical rectangle per earnings event spanning
    [earnings_date - PRE_EARNINGS_DAYS, earnings_date + POST_EARNINGS_DAYS].
    A small annotation arrow marks the exact earnings date.
    """
    import datetime
    if not earnings_dates:
        return

    # Only shade dates that fall within the price chart's date range
    chart_start = price_df.index.min()
    chart_end   = price_df.index.max()

    for ed in earnings_dates:
        ed_ts = pd.Timestamp(ed)
        x0    = ed_ts - pd.Timedelta(days=PRE_EARNINGS_DAYS)
        x1    = ed_ts + pd.Timedelta(days=POST_EARNINGS_DAYS)

        if x1 < chart_start or x0 > chart_end:
            continue   # outside visible range

        # Add a shaded rectangle that spans ALL rows (y0=0, y1=1 in paper coords)
        fig.add_vrect(
            x0=x0, x1=x1,
            fillcolor=COLOUR_EARNINGS,
            line_width=0,
            annotation_text="Earnings",
            annotation_position="top left",
            annotation=dict(font_size=9, font_color="#b36b00"),
        )


def _panel_price(fig: go.Figure, price_df: pd.DataFrame,
                 trades: pd.DataFrame, row: int,
                 live_signals: pd.DataFrame = None,
                 col: int = 1) -> None:
    """
    Close line + backtest signal markers (filled) + live signal markers
    (outlined).

    Filled markers come from `trades` (backtest log).  Outlined markers
    come from `live_signals` (signal_engine output).  This lets the user
    visually compare what the backtest *would* have done at a given
    historical date against what the live engine is currently saying.
    """
    fig.add_trace(go.Scatter(
        x=price_df.index,
        y=price_df["close"],
        mode="lines",
        name="Close price",
        line=dict(color=COLOUR_PRICE, width=1.5),
        hovertemplate="%{x|%Y-%m-%d}<br>$%{y:.2f}<extra></extra>",
    ), row=row, col=col)

    # --- Backtest signals: filled markers ---
    if trades is not None and not trades.empty:
        for signal in trades["signal"].unique():
            if signal == SIG_NEUTRAL:
                continue
            subset = trades[trades["signal"] == signal]
            y_vals = []
            for dt in subset["entry_date"]:
                dt_norm = pd.Timestamp(dt).normalize()
                if dt_norm in price_df.index:
                    y_vals.append(float(price_df.loc[dt_norm, "close"]))
                else:
                    y_vals.append(None)

            fig.add_trace(go.Scatter(
                x=subset["entry_date"],
                y=y_vals,
                mode="markers",
                name=f"{signal} (backtest)",
                marker=dict(
                    symbol=_signal_symbol(signal),
                    color=_signal_colour(signal),
                    size=12,
                    line=dict(width=1, color="white"),
                ),
                hovertemplate=(
                    f"<b>{signal}</b> (backtest)<br>"
                    "%{x|%Y-%m-%d}<br>"
                    "Entry: $%{y:.2f}<extra></extra>"
                ),
            ), row=row, col=col)

    # --- Live signals: outlined (open) markers ---
    # Plotly suffix "-open" gives us a marker drawn with line only, no
    # fill.  Distinct from the backtest's solid filled markers but uses
    # the same colour + symbol family so the meaning is obvious.
    if live_signals is not None and not live_signals.empty:
        for signal in live_signals["signal"].unique():
            if signal == SIG_NEUTRAL:
                continue
            subset = live_signals[live_signals["signal"] == signal]
            y_vals = []
            for dt in subset["signal_date"]:
                dt_norm = pd.Timestamp(dt).normalize()
                if dt_norm in price_df.index:
                    y_vals.append(float(price_df.loc[dt_norm, "close"]))
                else:
                    y_vals.append(None)

            base_symbol = _signal_symbol(signal)
            open_symbol = (base_symbol + "-open"
                           if not base_symbol.endswith("-open") else base_symbol)
            fig.add_trace(go.Scatter(
                x=subset["signal_date"],
                y=y_vals,
                mode="markers",
                name=f"{signal} (live)",
                marker=dict(
                    symbol=open_symbol,
                    color=_signal_colour(signal),
                    size=14,
                    line=dict(width=2, color=_signal_colour(signal)),
                ),
                hovertemplate=(
                    f"<b>{signal}</b> (live signal_engine)<br>"
                    "%{x|%Y-%m-%d}<br>"
                    "$%{y:.2f}<extra></extra>"
                ),
            ), row=row, col=col)


def _panel_sentiment(fig: go.Figure, sent_df: pd.DataFrame,
                     synthetic_df: pd.DataFrame, row: int,
                     combined_df: pd.DataFrame = None,
                     col: int = 1) -> None:
    """
    Sentiment panel with two display modes:

      * If `combined_df` is non-empty (Path-A merger output present):
        primary series is `combined_sentiment` (solid, prominent),
        with the three component streams (news / earnings / other)
        overlaid as faint toggleable lines.  Click their legend
        entries to inspect a single component.

      * If `combined_df` is empty (e.g. ETFs without SEC data, or
        any ticker pre-merger-run): fall back to the legacy raw-news
        display from `sent_df` (real) + `synthetic_df` (demo overlay).
        The caller is expected to print a stdout warning when this
        path is taken.

    Threshold bands (±0.25) and dashed reference lines are drawn in
    both modes, unchanged.
    """
    bull_thresh = config.SIGNAL_PARAMS["bullish_sentiment_threshold"]
    bear_thresh = config.SIGNAL_PARAMS["bearish_sentiment_threshold"]

    # Threshold band (shaded region between -0.25 and +0.25)
    fig.add_hrect(
        y0=bear_thresh, y1=bull_thresh,
        fillcolor=COLOUR_THRESH, line_width=0,
        row=row, col=col,
    )
    for val in [bull_thresh, bear_thresh]:
        fig.add_hline(
            y=val, line_dash="dash", line_color="gray", line_width=1,
            row=row, col=col,
        )

    if combined_df is not None and not combined_df.empty:
        # --- Path A 3-stream display ---
        # Drop rows where combined is NaN to avoid line breaks at the
        # leading edge of the series (merger emits NaN for grid days
        # before the earliest available source).
        cdf = combined_df.dropna(subset=["combined_sentiment"]).copy()
        if not cdf.empty:
            fig.add_trace(go.Scatter(
                x=cdf["date"],
                y=cdf["combined_sentiment"],
                mode="lines",
                name="Combined sentiment",
                line=dict(color=COLOUR_SENT, width=2.5),
                hovertemplate=("%{x|%Y-%m-%d}<br>"
                               "Combined: %{y:.4f}"
                               "<extra>0.50*news + 0.35*earnings + 0.15*other</extra>"),
            ), row=row, col=col)

        # Component overlays -- faint, toggle-by-click via Plotly legend.
        # Set visible="legendonly" to start hidden; user clicks the legend
        # entry to reveal.  This keeps the default view clean while making
        # decomposition one click away.
        components = [
            ("news_sentiment",         "News (raw, w=0.50)",       "#6baed6"),
            ("sec_earnings_sentiment", "SEC earnings (w=0.35)",    "#fdae6b"),
            ("sec_other_sentiment",    "SEC other / EDGAR (w=0.15)", "#bcbddc"),
        ]
        for col_name, legend_name, line_color in components:
            if col_name not in combined_df.columns:
                continue
            sub = combined_df.dropna(subset=[col_name])
            if sub.empty:
                continue
            fig.add_trace(go.Scatter(
                x=sub["date"],
                y=sub[col_name],
                mode="lines",
                name=legend_name,
                line=dict(color=line_color, width=1.0, dash="dot"),
                opacity=0.7,
                visible="legendonly",
                hovertemplate=(f"%{{x|%Y-%m-%d}}<br>"
                               f"{legend_name}: %{{y:.4f}}"
                               f"<extra></extra>"),
            ), row=row, col=col)
        return

    # --- Legacy fallback: raw-news display ---
    if not synthetic_df.empty:
        fig.add_trace(go.Scatter(
            x=synthetic_df["date"],
            y=synthetic_df["sentiment_score"],
            mode="lines",
            name="Sentiment (demo)",
            line=dict(color=COLOUR_SENT, width=1.5, dash="dot"),
            opacity=0.6,
            hovertemplate="%{x|%Y-%m-%d}<br>Score: %{y:.4f}<extra>demo</extra>",
        ), row=row, col=col)

    if not sent_df.empty:
        fig.add_trace(go.Scatter(
            x=sent_df["date"],
            y=sent_df["sentiment_score"],
            mode="lines+markers",
            name="Sentiment (raw news)",
            line=dict(color=COLOUR_SENT, width=2),
            marker=dict(size=6),
            hovertemplate="%{x|%Y-%m-%d}<br>Score: %{y:.4f}<extra>raw news</extra>",
        ), row=row, col=col)


def _panel_iv_rank(
    fig: go.Figure,
    price_df: pd.DataFrame,
    row: int,
    real_iv_today: float = None,
) -> None:
    """
    IV Rank over time + 0.30/0.70 threshold bands.
    If real_iv_today is provided, a horizontal reference line shows where
    today's real IV sits on the same scale as the proxy series.
    """
    iv_lo = config.SIGNAL_PARAMS["low_iv_rank_threshold"]
    iv_hi = config.SIGNAL_PARAMS["high_iv_rank_threshold"]

    fig.add_hrect(y0=0,     y1=iv_lo, fillcolor="rgba(44,160,44,0.08)",  line_width=0, row=row, col=1)
    fig.add_hrect(y0=iv_hi, y1=1,     fillcolor="rgba(214,39,40,0.08)",  line_width=0, row=row, col=1)

    for val in [iv_lo, iv_hi]:
        fig.add_hline(y=val, line_dash="dash", line_color="gray",
                      line_width=1, row=row, col=1)

    fig.add_trace(go.Scatter(
        x=price_df.index,
        y=price_df["iv_rank"],
        mode="lines",
        name="IV Rank (proxy)",
        line=dict(color=COLOUR_IV, width=1.5),
        fill="tozeroy",
        fillcolor="rgba(227,119,194,0.12)",
        hovertemplate="%{x|%Y-%m-%d}<br>IV Rank: %{y:.1%}<extra>proxy</extra>",
    ), row=row, col=1)

    # If we have today's real IV rank, draw a distinct point so the user can
    # see how much it differs from the proxy series.
    if real_iv_today is not None:
        today_ts = pd.Timestamp("today").normalize()
        fig.add_trace(go.Scatter(
            x=[today_ts],
            y=[real_iv_today],
            mode="markers",
            name="IV Rank (real IV)",
            marker=dict(symbol="diamond", size=12,
                        color=COLOUR_IV_CRUSH, line=dict(width=1, color="white")),
            hovertemplate=f"Today real IV rank: {real_iv_today:.1%}<extra></extra>",
        ), row=row, col=1)


def _panel_pnl(fig: go.Figure, trades: pd.DataFrame, row: int) -> None:
    """Cumulative P&L curve with colour-fill above/below zero."""
    if trades.empty:
        fig.add_annotation(
            text="No trades — NEUTRAL throughout",
            xref="paper", yref="paper", x=0.5, y=0.5,
            showarrow=False, font=dict(size=12, color="gray"),
            row=row, col=1,
        )
        return

    cum = cumulative_pnl_series(trades).reset_index()
    cum.columns = ["date", "cum_pnl"]
    cum["date"] = pd.to_datetime(cum["date"])

    # Positive and negative fills
    fig.add_trace(go.Scatter(
        x=cum["date"], y=cum["cum_pnl"].clip(lower=0),
        mode="none", fill="tozeroy",
        fillcolor="rgba(44,160,44,0.20)",
        showlegend=False,
        hoverinfo="skip",
    ), row=row, col=1)
    fig.add_trace(go.Scatter(
        x=cum["date"], y=cum["cum_pnl"].clip(upper=0),
        mode="none", fill="tozeroy",
        fillcolor="rgba(214,39,40,0.20)",
        showlegend=False,
        hoverinfo="skip",
    ), row=row, col=1)
    # Main line
    fig.add_trace(go.Scatter(
        x=cum["date"], y=cum["cum_pnl"],
        mode="lines+markers",
        name="Cumulative P&L",
        line=dict(
            color=COLOUR_PNL_POS if cum["cum_pnl"].iloc[-1] >= 0 else COLOUR_PNL_NEG,
            width=2,
        ),
        marker=dict(size=5),
        hovertemplate="%{x|%Y-%m-%d}<br>P&L: $%{y:+.2f}/share<extra></extra>",
    ), row=row, col=1)

    # Zero baseline
    fig.add_hline(y=0, line_dash="solid", line_color="lightgray",
                  line_width=1, row=row, col=1)


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_dashboard(
    ticker: str,
    demo_mode: bool = False,
    open_browser: bool = True,
    output_path: str = None,
) -> str:
    """
    Build the 4-panel interactive dashboard and save it as HTML.

    Parameters
    ----------
    ticker      : stock symbol
    demo_mode   : if True, overlays synthetic sentiment data
    open_browser: if True, auto-opens the HTML file after saving
    output_path : explicit destination.  When None and called for a
                  single ticker, defaults to `dashboard/report.html`
                  (preserves the historic single-ticker convention).
                  Multi-ticker callers (main.py iterating
                  config.TICKERS) should pass a per-ticker name like
                  `dashboard/report_{TICKER}.html` to avoid clobber.

    Returns
    -------
    str -- path to the saved HTML file
    """
    print(f"\n[dashboard] Building report for {ticker}...")

    # --- Load data ---
    price_df   = load_price_history(ticker, period="1y")
    price_df   = price_df.tail(90)   # show last 3 months on the chart

    real_sent  = _load_sentiment_all(ticker)
    synth_sent = pd.DataFrame()
    if demo_mode:
        raw = _generate_synthetic_history(ticker, 30)
        raw.index.name = "date"
        synth_sent = raw.reset_index()
        synth_sent["date"] = pd.to_datetime(synth_sent["date"])

    trades       = _load_signals_all(ticker, demo_mode)
    combined     = _load_combined_sentiment(ticker)
    live_signals = _load_live_signals(ticker)

    if combined.empty:
        print(f"[dashboard] WARN: combined_sentiment_{ticker.upper()}.csv "
              f"not on disk -- sentiment panel falling back to raw "
              f"sentiment_{ticker.upper()}_*.csv (Path-A 3-stream blend "
              f"unavailable for this ticker).")

    # Earnings dates for shading
    try:
        earnings_dates = fetch_earnings_dates(ticker)
    except Exception as e:
        print(f"[dashboard] Could not fetch earnings dates: {e}")
        earnings_dates = []

    # Real IV rank for today's reference point on the IV panel
    real_iv_today_rank = None
    try:
        raw_dir   = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data", "raw"))
        opt_files = sorted(glob.glob(os.path.join(raw_dir, f"options_{ticker}_*.csv")))
        if opt_files:
            opt_row = pd.read_csv(opt_files[-1], nrows=1).iloc[0]
            real_iv = opt_row.get("real_iv", None)
            iv_rank = opt_row.get("iv_rank", None)
            # The iv_rank in the CSV already uses real_iv if it was available
            real_iv_today_rank = float(iv_rank) if iv_rank is not None and not pd.isna(iv_rank) \
                                  else None
    except Exception:
        pass

    # --- Plotly layout ---
    fig = make_subplots(
        rows=4, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        subplot_titles=[
            f"{ticker} Price + Signal Markers",
            "Sentiment Score  (shaded band = neutral zone)",
            "IV Rank  (green zone = cheap, red zone = expensive)",
            "Cumulative P&L per Share  (options backtest)",
        ],
        row_heights=[0.35, 0.20, 0.20, 0.25],
    )

    _panel_price(fig, price_df, trades, row=1, live_signals=live_signals)
    _panel_sentiment(fig, real_sent, synth_sent, row=2, combined_df=combined)
    _panel_iv_rank(fig,   price_df,  row=3, real_iv_today=real_iv_today_rank)
    _panel_pnl(fig,       trades,                row=4)

    # Earnings windows — shaded on all panels via vrect (paper-coordinate y span)
    _add_earnings_vrects(fig, earnings_dates, price_df)

    # --- Global styling ---
    demo_note = " — DEMO DATA (synthetic sentiment)" if demo_mode else ""
    fig.update_layout(
        title=dict(
            text=f"Options Sentiment Signal System: {ticker}{demo_note}",
            font=dict(size=18),
        ),
        height=1000,
        template="plotly_white",
        hovermode="x unified",
        legend=dict(
            orientation="h",
            yanchor="bottom", y=1.02,
            xanchor="right",  x=1,
        ),
    )

    # Y-axis labels
    fig.update_yaxes(title_text="Price ($)",   row=1, col=1)
    fig.update_yaxes(title_text="Score",       row=2, col=1, range=[-1, 1])
    fig.update_yaxes(title_text="IV Rank",     row=3, col=1,
                     tickformat=".0%", range=[0, 1])
    fig.update_yaxes(title_text="P&L ($/sh)",  row=4, col=1)
    fig.update_xaxes(title_text="Date",        row=4, col=1)

    # Remove x-axis labels from upper panels (shared axis shows them on panel 4)
    for r in [1, 2, 3]:
        fig.update_xaxes(showticklabels=False, row=r, col=1)

    # --- Save ---
    if output_path is None:
        out_dir = os.path.join(os.path.dirname(__file__))
        os.makedirs(out_dir, exist_ok=True)
        html_path = os.path.join(out_dir, "report.html")
    else:
        html_path = output_path
        os.makedirs(os.path.dirname(html_path) or ".", exist_ok=True)

    fig.write_html(
        html_path,
        include_plotlyjs=True,   # fully self-contained -- no CDN needed
        full_html=True,
    )
    print(f"[dashboard] Saved -> {html_path}")

    if open_browser:
        import webbrowser
        webbrowser.open(f"file:///{os.path.abspath(html_path)}")
        print("[dashboard] Opened in browser.")

    return html_path


# ---------------------------------------------------------------------------
# Cross-universe overview dashboard (Issue 2)
# ---------------------------------------------------------------------------
# A second, lower-resolution view that shows ALL configured tickers at
# once, grouped by asset class then by sector.  The headline strip at
# the top aggregates per-asset-class cumulative P&L from each ticker's
# backtest log -- this is the "diversification is working / not
# working" signal a recruiter or PM would actually look at first.
#
# The per-ticker grid below is small-multiples: one row per ticker, two
# columns (price + signals on the left, sentiment on the right).  We
# deliberately drop IV-Rank and the cumulative-P&L curve from each
# ticker's panel here -- the per-ticker report.html keeps those for
# anyone who wants to drill in.

# Asset-class sort order: equities first (alphabetised by sector
# inside), then commodities, then fixed income.  Recruiters reading
# top-down see the dominant exposure first.
_ASSET_CLASS_ORDER = ["Equity", "Commodity", "FixedIncome"]
# Cumulative-P&L line colour per asset class
_ASSET_CLASS_COLOUR = {
    "Equity":      "#4C72B0",
    "Commodity":   "#dd8452",
    "FixedIncome": "#55a868",
}


def _ordered_tickers(tickers: list) -> list:
    """Sort tickers by (asset_class_order, sector, ticker) for the grid."""
    sector_map = getattr(config, "SECTOR_MAP", {})
    asset_map  = getattr(config, "ASSET_CLASS", {})

    def key(t):
        ac  = asset_map.get(t, "Equity")
        ac_idx = (_ASSET_CLASS_ORDER.index(ac)
                  if ac in _ASSET_CLASS_ORDER else len(_ASSET_CLASS_ORDER))
        sec = sector_map.get(t, "")
        return (ac_idx, sec, t)
    return sorted(tickers, key=key)


def _per_ticker_combined(ticker: str) -> pd.DataFrame:
    """
    Return a (date, sentiment) frame to plot in the overview's small-
    multiples sentiment panel.  Prefers `combined_sentiment` from the
    Path-A merger, falls back to `sent_df["sentiment_score"]` aggregated
    by date when combined isn't on disk.
    """
    combined = _load_combined_sentiment(ticker)
    if not combined.empty and "combined_sentiment" in combined.columns:
        out = combined.dropna(subset=["combined_sentiment"]).copy()
        out = out.rename(columns={"combined_sentiment": "sentiment"})
        return out[["date", "sentiment"]]
    raw = _load_sentiment_all(ticker)
    if raw.empty:
        return pd.DataFrame(columns=["date", "sentiment"])
    g = raw.groupby("date", as_index=False)["sentiment_score"].mean()
    g = g.rename(columns={"sentiment_score": "sentiment"})
    return g


def _asset_class_pnl_curve(
    tickers_in_class: list, demo_mode: bool,
) -> pd.DataFrame:
    """
    Aggregate cumulative P&L across all tickers in an asset class.

    For each ticker we load the backtest trade log, sum dollar P&L by
    entry_date, then merge across tickers and forward-cumsum.  Returns
    columns: date, cum_pnl.  Empty DataFrame if no tickers have
    backtest logs on disk.
    """
    pieces = []
    for t in tickers_in_class:
        trades = load_trade_log(t, demo_mode)
        if trades.empty:
            continue
        if "pnl_total" in trades.columns:
            pnl_col = "pnl_total"
        elif "pnl" in trades.columns:
            # backtest engine stores per-share P&L in `pnl`; convert
            # to dollar P&L using 100-share contract multiplier
            trades = trades.copy()
            trades["pnl_total"] = trades["pnl"].fillna(0.0) * 100.0
            pnl_col = "pnl_total"
        else:
            continue
        ed = pd.to_datetime(trades["entry_date"])
        per_day = pd.DataFrame({"date": ed,
                                 "pnl": trades[pnl_col].fillna(0.0)})
        per_day = per_day.groupby("date", as_index=False)["pnl"].sum()
        pieces.append(per_day)
    if not pieces:
        return pd.DataFrame(columns=["date", "cum_pnl"])
    merged = pd.concat(pieces, ignore_index=True)
    merged = merged.groupby("date", as_index=False)["pnl"].sum().sort_values("date")
    merged["cum_pnl"] = merged["pnl"].cumsum()
    return merged[["date", "cum_pnl"]]


def build_overview_dashboard(
    tickers:     list,
    demo_mode:   bool = False,
    output_path: str  = None,
    open_browser: bool = True,
) -> str:
    """
    Build the cross-universe overview HTML and save it.

    Layout (top to bottom):
      * Row 1 (full width): cumulative P&L by asset class (one line
        per asset class on a single panel).
      * Rows 2..N+1: small-multiples grid, one row per ticker
        (sorted by asset_class then sector), with two columns:
          - col 1: price + backtest signal markers (filled) + live
                   signal markers (outlined)
          - col 2: combined_sentiment line (with raw-news fallback
                   when combined isn't on disk for that ticker), plus
                   the ±0.25 threshold band.

    Parameters
    ----------
    tickers      : iterable of ticker symbols to include
    demo_mode    : pass-through to ticker loaders / synthetic overlay
    output_path  : explicit output path; defaults to dashboard/overview.html
    open_browser : auto-open after saving
    """
    if output_path is None:
        output_path = os.path.join(os.path.dirname(__file__), "overview.html")

    tickers = _ordered_tickers(list(tickers))
    asset_map  = getattr(config, "ASSET_CLASS", {})
    sector_map = getattr(config, "SECTOR_MAP", {})

    print(f"\n[dashboard] Building cross-universe overview for "
          f"{len(tickers)} tickers...")

    n = len(tickers)
    rows = 1 + n          # row 1 = asset-class strip; rows 2..n+1 = per-ticker
    # Row 1 spans both columns; per-ticker rows have 2 cols (price + sentiment)
    specs = [[{"colspan": 2}, None]] + [[{}, {}] for _ in range(n)]

    subplot_titles = ["Cumulative P&L by asset class (sum across all tickers in class)"]
    for t in tickers:
        sec = sector_map.get(t, "?")
        ac  = asset_map.get(t, "?")
        subplot_titles.append(f"{t} -- price + signals  [{sec} / {ac}]")
        subplot_titles.append(f"{t} -- combined sentiment")

    fig = make_subplots(
        rows=rows, cols=2,
        specs=specs,
        subplot_titles=subplot_titles,
        vertical_spacing=0.012,
        horizontal_spacing=0.06,
        row_heights=[0.18] + [(1 - 0.18) / n] * n,
    )

    # --- Row 1: per-asset-class cumulative P&L ---
    classes_present = []
    for ac in _ASSET_CLASS_ORDER:
        in_class = [t for t in tickers if asset_map.get(t) == ac]
        if not in_class:
            continue
        curve = _asset_class_pnl_curve(in_class, demo_mode)
        if curve.empty:
            continue
        classes_present.append(ac)
        fig.add_trace(go.Scatter(
            x=curve["date"], y=curve["cum_pnl"],
            mode="lines",
            name=f"{ac} ({len(in_class)} tickers)",
            line=dict(color=_ASSET_CLASS_COLOUR.get(ac, "#666"), width=2.5),
            hovertemplate=("%{x|%Y-%m-%d}<br>"
                           f"{ac} cum P&L: $%{{y:+,.0f}}<extra></extra>"),
        ), row=1, col=1)
    fig.add_hline(y=0, line_dash="solid", line_color="lightgray",
                  line_width=1, row=1, col=1)

    # --- Rows 2..n+1: per-ticker small-multiples ---
    for i, ticker in enumerate(tickers):
        row = i + 2

        try:
            price_df = load_price_history(ticker, period="1y").tail(180)
        except Exception as e:
            print(f"[dashboard] price fetch failed for {ticker}: {e} -- skipping")
            continue

        trades       = _load_signals_all(ticker, demo_mode)
        live_signals = _load_live_signals(ticker)
        sent_for_panel = _per_ticker_combined(ticker)

        # Price + signals on the left
        _panel_price(fig, price_df, trades, row=row,
                     live_signals=live_signals, col=1)

        # Sentiment line + threshold band on the right
        bull = config.SIGNAL_PARAMS["bullish_sentiment_threshold"]
        bear = config.SIGNAL_PARAMS["bearish_sentiment_threshold"]
        fig.add_hrect(y0=bear, y1=bull,
                      fillcolor=COLOUR_THRESH, line_width=0,
                      row=row, col=2)
        for v in [bull, bear]:
            fig.add_hline(y=v, line_dash="dash", line_color="gray",
                          line_width=1, row=row, col=2)
        if not sent_for_panel.empty:
            fig.add_trace(go.Scatter(
                x=sent_for_panel["date"], y=sent_for_panel["sentiment"],
                mode="lines",
                name=f"{ticker} sentiment",
                line=dict(color=COLOUR_SENT, width=1.6),
                showlegend=False,
                hovertemplate=(f"<b>{ticker}</b><br>"
                               "%{x|%Y-%m-%d}<br>"
                               "Sentiment: %{y:.4f}<extra></extra>"),
            ), row=row, col=2)

        fig.update_yaxes(title_text="", row=row, col=1)
        fig.update_yaxes(title_text="", row=row, col=2, range=[-1, 1])
        if row != rows:
            fig.update_xaxes(showticklabels=False, row=row, col=1)
            fig.update_xaxes(showticklabels=False, row=row, col=2)

    # --- Layout ---
    demo_note = " -- DEMO DATA" if demo_mode else ""
    fig.update_layout(
        title=dict(
            text=(f"Options Sentiment System -- Cross-Universe Overview "
                  f"({len(tickers)} tickers, "
                  f"{len(classes_present)} asset classes){demo_note}"),
            font=dict(size=18),
        ),
        height=max(900, 220 + 120 * n),
        template="plotly_white",
        hovermode="closest",
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom", y=1.005,
            xanchor="right",  x=1,
            font=dict(size=10),
        ),
    )
    fig.update_yaxes(title_text="Cum P&L ($)", row=1, col=1)
    # Tighten subplot-title font size so they're not visually overwhelming
    for ann in fig.layout.annotations:
        ann.font = dict(size=10)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fig.write_html(
        output_path,
        include_plotlyjs=True,
        full_html=True,
    )
    print(f"[dashboard] Saved -> {output_path}")

    if open_browser:
        import webbrowser
        webbrowser.open(f"file:///{os.path.abspath(output_path)}")
        print("[dashboard] Opened in browser.")

    return output_path


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    demo = "--demo" in sys.argv
    overview = "--overview" in sys.argv
    if overview:
        build_overview_dashboard(config.TICKERS,
                                 demo_mode=demo, open_browser=True)
    else:
        build_dashboard("AAPL", demo_mode=demo, open_browser=True)

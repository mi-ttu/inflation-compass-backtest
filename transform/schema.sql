-- Inflation Compass Backtest — curated (silver) + feature (gold) schema
-- Bronze layer is raw files on disk (data/raw/), not tables — see ingest/.

-- ============================================================
-- SILVER: curated, calendar-aligned, source-typed tables
-- ============================================================

-- Canonical NYSE trading-day calendar. Every other silver table is
-- reindexed onto this so joins are always date-exact, never fuzzy.
CREATE TABLE IF NOT EXISTS trading_calendar (
    trading_date DATE PRIMARY KEY
);

-- Raw daily OHLC + vendor adjusted close, one row per (ticker, date).
-- vendor_adj_close is kept for reconciliation only — it is NOT the
-- series used for return calculations (see total_return_index below).
CREATE TABLE IF NOT EXISTS equity_prices (
    ticker          VARCHAR NOT NULL,
    trading_date    DATE NOT NULL,
    open            DOUBLE,
    high            DOUBLE,
    low             DOUBLE,
    close           DOUBLE NOT NULL,       -- raw unadjusted close
    volume          BIGINT,
    vendor_adj_close DOUBLE,               -- yfinance 'Adj Close', for reconciliation
    source          VARCHAR NOT NULL,      -- e.g. 'yfinance'
    PRIMARY KEY (ticker, trading_date)
);

-- Dividend / distribution events, the raw ingredient for our own
-- total-return reconstruction (never inferred from adjusted close alone).
CREATE TABLE IF NOT EXISTS equity_dividends (
    ticker      VARCHAR NOT NULL,
    ex_date     DATE NOT NULL,
    amount      DOUBLE NOT NULL,
    source      VARCHAR NOT NULL,
    PRIMARY KEY (ticker, ex_date)
);

-- Our own reconstructed total-return index per ticker: cumulative
-- product of (1 + raw price return + dividend yield on ex-date),
-- rebased to 1.0 at each ticker's first available date.
-- Built in transform/, not computed on the fly in the backtest.
CREATE TABLE IF NOT EXISTS total_return_index (
    ticker              VARCHAR NOT NULL,
    trading_date        DATE NOT NULL,
    total_return_index  DOUBLE NOT NULL,
    daily_total_return   DOUBLE NOT NULL,
    is_forward_filled    BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (ticker, trading_date)
);

-- FRED daily/macro series (T5YIE, and CPI current-vintage convenience copy).
-- observation_date = date the value applies to.
-- release_date     = date FRED actually published/updated that value
--                     (same-day for T5YIE; matters more once ALFRED
--                     vintages are added for CPI).
-- is_forward_filled marks days where FRED had no new print (e.g. bond
-- market holiday that isn't an NYSE holiday) and we carried the prior
-- value forward onto the NYSE calendar.
CREATE TABLE IF NOT EXISTS fred_series (
    series_id           VARCHAR NOT NULL,   -- 'T5YIE', 'CPIAUCSL', etc.
    observation_date    DATE NOT NULL,
    release_date        DATE,
    value                DOUBLE,
    is_forward_filled    BOOLEAN NOT NULL DEFAULT FALSE,
    source               VARCHAR NOT NULL DEFAULT 'FRED',
    PRIMARY KEY (series_id, observation_date)
);

-- Point-in-time CPI vintages from ALFRED, used only for the post-hoc
-- "does it respond to inflation" validation table — never for the
-- trading signal itself.
CREATE TABLE IF NOT EXISTS cpi_vintages (
    observation_date DATE NOT NULL,   -- the month the CPI value describes
    vintage_date      DATE NOT NULL,   -- the ALFRED vintage (as-of publish date)
    value              DOUBLE NOT NULL,
    PRIMARY KEY (observation_date, vintage_date)
);

-- Fama-French 12 Industry Portfolios (value-weighted, daily), from Ken
-- French's Data Library. Used as a free, public pre-1998 proxy for
-- sector/industry returns -- see transform/build_signals_extended.py for
-- the documented industry-to-sector mapping.
CREATE TABLE IF NOT EXISTS famafrench_industry_returns (
    industry        VARCHAR NOT NULL,   -- 'NoDur','Durbl','Manuf','Enrgy','Chems','BusEq','Telcm','Utils','Shops','Hlth','Money','Other'
    trading_date    DATE NOT NULL,
    daily_return    DOUBLE NOT NULL,     -- decimal (e.g. 0.0164, not 1.64)
    weighting       VARCHAR NOT NULL DEFAULT 'value_weighted',
    source          VARCHAR NOT NULL DEFAULT 'ken_french_data_library',
    PRIMARY KEY (industry, trading_date)
);

-- Ingestion audit trail: what was pulled, when, from where.
CREATE TABLE IF NOT EXISTS ingestion_log (
    ingestion_id    BIGINT PRIMARY KEY,
    source          VARCHAR NOT NULL,      -- 'fred', 'yfinance', etc.
    identifier      VARCHAR NOT NULL,      -- ticker or series_id
    endpoint        VARCHAR,
    pulled_at        TIMESTAMP NOT NULL,
    date_range_start DATE,
    date_range_end   DATE,
    row_count        BIGINT,
    raw_file_path     VARCHAR NOT NULL     -- pointer back to data/raw/ bronze file
);

-- ============================================================
-- GOLD: derived signals and regime history
-- ============================================================

-- Daily signal values, computed in a strict forward-only pass
-- (no row may reference data beyond its own trading_date).
CREATE TABLE IF NOT EXISTS signals_daily (
    trading_date            DATE PRIMARY KEY,
    spy_close                DOUBLE,
    spy_sma_200               DOUBLE,
    growth_up                 BOOLEAN,        -- SPY > 200-day SMA
    t5yie                      DOUBLE,
    t5yie_60d_ago               DOUBLE,
    breakeven_momentum_up        BOOLEAN,        -- T5YIE > T5YIE 60 trading days ago
    breakeven_above_target        BOOLEAN,        -- T5YIE > 2.0%
    sector_basket_ratio            DOUBLE,         -- positive-basket / negative-basket cum. growth
    sector_basket_slope_60d          DOUBLE,         -- 60-day OLS slope on sector_basket_ratio
    asset_momentum_up                  BOOLEAN,
    inflation_on                        BOOLEAN         -- breakeven_above_target AND (breakeven_momentum_up OR asset_momentum_up)
);

-- One row per month-end decision date: the regime call and resulting holding.
CREATE TABLE IF NOT EXISTS regime_history (
    decision_date    DATE PRIMARY KEY,        -- last trading day of the month
    growth_up         BOOLEAN NOT NULL,
    inflation_on       BOOLEAN NOT NULL,
    regime              VARCHAR NOT NULL,        -- 'reflation' | 'goldilocks' | 'stagflation' | 'disinflationary_slowdown'
    holding               VARCHAR NOT NULL         -- 'XLE' | 'XLK' | 'XLU' | 'XLP+IEF_5050'
);

-- ============================================================
-- GOLD (Enhanced variant): parameter-diversified ("ensembled") signals,
-- per AllocateSmartly's description of Varadi's "Enhanced" Inflation
-- Compass -- see transform/build_signals_enhanced.py for the exact
-- ensembling design and the assumptions it documents (Varadi's own exact
-- algorithm isn't public; this is our own defensible reconstruction from
-- AllocateSmartly's description).
-- ============================================================

CREATE TABLE IF NOT EXISTS signals_daily_enhanced (
    trading_date                        DATE PRIMARY KEY,
    spy_close                            DOUBLE,
    spy_sma_200                           DOUBLE,
    growth_up                             BOOLEAN,        -- SPY > 200-day SMA (unchanged from Original)
    t5yie                                  DOUBLE,
    breakeven_above_target                  BOOLEAN,        -- T5YIE > 2.0% (unchanged from Original)
    breakeven_momentum_up_40                  BOOLEAN,        -- T5YIE > T5YIE 40 trading days ago
    breakeven_momentum_up_60                    BOOLEAN,        -- T5YIE > T5YIE 60 trading days ago
    breakeven_momentum_up_80                      BOOLEAN,        -- T5YIE > T5YIE 80 trading days ago
    breakeven_momentum_up_ensemble_frac              DOUBLE,         -- fraction of {40,60,80} windows that were True
    breakeven_momentum_up_enhanced                     BOOLEAN,        -- majority vote (frac > 0.5)
    asset_momentum_slope_40                              DOUBLE,
    asset_momentum_slope_60                                DOUBLE,
    asset_momentum_slope_80                                  DOUBLE,
    asset_momentum_up_ensemble_frac                            DOUBLE,         -- fraction of {40,60,80} slopes that were positive
    asset_momentum_up_enhanced                                   BOOLEAN,        -- majority vote (frac > 0.5)
    inflation_on                                                   BOOLEAN         -- breakeven_above_target AND (breakeven_momentum_up_enhanced OR asset_momentum_up_enhanced)
);

CREATE TABLE IF NOT EXISTS regime_history_enhanced (
    decision_date    DATE PRIMARY KEY,
    growth_up         BOOLEAN NOT NULL,
    inflation_on       BOOLEAN NOT NULL,
    regime              VARCHAR NOT NULL,
    holding               VARCHAR NOT NULL
);

-- ============================================================
-- GOLD (Extended variant): 1990+ reconstruction replicating what
-- AllocateSmartly describes doing -- see transform/build_signals_extended.py
-- for the full splicing methodology and documented substitutions
-- (EXPINF5YR for T5YIE pre-2003, Fama-French 12 industries for the SPDR
-- sector basket pre-1998, chained not independently-rebased at the
-- splice). Data before 2003-01-02 is out-of-sample for the Original
-- model, same framing AllocateSmartly uses.
-- ============================================================

CREATE TABLE IF NOT EXISTS signals_daily_extended (
    trading_date               DATE PRIMARY KEY,
    spy_close                   DOUBLE,         -- ^GSPC price throughout (no splice needed here)
    spy_sma_200                  DOUBLE,
    growth_up                     BOOLEAN,
    inflation_signal_source         VARCHAR,        -- 'EXPINF5YR_proxy' (pre-2003) or 'T5YIE' (real, 2003+)
    inflation_level                  DOUBLE,         -- whichever series is active that day
    breakeven_above_target             BOOLEAN,
    breakeven_momentum_up                 BOOLEAN,
    sector_basket_ratio                     DOUBLE,         -- chained across the Fama-French / SPDR splice
    sector_basket_slope_60d                   DOUBLE,
    asset_momentum_up                           BOOLEAN,
    inflation_on                                  BOOLEAN
);

CREATE TABLE IF NOT EXISTS regime_history_extended (
    decision_date    DATE PRIMARY KEY,
    growth_up         BOOLEAN NOT NULL,
    inflation_on       BOOLEAN NOT NULL,
    regime              VARCHAR NOT NULL,
    holding               VARCHAR NOT NULL
);

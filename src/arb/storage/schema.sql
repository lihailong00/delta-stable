CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    exchange TEXT NOT NULL,
    symbol TEXT NOT NULL,
    market_type TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity TEXT NOT NULL,
    price TEXT,
    status TEXT NOT NULL,
    client_order_id TEXT,
    filled_quantity TEXT NOT NULL,
    average_price TEXT,
    reduce_only INTEGER NOT NULL DEFAULT 0,
    raw_status TEXT,
    ts TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fills (
    fill_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    exchange TEXT NOT NULL,
    symbol TEXT NOT NULL,
    market_type TEXT,
    side TEXT NOT NULL,
    quantity TEXT NOT NULL,
    price TEXT NOT NULL,
    fee TEXT,
    fee_asset TEXT,
    ts TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS positions (
    exchange TEXT NOT NULL,
    symbol TEXT NOT NULL,
    market_type TEXT NOT NULL,
    direction TEXT NOT NULL,
    quantity TEXT NOT NULL,
    entry_price TEXT NOT NULL,
    mark_price TEXT NOT NULL,
    unrealized_pnl TEXT NOT NULL,
    liquidation_price TEXT,
    leverage TEXT,
    margin_mode TEXT,
    position_id TEXT,
    ts TEXT NOT NULL,
    PRIMARY KEY (exchange, symbol, market_type, direction)
);

CREATE TABLE IF NOT EXISTS funding_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exchange TEXT NOT NULL,
    symbol TEXT NOT NULL,
    rate TEXT NOT NULL,
    predicted_rate TEXT,
    next_funding_time TEXT NOT NULL,
    ts TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_funding_exchange_symbol_ts
    ON funding_snapshots (exchange, symbol, ts DESC);

CREATE TABLE IF NOT EXISTS ticks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exchange TEXT NOT NULL,
    symbol TEXT NOT NULL,
    market_type TEXT NOT NULL,
    bid TEXT NOT NULL,
    ask TEXT NOT NULL,
    last TEXT NOT NULL,
    ts TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workflow_state (
    workflow_id TEXT PRIMARY KEY,
    workflow_type TEXT NOT NULL,
    exchange TEXT NOT NULL,
    symbol TEXT NOT NULL,
    status TEXT NOT NULL,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS order_status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL,
    exchange TEXT NOT NULL,
    symbol TEXT NOT NULL,
    market_type TEXT NOT NULL,
    status TEXT NOT NULL,
    filled_quantity TEXT NOT NULL,
    ts TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_workflow_state_status_updated_at
    ON workflow_state (status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_order_status_history_order_id_ts
    ON order_status_history (order_id, ts DESC);

from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path
from typing import Any

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS scans (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  market_limit INTEGER NOT NULL,
  notes TEXT
);
CREATE TABLE IF NOT EXISTS signals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scan_id INTEGER NOT NULL,
  ticker TEXT NOT NULL,
  title TEXT NOT NULL,
  city TEXT,
  target_date TEXT,
  target_hour INTEGER,
  variable TEXT,
  threshold REAL,
  raw_forecast_value REAL,
  forecast_value REAL,
  forecast_sigma REAL,
  model_source TEXT,
  bias_correction REAL,
  bias_correction_n INTEGER,
  bias_mae REAL,
  probability_yes REAL,
  fair_yes_cents REAL,
  fair_no_cents REAL,
  yes_bid_cents REAL,
  yes_ask_cents REAL,
  yes_ask_size REAL,
  no_bid_cents REAL,
  no_ask_cents REAL,
  no_ask_size REAL,
  selected_side TEXT,
  selected_price_cents REAL,
  edge_cents REAL,
  fee_cents REAL,
  fee_adjusted_ev_cents REAL,
  skipped_reason TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(scan_id) REFERENCES scans(id)
);
CREATE TABLE IF NOT EXISTS paper_orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scan_id INTEGER NOT NULL,
  signal_id INTEGER NOT NULL,
  ticker TEXT NOT NULL,
  side TEXT NOT NULL,
  quantity INTEGER NOT NULL,
  limit_price_cents REAL NOT NULL,
  avg_fill_price_cents REAL,
  fee_cents REAL,
  status TEXT NOT NULL,
  reason TEXT,
  settlement_status TEXT,
  settlement_result TEXT,
  settled_at TEXT,
  payout_cents REAL,
  realized_pnl_cents REAL,
  settlement_json TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(scan_id) REFERENCES scans(id),
  FOREIGN KEY(signal_id) REFERENCES signals(id)
);
CREATE TABLE IF NOT EXISTS paper_positions (
  ticker TEXT NOT NULL,
  side TEXT NOT NULL DEFAULT 'BUY_YES',
  quantity INTEGER NOT NULL,
  avg_price_cents REAL NOT NULL,
  total_fees_cents REAL NOT NULL,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (ticker, side)
);
CREATE TABLE IF NOT EXISTS demo_orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scan_id INTEGER NOT NULL,
  signal_id INTEGER NOT NULL,
  local_order_id INTEGER,
  ticker TEXT NOT NULL,
  client_order_id TEXT NOT NULL,
  kalshi_order_id TEXT,
  side TEXT NOT NULL,
  quantity TEXT NOT NULL,
  price_dollars TEXT NOT NULL,
  status TEXT NOT NULL,
  response_json TEXT,
  error TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(scan_id) REFERENCES scans(id),
  FOREIGN KEY(signal_id) REFERENCES signals(id)
);
CREATE TABLE IF NOT EXISTS demo_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  captured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  balance_json TEXT,
  positions_json TEXT
);
CREATE TABLE IF NOT EXISTS shadow_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scan_id INTEGER NOT NULL,
  ticker TEXT NOT NULL,
  title TEXT NOT NULL,
  city TEXT,
  target_date TEXT,
  target_hour INTEGER,
  variable TEXT,
  threshold REAL,
  market_status TEXT,
  close_time TEXT,
  production_base_url TEXT,
  raw_forecast_value REAL,
  forecast_value REAL,
  forecast_sigma REAL,
  model_source TEXT,
  bias_correction REAL,
  bias_correction_n INTEGER,
  bias_mae REAL,
  probability_yes REAL,
  fair_yes_cents REAL,
  fair_no_cents REAL,
  yes_bid_cents REAL,
  yes_ask_cents REAL,
  yes_ask_size REAL,
  no_bid_cents REAL,
  no_ask_cents REAL,
  no_ask_size REAL,
  spread_cents REAL,
  selected_side TEXT,
  selected_price_cents REAL,
  edge_cents REAL,
  fee_cents REAL,
  fee_adjusted_ev_cents REAL,
  skipped_reason TEXT,
  orderbook_json TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(scan_id) REFERENCES scans(id)
);
CREATE TABLE IF NOT EXISTS shadow_orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scan_id INTEGER NOT NULL,
  snapshot_id INTEGER NOT NULL,
  ticker TEXT NOT NULL,
  side TEXT NOT NULL,
  quantity INTEGER NOT NULL,
  limit_price_cents REAL NOT NULL,
  avg_fill_price_cents REAL,
  fee_cents REAL,
  status TEXT NOT NULL,
  reason TEXT,
  settlement_status TEXT,
  settlement_result TEXT,
  settled_at TEXT,
  payout_cents REAL,
  realized_pnl_cents REAL,
  settlement_json TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(scan_id) REFERENCES scans(id),
  FOREIGN KEY(snapshot_id) REFERENCES shadow_snapshots(id)
);
CREATE TABLE IF NOT EXISTS runner_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  level TEXT NOT NULL,
  message TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS counterfactual_outcomes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  source_row_id INTEGER NOT NULL,
  ticker TEXT NOT NULL,
  selected_side TEXT,
  selected_price_cents REAL,
  fee_cents REAL,
  fee_adjusted_ev_cents REAL,
  skipped_reason TEXT,
  settlement_result TEXT,
  result_value REAL,
  payout_cents REAL,
  counterfactual_pnl_cents REAL,
  settlement_json TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(source, source_row_id)
);
"""


def _is_postgres_target(target: str) -> bool:
    """True when the store target is a Postgres connection URL rather than a file path."""
    return target.startswith("postgres://") or target.startswith("postgresql://")


class _PgRow:
    """Row that mimics ``sqlite3.Row``: supports both positional (``row[0]``) and name
    (``row["col"]``) access, and the mapping protocol so ``dict(row)`` works."""

    __slots__ = ("_cols", "_vals")

    def __init__(self, cols: list[str], vals: tuple):
        self._cols = cols
        self._vals = vals

    def __getitem__(self, key):
        if isinstance(key, (int, slice)):
            return self._vals[key]
        try:
            return self._vals[self._cols.index(key)]
        except ValueError as exc:
            raise KeyError(key) from exc

    def keys(self) -> list[str]:
        return list(self._cols)

    def get(self, key, default=None):
        try:
            return self[key]
        except (KeyError, IndexError):
            return default

    def __iter__(self):
        return iter(self._vals)

    def __len__(self) -> int:
        return len(self._vals)


def _pg_row_factory(cursor):
    cols = [c.name for c in cursor.description] if cursor.description else []

    def make_row(values):
        return _PgRow(cols, tuple(values))

    return make_row


class _PgConnection:
    """Thin adapter exposing the slice of ``sqlite3.Connection`` the Store uses, backed by
    psycopg. Translates ``?`` placeholders to ``%s`` so the existing SQL works unchanged, and
    runs in autocommit mode so reads never hold an idle transaction (important for the
    per-request dashboard) and writes persist immediately (matching the SQLite commit pattern).
    """

    def __init__(self, dsn: str):
        import psycopg  # imported lazily so SQLite-only/local use needs no psycopg

        # prepare_threshold=None disables server-side prepared statements, which are
        # incompatible with Supabase's transaction-mode (pgbouncer) pooler on port 6543.
        self._conn = psycopg.connect(
            dsn, autocommit=True, prepare_threshold=None, row_factory=_pg_row_factory
        )

    def execute(self, sql: str, params: Any = ()):  # noqa: ANN401
        cur = self._conn.cursor()
        if params:
            # Escape any literal % first, then map qmark placeholders to psycopg's %s.
            translated = sql.replace("%", "%%").replace("?", "%s")
            cur.execute(translated, tuple(params))
        else:
            cur.execute(sql)
        return cur

    def commit(self) -> None:
        # No-op: the connection runs in autocommit mode.
        return None

    def close(self) -> None:
        self._conn.close()


class Store:
    def __init__(self, path: str = "data/kalshi_weather.sqlite"):
        self.is_postgres = _is_postgres_target(path)
        if self.is_postgres:
            # Schema for Postgres is owned by the committed Supabase migration
            # (supabase/migrations/...), so we skip the SQLite SCHEMA/_migrate/PRAGMA path.
            self.path = None
            self.conn = _PgConnection(path)
        else:
            self.path = Path(path)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(self.path)
            self.conn.row_factory = sqlite3.Row
            self.conn.executescript(SCHEMA)
            self._migrate()
            self.conn.commit()

    def _json(self, obj: Any) -> Any:
        """Adapt a JSON payload for the active backend: a JSON text string for SQLite TEXT
        columns, or a psycopg ``Jsonb`` wrapper for Postgres ``jsonb`` columns. Accepts either a
        Python object or an already-serialized JSON string."""
        if obj is None:
            return None
        text = obj if isinstance(obj, str) else json.dumps(obj, default=str)
        if self.is_postgres:
            from psycopg.types.json import Jsonb

            return Jsonb(text, dumps=lambda s: s)
        return text

    def _insert(self, sql: str, params: tuple) -> int:
        """Run an INSERT and return the new row id (``RETURNING id`` on Postgres,
        ``lastrowid`` on SQLite)."""
        if self.is_postgres:
            cur = self.conn.execute(sql + " RETURNING id", params)
            row = cur.fetchone()
            return int(row[0])
        cur = self.conn.execute(sql, params)
        self.conn.commit()
        return int(cur.lastrowid)

    def _migrate(self) -> None:
        for name, ddl in {
            "fair_no_cents": "ALTER TABLE signals ADD COLUMN fair_no_cents REAL",
            "no_bid_cents": "ALTER TABLE signals ADD COLUMN no_bid_cents REAL",
            "no_ask_cents": "ALTER TABLE signals ADD COLUMN no_ask_cents REAL",
            "no_ask_size": "ALTER TABLE signals ADD COLUMN no_ask_size REAL",
            "selected_side": "ALTER TABLE signals ADD COLUMN selected_side TEXT",
            "selected_price_cents": "ALTER TABLE signals ADD COLUMN selected_price_cents REAL",
            "edge_cents": "ALTER TABLE signals ADD COLUMN edge_cents REAL",
            "band_lower": "ALTER TABLE signals ADD COLUMN band_lower REAL",
            "band_upper": "ALTER TABLE signals ADD COLUMN band_upper REAL",
            "event_ticker": "ALTER TABLE signals ADD COLUMN event_ticker TEXT",
            "lookahead_risk": "ALTER TABLE signals ADD COLUMN lookahead_risk INTEGER",
            "raw_forecast_value": "ALTER TABLE signals ADD COLUMN raw_forecast_value REAL",
            "forecast_sigma": "ALTER TABLE signals ADD COLUMN forecast_sigma REAL",
            "model_source": "ALTER TABLE signals ADD COLUMN model_source TEXT",
            "bias_correction": "ALTER TABLE signals ADD COLUMN bias_correction REAL",
            "bias_correction_n": "ALTER TABLE signals ADD COLUMN bias_correction_n INTEGER",
            "bias_mae": "ALTER TABLE signals ADD COLUMN bias_mae REAL",
        }.items():
            if not self._column_exists("signals", name):
                self.conn.execute(ddl)

        for name, ddl in {
            "settlement_status": "ALTER TABLE paper_orders ADD COLUMN settlement_status TEXT",
            "settlement_result": "ALTER TABLE paper_orders ADD COLUMN settlement_result TEXT",
            "settled_at": "ALTER TABLE paper_orders ADD COLUMN settled_at TEXT",
            "payout_cents": "ALTER TABLE paper_orders ADD COLUMN payout_cents REAL",
            "realized_pnl_cents": "ALTER TABLE paper_orders ADD COLUMN realized_pnl_cents REAL",
            "settlement_json": "ALTER TABLE paper_orders ADD COLUMN settlement_json TEXT",
            "result_value": "ALTER TABLE paper_orders ADD COLUMN result_value REAL",
        }.items():
            if not self._column_exists("paper_orders", name):
                self.conn.execute(ddl)

        for name, ddl in {
            "band_lower": "ALTER TABLE shadow_snapshots ADD COLUMN band_lower REAL",
            "band_upper": "ALTER TABLE shadow_snapshots ADD COLUMN band_upper REAL",
            "event_ticker": "ALTER TABLE shadow_snapshots ADD COLUMN event_ticker TEXT",
            "lookahead_risk": "ALTER TABLE shadow_snapshots ADD COLUMN lookahead_risk INTEGER",
            "variable": "ALTER TABLE shadow_snapshots ADD COLUMN variable TEXT",
            "threshold": "ALTER TABLE shadow_snapshots ADD COLUMN threshold REAL",
            "raw_forecast_value": "ALTER TABLE shadow_snapshots ADD COLUMN raw_forecast_value REAL",
            "forecast_sigma": "ALTER TABLE shadow_snapshots ADD COLUMN forecast_sigma REAL",
            "model_source": "ALTER TABLE shadow_snapshots ADD COLUMN model_source TEXT",
            "bias_correction": "ALTER TABLE shadow_snapshots ADD COLUMN bias_correction REAL",
            "bias_correction_n": "ALTER TABLE shadow_snapshots ADD COLUMN bias_correction_n INTEGER",
            "bias_mae": "ALTER TABLE shadow_snapshots ADD COLUMN bias_mae REAL",
        }.items():
            if not self._column_exists("shadow_snapshots", name):
                self.conn.execute(ddl)

        if not self._column_exists("shadow_orders", "result_value"):
            self.conn.execute("ALTER TABLE shadow_orders ADD COLUMN result_value REAL")

        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS counterfactual_outcomes (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              source TEXT NOT NULL,
              source_row_id INTEGER NOT NULL,
              ticker TEXT NOT NULL,
              selected_side TEXT,
              selected_price_cents REAL,
              fee_cents REAL,
              fee_adjusted_ev_cents REAL,
              skipped_reason TEXT,
              settlement_result TEXT,
              result_value REAL,
              payout_cents REAL,
              counterfactual_pnl_cents REAL,
              settlement_json TEXT,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              UNIQUE(source, source_row_id)
            )
            """
        )

        if not self._column_exists("paper_positions", "side"):
            self.conn.executescript(
                """
                ALTER TABLE paper_positions RENAME TO paper_positions_old;
                CREATE TABLE paper_positions (
                  ticker TEXT NOT NULL,
                  side TEXT NOT NULL DEFAULT 'BUY_YES',
                  quantity INTEGER NOT NULL,
                  avg_price_cents REAL NOT NULL,
                  total_fees_cents REAL NOT NULL,
                  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  PRIMARY KEY (ticker, side)
                );
                INSERT INTO paper_positions (ticker, side, quantity, avg_price_cents, total_fees_cents, updated_at)
                SELECT ticker, 'BUY_YES', quantity, avg_price_cents, total_fees_cents, updated_at FROM paper_positions_old;
                DROP TABLE paper_positions_old;
                """
            )

    def _column_exists(self, table: str, column: str) -> bool:
        return any(row[1] == column for row in self.conn.execute(f"PRAGMA table_info({table})"))

    def create_scan(self, market_limit: int, notes: str | None = None) -> int:
        return self._insert("INSERT INTO scans (market_limit, notes) VALUES (?, ?)", (market_limit, notes))

    def insert_signal(self, scan_id: int, row: dict[str, Any]) -> int:
        keys = [
            "scan_id", "ticker", "title", "city", "target_date", "target_hour", "variable", "threshold",
            "band_lower", "band_upper", "event_ticker", "lookahead_risk",
            "raw_forecast_value", "forecast_value", "forecast_sigma", "model_source", "bias_correction", "bias_correction_n", "bias_mae",
            "probability_yes", "fair_yes_cents", "fair_no_cents", "yes_bid_cents", "yes_ask_cents",
            "yes_ask_size", "no_bid_cents", "no_ask_cents", "no_ask_size", "selected_side", "selected_price_cents",
            "edge_cents", "fee_cents", "fee_adjusted_ev_cents", "skipped_reason",
        ]
        data = {**row, "scan_id": scan_id}
        return self._insert(
            f"INSERT INTO signals ({', '.join(keys)}) VALUES ({', '.join('?' for _ in keys)})",
            tuple(data.get(k) for k in keys),
        )

    def insert_order(self, scan_id: int, signal_id: int, row: dict[str, Any]) -> int:
        keys = [
            "scan_id", "signal_id", "ticker", "side", "quantity", "limit_price_cents",
            "avg_fill_price_cents", "fee_cents", "status", "reason",
        ]
        data = {**row, "scan_id": scan_id, "signal_id": signal_id}
        return self._insert(
            f"INSERT INTO paper_orders ({', '.join(keys)}) VALUES ({', '.join('?' for _ in keys)})",
            tuple(data.get(k) for k in keys),
        )

    def insert_demo_order(self, scan_id: int, signal_id: int, row: dict[str, Any]) -> int:
        keys = [
            "scan_id", "signal_id", "local_order_id", "ticker", "client_order_id", "kalshi_order_id",
            "side", "quantity", "price_dollars", "status", "response_json", "error",
        ]
        data = {**row, "scan_id": scan_id, "signal_id": signal_id}
        data["response_json"] = self._json(data.get("response_json"))
        return self._insert(
            f"INSERT INTO demo_orders ({', '.join(keys)}) VALUES ({', '.join('?' for _ in keys)})",
            tuple(data.get(k) for k in keys),
        )

    def insert_demo_snapshot(self, balance: dict[str, Any] | None, positions: dict[str, Any] | None) -> int:
        return self._insert(
            "INSERT INTO demo_snapshots (balance_json, positions_json) VALUES (?, ?)",
            (self._json(balance), self._json(positions)),
        )

    def insert_shadow_snapshot(self, scan_id: int, row: dict[str, Any]) -> int:
        keys = [
            "scan_id", "ticker", "title", "city", "target_date", "target_hour", "variable", "threshold", "market_status", "close_time",
            "band_lower", "band_upper", "event_ticker", "lookahead_risk",
            "production_base_url", "raw_forecast_value", "forecast_value", "forecast_sigma", "model_source", "bias_correction", "bias_correction_n", "bias_mae",
            "probability_yes", "fair_yes_cents", "fair_no_cents",
            "yes_bid_cents", "yes_ask_cents", "yes_ask_size", "no_bid_cents", "no_ask_cents", "no_ask_size",
            "spread_cents", "selected_side", "selected_price_cents", "edge_cents", "fee_cents",
            "fee_adjusted_ev_cents", "skipped_reason", "orderbook_json",
        ]
        data = {**row, "scan_id": scan_id}
        data["orderbook_json"] = self._json(data.get("orderbook_json"))
        return self._insert(
            f"INSERT INTO shadow_snapshots ({', '.join(keys)}) VALUES ({', '.join('?' for _ in keys)})",
            tuple(data.get(k) for k in keys),
        )

    def insert_shadow_order(self, scan_id: int, snapshot_id: int, row: dict[str, Any]) -> int:
        keys = [
            "scan_id", "snapshot_id", "ticker", "side", "quantity", "limit_price_cents",
            "avg_fill_price_cents", "fee_cents", "status", "reason",
        ]
        data = {**row, "scan_id": scan_id, "snapshot_id": snapshot_id}
        return self._insert(
            f"INSERT INTO shadow_orders ({', '.join(keys)}) VALUES ({', '.join('?' for _ in keys)})",
            tuple(data.get(k) for k in keys),
        )

    def insert_runner_event(self, level: str, message: str) -> int:
        return self._insert("INSERT INTO runner_events (level, message) VALUES (?, ?)", (level, message))

    def count_orders_today(self) -> int:
        if self.is_postgres:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM paper_orders WHERE status IN ('FILLED', 'SETTLED') AND created_at::date = current_date"
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM paper_orders WHERE status IN ('FILLED', 'SETTLED') AND date(created_at) = date('now', 'localtime')"
            ).fetchone()
        return int(row[0])

    def count_orders_since(self, ticker: str, side: str, minutes: int) -> int:
        if self.is_postgres:
            row = self.conn.execute(
                """
                SELECT COUNT(*)
                FROM paper_orders
                WHERE status IN ('FILLED', 'SETTLED')
                  AND ticker = ?
                  AND side = ?
                  AND created_at >= now() - make_interval(mins => ?)
                """,
                (ticker, side, minutes),
            ).fetchone()
        else:
            row = self.conn.execute(
                """
                SELECT COUNT(*)
                FROM paper_orders
                WHERE status IN ('FILLED', 'SETTLED')
                  AND ticker = ?
                  AND side = ?
                  AND created_at >= datetime('now', ?)
                """,
                (ticker, side, f"-{minutes} minutes"),
            ).fetchone()
        return int(row[0])

    def count_shadow_orders_today(self) -> int:
        if self.is_postgres:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM shadow_orders WHERE status IN ('SHADOW_FILLED', 'SHADOW_SETTLED') AND created_at::date = current_date"
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM shadow_orders WHERE status IN ('SHADOW_FILLED', 'SHADOW_SETTLED') AND date(created_at) = date('now', 'localtime')"
            ).fetchone()
        return int(row[0])

    def count_shadow_orders_since(self, ticker: str, side: str, minutes: int) -> int:
        if self.is_postgres:
            row = self.conn.execute(
                """
                SELECT COUNT(*)
                FROM shadow_orders
                WHERE status IN ('SHADOW_FILLED', 'SHADOW_SETTLED')
                  AND ticker = ?
                  AND side = ?
                  AND created_at >= now() - make_interval(mins => ?)
                """,
                (ticker, side, minutes),
            ).fetchone()
        else:
            row = self.conn.execute(
                """
                SELECT COUNT(*)
                FROM shadow_orders
                WHERE status IN ('SHADOW_FILLED', 'SHADOW_SETTLED')
                  AND ticker = ?
                  AND side = ?
                  AND created_at >= datetime('now', ?)
                """,
                (ticker, side, f"-{minutes} minutes"),
            ).fetchone()
        return int(row[0])

    def has_opposite_position(self, ticker: str, side: str) -> bool:
        opposite = "BUY_NO" if side == "BUY_YES" else "BUY_YES"
        row = self.conn.execute(
            "SELECT COALESCE(SUM(quantity), 0) FROM paper_orders WHERE status = 'FILLED' AND ticker = ? AND side = ? AND realized_pnl_cents IS NULL",
            (ticker, opposite),
        ).fetchone()
        return int(row[0] or 0) > 0

    def position_quantity(self, ticker: str, side: str | None = None) -> int:
        if side is None:
            row = self.conn.execute("SELECT COALESCE(SUM(quantity), 0) FROM paper_orders WHERE status = 'FILLED' AND ticker = ? AND realized_pnl_cents IS NULL", (ticker,)).fetchone()
        else:
            row = self.conn.execute("SELECT COALESCE(SUM(quantity), 0) FROM paper_orders WHERE status = 'FILLED' AND ticker = ? AND side = ? AND realized_pnl_cents IS NULL", (ticker, side)).fetchone()
        return int(row[0]) if row else 0

    def total_open_exposure_cents(self) -> float:
        row = self.conn.execute(
            """
            SELECT COALESCE(SUM(quantity * avg_fill_price_cents), 0)
            FROM paper_orders
            WHERE status = 'FILLED' AND realized_pnl_cents IS NULL
            """
        ).fetchone()
        return float(row[0] or 0.0)

    def event_order_quantity(self, event_ticker: str) -> int:
        """Contracts already placed on this correlated event, open or settled.

        This is intentionally stricter than open exposure: once the bot has tested one strike in
        a city/date/hour ladder, repeated scans should not keep adding different strikes from the
        same event. Those fills are not independent evidence; they are the same forecast call.
        """
        row = self.conn.execute(
            "SELECT COALESCE(SUM(quantity), 0) FROM paper_orders WHERE status IN ('FILLED', 'SETTLED') AND ticker LIKE ?",
            (f"{event_ticker}-%",),
        ).fetchone()
        return int(row[0]) if row else 0

    def event_position_quantity(self, event_ticker: str, side: str | None = None) -> int:
        like = f"{event_ticker}-%"
        if side is None:
            row = self.conn.execute(
                "SELECT COALESCE(SUM(quantity), 0) FROM paper_orders WHERE status = 'FILLED' AND ticker LIKE ? AND realized_pnl_cents IS NULL",
                (like,),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT COALESCE(SUM(quantity), 0) FROM paper_orders WHERE status = 'FILLED' AND ticker LIKE ? AND side = ? AND realized_pnl_cents IS NULL",
                (like, side),
            ).fetchone()
        return int(row[0]) if row else 0

    def event_open_exposure_cents(self, event_ticker: str) -> float:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(quantity * avg_fill_price_cents), 0) FROM paper_orders WHERE status = 'FILLED' AND ticker LIKE ? AND realized_pnl_cents IS NULL",
            (f"{event_ticker}-%",),
        ).fetchone()
        return float(row[0] or 0.0)

    # --- shadow_orders safety/exposure queries (mirror the paper helpers above) ---

    def shadow_has_opposite_position(self, ticker: str, side: str) -> bool:
        opposite = "BUY_NO" if side == "BUY_YES" else "BUY_YES"
        row = self.conn.execute(
            "SELECT COALESCE(SUM(quantity), 0) FROM shadow_orders WHERE status = 'SHADOW_FILLED' AND ticker = ? AND side = ? AND realized_pnl_cents IS NULL",
            (ticker, opposite),
        ).fetchone()
        return int(row[0] or 0) > 0

    def shadow_position_quantity(self, ticker: str, side: str | None = None) -> int:
        if side is None:
            row = self.conn.execute("SELECT COALESCE(SUM(quantity), 0) FROM shadow_orders WHERE status = 'SHADOW_FILLED' AND ticker = ? AND realized_pnl_cents IS NULL", (ticker,)).fetchone()
        else:
            row = self.conn.execute("SELECT COALESCE(SUM(quantity), 0) FROM shadow_orders WHERE status = 'SHADOW_FILLED' AND ticker = ? AND side = ? AND realized_pnl_cents IS NULL", (ticker, side)).fetchone()
        return int(row[0]) if row else 0

    def shadow_total_open_exposure_cents(self) -> float:
        row = self.conn.execute(
            """
            SELECT COALESCE(SUM(quantity * avg_fill_price_cents), 0)
            FROM shadow_orders
            WHERE status = 'SHADOW_FILLED' AND realized_pnl_cents IS NULL
            """
        ).fetchone()
        return float(row[0] or 0.0)

    def shadow_event_order_quantity(self, event_ticker: str) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(quantity), 0) FROM shadow_orders WHERE status IN ('SHADOW_FILLED', 'SHADOW_SETTLED') AND ticker LIKE ?",
            (f"{event_ticker}-%",),
        ).fetchone()
        return int(row[0]) if row else 0

    def shadow_event_position_quantity(self, event_ticker: str, side: str | None = None) -> int:
        like = f"{event_ticker}-%"
        if side is None:
            row = self.conn.execute(
                "SELECT COALESCE(SUM(quantity), 0) FROM shadow_orders WHERE status = 'SHADOW_FILLED' AND ticker LIKE ? AND realized_pnl_cents IS NULL",
                (like,),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT COALESCE(SUM(quantity), 0) FROM shadow_orders WHERE status = 'SHADOW_FILLED' AND ticker LIKE ? AND side = ? AND realized_pnl_cents IS NULL",
                (like, side),
            ).fetchone()
        return int(row[0]) if row else 0

    def shadow_event_open_exposure_cents(self, event_ticker: str) -> float:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(quantity * avg_fill_price_cents), 0) FROM shadow_orders WHERE status = 'SHADOW_FILLED' AND ticker LIKE ? AND realized_pnl_cents IS NULL",
            (f"{event_ticker}-%",),
        ).fetchone()
        return float(row[0] or 0.0)

    # --- model-quality helpers (bias/sigma calibration and directional risk caps) ---

    def forecast_error_stats(
        self,
        *,
        series_ticker: str,
        variable: str,
        target_hour: int | None = None,
        source: str = "both",
        lookback_days: int = 45,
        include_lookahead: bool = True,
    ) -> dict[str, float | int | None]:
        """Rolling realized forecast error stats for a series/variable/hour key.

        Error is stored as ``forecast_value - result_value``. A positive bias means the forecast
        ran warm/high and should be subtracted from the next raw forecast. Uses already-settled
        paper and/or shadow rows; no live orders are involved.
        """
        errors: list[float] = []
        requested = {source.lower()} if source.lower() in {"paper", "shadow"} else {"paper", "shadow"}
        if "paper" in requested:
            errors.extend(
                self._forecast_errors_from_join(
                    order_table="paper_orders",
                    signal_table="signals",
                    signal_fk="signal_id",
                    order_status="SETTLED",
                    series_ticker=series_ticker,
                    variable=variable,
                    target_hour=target_hour,
                    lookback_days=lookback_days,
                    include_lookahead=include_lookahead,
                    has_variable_column=True,
                )
            )
        if "shadow" in requested:
            # Historical shadow_snapshots do not have a variable column; the series prefix and
            # target-hour filter are the stable key. Future schema can add variable without
            # changing this query.
            errors.extend(
                self._forecast_errors_from_join(
                    order_table="shadow_orders",
                    signal_table="shadow_snapshots",
                    signal_fk="snapshot_id",
                    order_status="SHADOW_SETTLED",
                    series_ticker=series_ticker,
                    variable=variable,
                    target_hour=target_hour,
                    lookback_days=lookback_days,
                    include_lookahead=include_lookahead,
                    has_variable_column=False,
                )
            )
            # Verified skipped snapshots: counterfactual settlement backfill resolves markets the
            # gates refused to trade, so temperature bias/sigma can calibrate with zero fills.
            errors.extend(
                self._forecast_errors_from_counterfactuals(
                    series_ticker=series_ticker,
                    target_hour=target_hour,
                    lookback_days=lookback_days,
                    include_lookahead=include_lookahead,
                )
            )
        if not errors:
            return {"n": 0, "bias": None, "mae": None, "rmse": None}
        bias = sum(errors) / len(errors)
        mae = sum(abs(e) for e in errors) / len(errors)
        rmse = math.sqrt(sum(e * e for e in errors) / len(errors))
        return {"n": len(errors), "bias": bias, "mae": mae, "rmse": rmse}

    def _forecast_errors_from_join(
        self,
        *,
        order_table: str,
        signal_table: str,
        signal_fk: str,
        order_status: str,
        series_ticker: str,
        variable: str,
        target_hour: int | None,
        lookback_days: int,
        include_lookahead: bool,
        has_variable_column: bool,
    ) -> list[float]:
        where = [
            f"o.status = '{order_status}'",
            "o.result_value IS NOT NULL",
            "s.forecast_value IS NOT NULL",
            "o.ticker LIKE ?",
        ]
        params: list[Any] = [f"{series_ticker}-%"]
        if has_variable_column:
            where.append("s.variable = ?")
            params.append(variable)
        if target_hour is None:
            where.append("s.target_hour IS NULL")
        else:
            where.append("s.target_hour = ?")
            params.append(target_hour)
        if not include_lookahead:
            where.append("COALESCE(s.lookahead_risk, 0) = 0")
        if lookback_days > 0:
            if self.is_postgres:
                where.append("o.created_at >= now() - make_interval(days => ?)")
                params.append(lookback_days)
            else:
                where.append("o.created_at >= datetime('now', ?)")
                params.append(f"-{lookback_days} days")
        sql = f"""
            SELECT COALESCE(s.raw_forecast_value, s.forecast_value) AS fv, o.result_value AS rv
            FROM {order_table} o
            JOIN {signal_table} s ON s.id = o.{signal_fk}
            WHERE {' AND '.join(where)}
        """
        out: list[float] = []
        for row in self.conn.execute(sql, tuple(params)).fetchall():
            try:
                out.append(float(row["fv"]) - float(row["rv"]))
            except (TypeError, ValueError):
                continue
        return out

    def _forecast_errors_from_counterfactuals(
        self,
        *,
        series_ticker: str,
        target_hour: int | None,
        lookback_days: int,
        include_lookahead: bool,
    ) -> list[float]:
        """Forecast errors from settled-but-skipped shadow snapshots (counterfactual backfill).

        ``result_value`` is the best-effort settlement value extracted from the Kalshi market
        payload, same as the settled-order path; one outcome row per ticker is expected because
        candidate selection dedupes to the latest pre-close snapshot.
        """
        where = [
            "co.source = 'shadow'",
            "co.result_value IS NOT NULL",
            "co.ticker LIKE ?",
            "s.forecast_value IS NOT NULL",
        ]
        params: list[Any] = [f"{series_ticker}-%"]
        if target_hour is None:
            where.append("s.target_hour IS NULL")
        else:
            where.append("s.target_hour = ?")
            params.append(target_hour)
        if not include_lookahead:
            where.append("COALESCE(s.lookahead_risk, 0) = 0")
        if lookback_days > 0:
            if self.is_postgres:
                where.append("s.created_at >= now() - make_interval(days => ?)")
                params.append(lookback_days)
            else:
                where.append("s.created_at >= datetime('now', ?)")
                params.append(f"-{lookback_days} days")
        sql = f"""
            SELECT COALESCE(s.raw_forecast_value, s.forecast_value) AS fv, co.result_value AS rv
            FROM counterfactual_outcomes co
            JOIN shadow_snapshots s ON s.id = co.source_row_id
            JOIN (
                SELECT ticker, MAX(id) AS max_id FROM counterfactual_outcomes
                WHERE source = 'shadow' GROUP BY ticker
            ) latest ON latest.max_id = co.id
            WHERE {' AND '.join(where)}
        """
        out: list[float] = []
        for row in self.conn.execute(sql, tuple(params)).fetchall():
            try:
                out.append(float(row["fv"]) - float(row["rv"]))
            except (TypeError, ValueError):
                continue
        return out

    def same_day_directional_order_quantity(self, series_ticker: str, target_date: str, side: str) -> int:
        row = self.conn.execute(
            """
            SELECT COALESCE(SUM(o.quantity), 0)
            FROM paper_orders o
            JOIN signals s ON s.id = o.signal_id
            WHERE o.status IN ('FILLED', 'SETTLED')
              AND o.side = ?
              AND o.ticker LIKE ?
              AND s.target_date = ?
              AND s.variable = 'point_temp_f'
            """,
            (side, f"{series_ticker}-%", target_date),
        ).fetchone()
        return int(row[0] or 0)

    def adjacent_hour_directional_order_quantity(self, series_ticker: str, target_date: str, target_hour: int, side: str, window: int) -> int:
        lo = max(0, target_hour - window)
        hi = min(23, target_hour + window)
        row = self.conn.execute(
            """
            SELECT COALESCE(SUM(o.quantity), 0)
            FROM paper_orders o
            JOIN signals s ON s.id = o.signal_id
            WHERE o.status IN ('FILLED', 'SETTLED')
              AND o.side = ?
              AND o.ticker LIKE ?
              AND s.target_date = ?
              AND s.variable = 'point_temp_f'
              AND s.target_hour BETWEEN ? AND ?
            """,
            (side, f"{series_ticker}-%", target_date, lo, hi),
        ).fetchone()
        return int(row[0] or 0)

    def shadow_same_day_directional_order_quantity(self, series_ticker: str, target_date: str, side: str) -> int:
        row = self.conn.execute(
            """
            SELECT COALESCE(SUM(o.quantity), 0)
            FROM shadow_orders o
            JOIN shadow_snapshots s ON s.id = o.snapshot_id
            WHERE o.status IN ('SHADOW_FILLED', 'SHADOW_SETTLED')
              AND o.side = ?
              AND o.ticker LIKE ?
              AND s.target_date = ?
              AND s.target_hour IS NOT NULL
            """,
            (side, f"{series_ticker}-%", target_date),
        ).fetchone()
        return int(row[0] or 0)

    def shadow_adjacent_hour_directional_order_quantity(self, series_ticker: str, target_date: str, target_hour: int, side: str, window: int) -> int:
        lo = max(0, target_hour - window)
        hi = min(23, target_hour + window)
        row = self.conn.execute(
            """
            SELECT COALESCE(SUM(o.quantity), 0)
            FROM shadow_orders o
            JOIN shadow_snapshots s ON s.id = o.snapshot_id
            WHERE o.status IN ('SHADOW_FILLED', 'SHADOW_SETTLED')
              AND o.side = ?
              AND o.ticker LIKE ?
              AND s.target_date = ?
              AND s.target_hour BETWEEN ? AND ?
            """,
            (side, f"{series_ticker}-%", target_date, lo, hi),
        ).fetchone()
        return int(row[0] or 0)

    def stale_shadow_orders(self, hours_after_close: int = 6, limit: int = 40) -> list[dict[str, Any]]:
        if self.is_postgres:
            sql = """
                SELECT o.*, s.close_time, s.event_ticker, s.probability_yes, s.selected_side, s.selected_price_cents
                FROM shadow_orders o
                JOIN shadow_snapshots s ON s.id = o.snapshot_id
                WHERE o.status = 'SHADOW_FILLED'
                  AND o.realized_pnl_cents IS NULL
                  AND s.close_time IS NOT NULL
                  AND s.close_time < now() - make_interval(hours => ?)
                ORDER BY s.close_time ASC
                LIMIT ?
            """
            params = (hours_after_close, limit)
        else:
            sql = """
                SELECT o.*, s.close_time, s.event_ticker, s.probability_yes, s.selected_side, s.selected_price_cents
                FROM shadow_orders o
                JOIN shadow_snapshots s ON s.id = o.snapshot_id
                WHERE o.status = 'SHADOW_FILLED'
                  AND o.realized_pnl_cents IS NULL
                  AND s.close_time IS NOT NULL
                  AND datetime(s.close_time) < datetime('now', ?)
                ORDER BY s.close_time ASC
                LIMIT ?
            """
            params = (f"-{hours_after_close} hours", limit)
        return [dict(row) for row in self.conn.execute(sql, params).fetchall()]

    def unsettled_order_tickers(self) -> list[str]:
        return [
            str(row[0])
            for row in self.conn.execute(
                "SELECT DISTINCT ticker FROM paper_orders WHERE status = 'FILLED' AND realized_pnl_cents IS NULL ORDER BY ticker"
            ).fetchall()
        ]

    def settle_paper_orders_for_market(self, ticker: str, market: dict[str, Any]) -> int:
        result = _normalize_result(market.get("result") or market.get("expiration_value"))
        status = str(market.get("status") or "").lower()
        if result not in {"yes", "no"}:
            return 0
        settled_at = market.get("settlement_ts") or market.get("close_time")
        result_value = _result_value(market)
        rows = self.conn.execute(
            "SELECT * FROM paper_orders WHERE status = 'FILLED' AND ticker = ? AND realized_pnl_cents IS NULL",
            (ticker,),
        ).fetchall()
        count = 0
        for row in rows:
            side = str(row["side"])
            quantity = int(row["quantity"])
            won = (side == "BUY_YES" and result == "yes") or (side == "BUY_NO" and result == "no")
            payout = 100.0 * quantity if won else 0.0
            cost = (float(row["avg_fill_price_cents"] or row["limit_price_cents"]) * quantity) + float(row["fee_cents"] or 0.0)
            pnl = payout - cost
            self.conn.execute(
                """
                UPDATE paper_orders
                SET settlement_status=?, settlement_result=?, settled_at=?, payout_cents=?, realized_pnl_cents=?, settlement_json=?, status=?, result_value=?
                WHERE id=?
                """,
                (status or "settled", result.upper(), settled_at, payout, pnl, self._json(market), "SETTLED", result_value, row["id"]),
            )
            count += 1
        self.conn.commit()
        return count

    def unsettled_shadow_order_tickers(self) -> list[str]:
        return [
            str(row[0])
            for row in self.conn.execute(
                "SELECT DISTINCT ticker FROM shadow_orders WHERE status = 'SHADOW_FILLED' AND realized_pnl_cents IS NULL ORDER BY ticker"
            ).fetchall()
        ]

    def settle_shadow_orders_for_market(self, ticker: str, market: dict[str, Any]) -> int:
        result = _normalize_result(market.get("result") or market.get("expiration_value"))
        status = str(market.get("status") or "").lower()
        if result not in {"yes", "no"}:
            return 0
        settled_at = market.get("settlement_ts") or market.get("close_time")
        result_value = _result_value(market)
        rows = self.conn.execute(
            "SELECT * FROM shadow_orders WHERE status = 'SHADOW_FILLED' AND ticker = ? AND realized_pnl_cents IS NULL",
            (ticker,),
        ).fetchall()
        count = 0
        for row in rows:
            side = str(row["side"])
            quantity = int(row["quantity"])
            won = (side == "BUY_YES" and result == "yes") or (side == "BUY_NO" and result == "no")
            payout = 100.0 * quantity if won else 0.0
            cost = (float(row["avg_fill_price_cents"] or row["limit_price_cents"]) * quantity) + float(row["fee_cents"] or 0.0)
            pnl = payout - cost
            self.conn.execute(
                """
                UPDATE shadow_orders
                SET settlement_status=?, settlement_result=?, settled_at=?, payout_cents=?, realized_pnl_cents=?, settlement_json=?, status=?, result_value=?
                WHERE id=?
                """,
                (status or "settled", result.upper(), settled_at, payout, pnl, self._json(market), "SHADOW_SETTLED", result_value, row["id"]),
            )
            count += 1
        self.conn.commit()
        return count

    # Skip reasons whose snapshots are fetched regardless of model EV: gated temperature rows are
    # the calibration data that bias correction / dynamic sigma need, since the conservative gate
    # prevents any temperature fills from settling.
    COUNTERFACTUAL_ALWAYS_REASONS = ("forecast_uncertainty_exceeds_strike_spacing",)

    def counterfactual_candidates(
        self,
        *,
        source: str = "shadow",
        min_ev_cents: float = 10.0,
        limit: int = 50,
        skip_reason: str | None = None,
    ) -> list[dict[str, Any]]:
        """Skipped rows whose markets have closed and can be audited against settlement.

        One candidate per ticker, preferring the latest *non-lookahead* snapshot (newest clean
        forecast that did not peek at observed weather) and only falling back to the latest
        overall snapshot when no clean one exists. This matters: the previous latest-before-close
        selection produced exclusively ``lookahead_risk=1`` rows, which bias correction and
        dynamic sigma are configured to ignore, so the calibrate-from-skips loop fed zero rows to
        its consumers. Tickers already resolved in ``counterfactual_outcomes`` are excluded.
        Rows skipped by the forecast-uncertainty gate qualify regardless of EV; other skip
        reasons must clear ``min_ev_cents``.
        """
        table = "signals" if source == "paper" else "shadow_snapshots"
        always = list(self.COUNTERFACTUAL_ALWAYS_REASONS)
        where = [
            "skipped_reason IS NOT NULL",
            "selected_side IS NOT NULL",
            "selected_price_cents IS NOT NULL",
            "close_time IS NOT NULL",
        ]
        params: list[Any] = []
        if self.is_postgres:
            where.append("close_time::timestamptz <= now()")
        else:
            where.append("datetime(close_time) <= datetime('now')")
        reason_placeholders = ", ".join("?" for _ in always)
        where.append(f"(skipped_reason IN ({reason_placeholders}) OR fee_adjusted_ev_cents >= ?)")
        params.extend(always)
        params.append(min_ev_cents)
        if skip_reason:
            where.append("skipped_reason = ?")
            params.append(skip_reason)
        params.append(source)
        params.append(limit)
        sql = f"""
            SELECT ranked.id AS source_row_id, ranked.ticker, ranked.selected_side,
                   ranked.selected_price_cents, ranked.fee_cents, ranked.fee_adjusted_ev_cents,
                   ranked.skipped_reason
            FROM (
                SELECT t.id, t.ticker, t.selected_side, t.selected_price_cents, t.fee_cents,
                       t.fee_adjusted_ev_cents, t.skipped_reason, t.close_time,
                       ROW_NUMBER() OVER (
                           PARTITION BY t.ticker
                           ORDER BY COALESCE(t.lookahead_risk, 0) ASC, t.id DESC
                       ) AS rn
                FROM {table} t
                WHERE {' AND '.join(where)}
            ) ranked
            WHERE ranked.rn = 1
              AND NOT EXISTS (
                SELECT 1 FROM counterfactual_outcomes co
                WHERE co.source = ?
                  AND co.ticker = ranked.ticker
                  AND (co.settlement_result IS NOT NULL OR co.result_value IS NOT NULL)
            )
            ORDER BY ranked.close_time ASC
            LIMIT ?
        """
        return [dict(row) for row in self.conn.execute(sql, tuple(params)).fetchall()]

    def upsert_counterfactual_outcome(
        self,
        *,
        source: str,
        source_row_id: int,
        ticker: str,
        selected_side: str | None,
        selected_price_cents: float | None,
        fee_cents: float | None,
        fee_adjusted_ev_cents: float | None,
        skipped_reason: str | None,
        market: dict[str, Any],
    ) -> None:
        result = _normalize_result(market.get("result") or market.get("expiration_value"))
        result_value = _result_value(market)
        payout = pnl = None
        if result in {"yes", "no"} and selected_side and selected_price_cents is not None:
            won = (selected_side == "BUY_YES" and result == "yes") or (selected_side == "BUY_NO" and result == "no")
            payout = 100.0 if won else 0.0
            pnl = payout - float(selected_price_cents) - float(fee_cents or 0.0)
        payload = self._json(market)
        if self.is_postgres:
            self.conn.execute(
                """
                INSERT INTO counterfactual_outcomes (
                  source, source_row_id, ticker, selected_side, selected_price_cents, fee_cents,
                  fee_adjusted_ev_cents, skipped_reason, settlement_result, result_value, payout_cents,
                  counterfactual_pnl_cents, settlement_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, now())
                ON CONFLICT (source, source_row_id) DO UPDATE SET
                  settlement_result=EXCLUDED.settlement_result,
                  result_value=EXCLUDED.result_value,
                  payout_cents=EXCLUDED.payout_cents,
                  counterfactual_pnl_cents=EXCLUDED.counterfactual_pnl_cents,
                  settlement_json=EXCLUDED.settlement_json,
                  updated_at=now()
                """,
                (source, source_row_id, ticker, selected_side, selected_price_cents, fee_cents,
                 fee_adjusted_ev_cents, skipped_reason, result.upper() if result else None, result_value,
                 payout, pnl, payload),
            )
        else:
            self.conn.execute(
                """
                INSERT INTO counterfactual_outcomes (
                  source, source_row_id, ticker, selected_side, selected_price_cents, fee_cents,
                  fee_adjusted_ev_cents, skipped_reason, settlement_result, result_value, payout_cents,
                  counterfactual_pnl_cents, settlement_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(source, source_row_id) DO UPDATE SET
                  settlement_result=excluded.settlement_result,
                  result_value=excluded.result_value,
                  payout_cents=excluded.payout_cents,
                  counterfactual_pnl_cents=excluded.counterfactual_pnl_cents,
                  settlement_json=excluded.settlement_json,
                  updated_at=CURRENT_TIMESTAMP
                """,
                (source, source_row_id, ticker, selected_side, selected_price_cents, fee_cents,
                 fee_adjusted_ev_cents, skipped_reason, result.upper() if result else None, result_value,
                 payout, pnl, payload),
            )
            self.conn.commit()

    def counterfactual_summary(self, source: str = "shadow") -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.conn.execute(
                """
                SELECT skipped_reason, COUNT(*) AS n,
                       SUM(CASE WHEN counterfactual_pnl_cents > 0 THEN 1 ELSE 0 END) AS wins,
                       COALESCE(SUM(counterfactual_pnl_cents), 0) AS pnl_cents,
                       AVG(fee_adjusted_ev_cents) AS avg_model_ev_cents
                FROM counterfactual_outcomes
                WHERE source = ? AND counterfactual_pnl_cents IS NOT NULL
                GROUP BY skipped_reason
                ORDER BY pnl_cents DESC
                """,
                (source,),
            ).fetchall()
        ]

    def counterfactual_forecast_summary(self, source: str = "shadow") -> list[dict[str, Any]]:
        """Per-series verified forecast error from settled-but-skipped snapshots.

        This is the dashboard's "is bias correction getting data?" view: n must grow and MAE
        should be compared against the series' strike spacing.
        """
        series_expr = (
            "split_part(x.ticker, '-', 1)"
            if self.is_postgres
            else "substr(x.ticker, 1, instr(x.ticker, '-') - 1)"
        )
        sql = f"""
            SELECT {series_expr} AS series, COUNT(*) AS n,
                   AVG(x.fv - x.rv) AS bias_f,
                   AVG(ABS(x.fv - x.rv)) AS mae_f
            FROM (
                SELECT co.ticker, COALESCE(s.raw_forecast_value, s.forecast_value) AS fv,
                       co.result_value AS rv
                FROM counterfactual_outcomes co
                JOIN shadow_snapshots s ON s.id = co.source_row_id
                WHERE co.source = ? AND co.result_value IS NOT NULL AND s.forecast_value IS NOT NULL
            ) x
            GROUP BY series
            ORDER BY n DESC
        """
        return [dict(row) for row in self.conn.execute(sql, (source,)).fetchall()]

    def mark_order_demo_rejected(self, order_id: int, reason: str | None = None) -> None:
        self.conn.execute(
            "UPDATE paper_orders SET status=?, reason=? WHERE id=? AND status='FILLED'",
            ("DEMO_REJECTED", reason or "demo_order_error", order_id),
        )
        self.conn.commit()

    def upsert_position(self, ticker: str, side: str, quantity: int, price_cents: float, fee_cents: float) -> None:
        existing = self.conn.execute("SELECT * FROM paper_positions WHERE ticker = ? AND side = ?", (ticker, side)).fetchone()
        if existing:
            old_qty = int(existing["quantity"])
            new_qty = old_qty + quantity
            avg = ((old_qty * float(existing["avg_price_cents"])) + (quantity * price_cents)) / new_qty
            fees = float(existing["total_fees_cents"]) + fee_cents
            if self.is_postgres:
                self.conn.execute(
                    "UPDATE paper_positions SET quantity=?, avg_price_cents=?, total_fees_cents=?, updated_at=now() WHERE ticker=? AND side=?",
                    (new_qty, avg, fees, ticker, side),
                )
            else:
                self.conn.execute(
                    "UPDATE paper_positions SET quantity=?, avg_price_cents=?, total_fees_cents=?, updated_at=CURRENT_TIMESTAMP WHERE ticker=? AND side=?",
                    (new_qty, avg, fees, ticker, side),
                )
        else:
            self.conn.execute(
                "INSERT INTO paper_positions (ticker, side, quantity, avg_price_cents, total_fees_cents) VALUES (?, ?, ?, ?, ?)",
                (ticker, side, quantity, price_cents, fee_cents),
            )
        self.conn.commit()

    def summary(self) -> dict[str, Any]:
        return {
            "signals": self.conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0],
            "orders": self.conn.execute("SELECT COUNT(*) FROM paper_orders").fetchone()[0],
            "positions": self.conn.execute("SELECT COUNT(*) FROM paper_positions").fetchone()[0],
            "demo_orders": self.conn.execute("SELECT COUNT(*) FROM demo_orders").fetchone()[0],
            "shadow_snapshots": self.conn.execute("SELECT COUNT(*) FROM shadow_snapshots").fetchone()[0],
            "shadow_orders": self.conn.execute("SELECT COUNT(*) FROM shadow_orders").fetchone()[0],
        }


def _result_value(market: dict[str, Any]) -> float | None:
    """Best-effort realized numeric outcome (e.g. settled temperature) from a settled market."""
    for key in ("settlement_value", "settled_value", "result_value", "expiration_value"):
        value = market.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _normalize_result(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"yes", "y", "1", "true"}:
        return "yes"
    if text in {"no", "n", "0", "false"}:
        return "no"
    return None

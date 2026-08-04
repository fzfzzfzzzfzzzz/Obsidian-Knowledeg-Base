#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""SQLite cache for derived market quote data.

This is temporary/rebuildable market data. Markdown remains the source of truth
for editable watchlist items.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import kb


DB_NAME = "market_cache.sqlite"


def cache_db_path() -> Path:
    return kb.KB_DIR / "cache" / "market" / DB_NAME


def has_cache_db() -> bool:
    return cache_db_path().exists()


def _connect(*, create: bool = True) -> sqlite3.Connection | None:
    path = cache_db_path()
    if not create and not path.exists():
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 3000")
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS daily_kline (
            market TEXT NOT NULL,
            code TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            adjust TEXT NOT NULL,
            source TEXT NOT NULL,
            currency TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            preclose REAL,
            price REAL,
            change_amt REAL,
            change_pct REAL,
            volume_shares REAL,
            amount REAL,
            amplitude REAL,
            turnover REAL,
            trade_status TEXT,
            is_st TEXT,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (market, code, trade_date, adjust)
        );

        CREATE TABLE IF NOT EXISTS quote_snapshot (
            market TEXT NOT NULL,
            code TEXT NOT NULL,
            source TEXT NOT NULL,
            currency TEXT,
            price REAL,
            change_amt REAL,
            change_pct REAL,
            volume_shares REAL,
            amount REAL,
            trade_date TEXT,
            updated_at TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY (market, code)
        );

        CREATE TABLE IF NOT EXISTS detail_blocks (
            market TEXT NOT NULL,
            code TEXT NOT NULL,
            block TEXT NOT NULL,
            source TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY (market, code, block)
        );

        CREATE TABLE IF NOT EXISTS fetch_status (
            market TEXT NOT NULL,
            code TEXT NOT NULL,
            data_type TEXT NOT NULL,
            source TEXT NOT NULL,
            ok INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            error TEXT,
            PRIMARY KEY (market, code, data_type, source)
        );
        """
    )
    conn.commit()


def upsert_daily_kline(rows: list[dict[str, Any]], *, source: str) -> None:
    if not rows:
        return
    now = kb.now_ts()
    conn = _connect(create=True)
    assert conn is not None
    with conn:
        conn.executemany(
            """
            INSERT INTO daily_kline (
                market, code, trade_date, adjust, source, currency,
                open, high, low, close, preclose, price,
                change_amt, change_pct, volume_shares, amount,
                amplitude, turnover, trade_status, is_st, fetched_at
            ) VALUES (
                :market, :code, :trade_date, :adjust, :source, :currency,
                :open, :high, :low, :close, :preclose, :price,
                :change_amt, :change_pct, :volume_shares, :amount,
                :amplitude, :turnover, :trade_status, :is_st, :fetched_at
            )
            ON CONFLICT(market, code, trade_date, adjust) DO UPDATE SET
                source=excluded.source,
                currency=excluded.currency,
                open=excluded.open,
                high=excluded.high,
                low=excluded.low,
                close=excluded.close,
                preclose=excluded.preclose,
                price=excluded.price,
                change_amt=excluded.change_amt,
                change_pct=excluded.change_pct,
                volume_shares=excluded.volume_shares,
                amount=excluded.amount,
                amplitude=excluded.amplitude,
                turnover=excluded.turnover,
                trade_status=excluded.trade_status,
                is_st=excluded.is_st,
                fetched_at=excluded.fetched_at
            """,
            [
                {
                    **row,
                    "source": source,
                    "price": row.get("price", row.get("close")),
                    "fetched_at": row.get("fetched_at") or now,
                }
                for row in rows
            ],
        )
    conn.close()


def load_daily_kline(market: str, code: str, *, adjust: str = "qfq", limit: int = 90) -> list[dict[str, Any]]:
    conn = _connect(create=False)
    if conn is None:
        return []
    try:
        cur = conn.execute(
            """
            SELECT * FROM daily_kline
            WHERE market = ? AND code = ? AND adjust = ?
            ORDER BY trade_date DESC
            LIMIT ?
            """,
            (market.upper(), code, adjust, int(limit)),
        )
        rows = [_row_to_kline(dict(row)) for row in cur.fetchall()]
        rows.reverse()
        return rows
    finally:
        conn.close()


def upsert_quote_snapshot(payload: dict[str, Any], *, source: str) -> None:
    if not payload.get("market") or not payload.get("code"):
        return
    now = kb.now_ts()
    conn = _connect(create=True)
    assert conn is not None
    with conn:
        conn.execute(
            """
            INSERT INTO quote_snapshot (
                market, code, source, currency, price, change_amt,
                change_pct, volume_shares, amount, trade_date, updated_at,
                payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(market, code) DO UPDATE SET
                source=excluded.source,
                currency=excluded.currency,
                price=excluded.price,
                change_amt=excluded.change_amt,
                change_pct=excluded.change_pct,
                volume_shares=excluded.volume_shares,
                amount=excluded.amount,
                trade_date=excluded.trade_date,
                updated_at=excluded.updated_at,
                payload_json=excluded.payload_json
            """,
            (
                str(payload.get("market", "")).upper(),
                str(payload.get("code", "")),
                source,
                payload.get("currency"),
                payload.get("price"),
                payload.get("change_amt"),
                payload.get("change_pct"),
                payload.get("volume_shares"),
                payload.get("amount"),
                payload.get("date") or payload.get("trade_date"),
                payload.get("updated_at") or now,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
            ),
        )
    conn.close()


def load_quote_snapshot(market: str, code: str) -> dict[str, Any] | None:
    conn = _connect(create=False)
    if conn is None:
        return None
    try:
        cur = conn.execute(
            "SELECT payload_json FROM quote_snapshot WHERE market = ? AND code = ?",
            (market.upper(), code),
        )
        row = cur.fetchone()
        if row is None:
            return None
        try:
            return json.loads(row["payload_json"])
        except Exception:
            return None
    finally:
        conn.close()


def upsert_detail_block(market: str, code: str, block: str, payload: Any, *, source: str) -> None:
    if payload in (None, "", [], {}):
        return
    conn = _connect(create=True)
    assert conn is not None
    with conn:
        conn.execute(
            """
            INSERT INTO detail_blocks (market, code, block, source, updated_at, payload_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(market, code, block) DO UPDATE SET
                source=excluded.source,
                updated_at=excluded.updated_at,
                payload_json=excluded.payload_json
            """,
            (
                market.upper(),
                code,
                block,
                source,
                kb.now_ts(),
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
            ),
        )
    conn.close()


def load_detail_blocks(market: str, code: str) -> dict[str, Any]:
    conn = _connect(create=False)
    if conn is None:
        return {}
    try:
        cur = conn.execute(
            "SELECT block, payload_json FROM detail_blocks WHERE market = ? AND code = ?",
            (market.upper(), code),
        )
        blocks: dict[str, Any] = {}
        for row in cur.fetchall():
            try:
                blocks[row["block"]] = json.loads(row["payload_json"])
            except Exception:
                continue
        return blocks
    finally:
        conn.close()


def load_detail_block(market: str, code: str, block: str) -> Any:
    return load_detail_blocks(market, code).get(block)


def record_fetch_status(
    market: str,
    code: str,
    data_type: str,
    source: str,
    *,
    ok: bool,
    error: str = "",
    create_on_failure: bool = False,
) -> None:
    conn = _connect(create=ok or create_on_failure)
    if conn is None:
        return
    with conn:
        conn.execute(
            """
            INSERT INTO fetch_status (market, code, data_type, source, ok, updated_at, error)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(market, code, data_type, source) DO UPDATE SET
                ok=excluded.ok,
                updated_at=excluded.updated_at,
                error=excluded.error
            """,
            (market.upper(), code, data_type, source, 1 if ok else 0, kb.now_ts(), error[:240]),
        )
    conn.close()


def has_any_cache() -> bool:
    conn = _connect(create=False)
    if conn is None:
        return False
    try:
        cur = conn.execute("SELECT 1 FROM daily_kline LIMIT 1")
        return cur.fetchone() is not None
    finally:
        conn.close()


def _row_to_kline(row: dict[str, Any]) -> dict[str, Any]:
    trade_date = row.pop("trade_date", "")
    row["date"] = trade_date
    row["volume"] = row.get("volume_shares")
    return row

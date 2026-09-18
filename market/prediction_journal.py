import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class PredictionJournal:
    """Persistent, auditable next-session forecast journal."""

    def __init__(self, path="data/prediction_journal.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self):
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_date TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    bias TEXT NOT NULL,
                    probability INTEGER NOT NULL,
                    risk_score INTEGER NOT NULL,
                    signals_json TEXT NOT NULL,
                    reasons_json TEXT NOT NULL,
                    catalysts_json TEXT NOT NULL,
                    confirmation_json TEXT NOT NULL,
                    invalidation_json TEXT NOT NULL,
                    open_snapshot_json TEXT,
                    close_snapshot_json TEXT,
                    actual_outcome TEXT,
                    actual_change REAL,
                    direction_correct INTEGER,
                    invalidated INTEGER NOT NULL DEFAULT 0,
                    invalidation_reason TEXT,
                    lesson TEXT,
                    reviewed_at TEXT
                )
            """)

    def save_setup(self, setup):
        values = (
            setup["session_date"], setup["created_at"], setup["bias"],
            setup["probability"], setup["risk_score"],
            json.dumps(setup["signals"]), json.dumps(setup["reasons"]),
            json.dumps(setup["catalysts"]), json.dumps(setup["confirmation"]),
            json.dumps(setup["invalidation"]),
        )
        with self._connect() as db:
            db.execute("""
                INSERT INTO predictions (
                    session_date, created_at, bias, probability, risk_score,
                    signals_json, reasons_json, catalysts_json,
                    confirmation_json, invalidation_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_date) DO UPDATE SET
                    created_at=excluded.created_at, bias=excluded.bias,
                    probability=excluded.probability, risk_score=excluded.risk_score,
                    signals_json=excluded.signals_json, reasons_json=excluded.reasons_json,
                    catalysts_json=excluded.catalysts_json,
                    confirmation_json=excluded.confirmation_json,
                    invalidation_json=excluded.invalidation_json
                WHERE predictions.reviewed_at IS NULL
            """, values)
        return self.get(setup["session_date"])

    def get(self, session_date):
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM predictions WHERE session_date=?", (str(session_date),)
            ).fetchone()
        return self._decode(row)

    def latest_open(self):
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM predictions WHERE reviewed_at IS NULL ORDER BY session_date DESC LIMIT 1"
            ).fetchone()
        return self._decode(row)

    def capture_open(self, session_date, snapshot):
        with self._connect() as db:
            db.execute(
                "UPDATE predictions SET open_snapshot_json=? WHERE session_date=? AND reviewed_at IS NULL",
                (json.dumps(snapshot), str(session_date)),
            )
        return self.get(session_date)

    def review(self, session_date, close_snapshot, actual_change, invalidated=False,
               invalidation_reason=None, lesson=None):
        item = self.get(session_date)
        if not item:
            raise ValueError("No saved setup exists for that date.")
        actual_change = float(actual_change)
        outcome = "Bullish" if actual_change >= 0.20 else "Bearish" if actual_change <= -0.20 else "Mixed"
        predicted = item["bias"]
        correct = predicted == outcome or predicted == "Mixed" and outcome == "Mixed"
        with self._connect() as db:
            db.execute("""
                UPDATE predictions SET close_snapshot_json=?, actual_outcome=?,
                    actual_change=?, direction_correct=?, invalidated=?,
                    invalidation_reason=?, lesson=?, reviewed_at=?
                WHERE session_date=?
            """, (
                json.dumps(close_snapshot), outcome, actual_change, int(correct),
                int(bool(invalidated)), invalidation_reason, lesson,
                datetime.now(timezone.utc).isoformat(timespec="seconds"), str(session_date),
            ))
        return self.get(session_date)

    def statistics(self, limit=60):
        with self._connect() as db:
            rows = db.execute("""
                SELECT * FROM predictions WHERE reviewed_at IS NOT NULL
                ORDER BY session_date DESC LIMIT ?
            """, (limit,)).fetchall()
        if not rows:
            return {"count": 0, "accuracy": None, "avg_confidence": None,
                    "invalidation_rate": None, "calibration_gap": None}
        count = len(rows)
        accuracy = sum(r["direction_correct"] for r in rows) / count * 100
        average = sum(r["probability"] for r in rows) / count
        invalidation = sum(r["invalidated"] for r in rows) / count * 100
        return {
            "count": count,
            "accuracy": round(accuracy, 1),
            "avg_confidence": round(average, 1),
            "invalidation_rate": round(invalidation, 1),
            "calibration_gap": round(average - accuracy, 1),
        }

    @staticmethod
    def _decode(row):
        if row is None:
            return None
        item = dict(row)
        for key in ("signals", "reasons", "catalysts", "confirmation", "invalidation",
                    "open_snapshot", "close_snapshot"):
            raw = item.pop(f"{key}_json", None)
            item[key] = json.loads(raw) if raw else ([] if key not in {"signals", "open_snapshot", "close_snapshot"} else {})
        item["direction_correct"] = None if item["direction_correct"] is None else bool(item["direction_correct"])
        item["invalidated"] = bool(item["invalidated"])
        return item

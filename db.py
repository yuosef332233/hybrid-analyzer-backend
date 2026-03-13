"""
db.py — SQLite database layer for predictions, accuracy tracking, and auto-learning
"""
import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.getenv("DB_PATH", "predictions.db")

# Default weights — system starts here and learns over time
DEFAULT_WEIGHTS = {
    "home_advantage": 5.0,
    "form_weight": 0.30,
    "rating_weight": 0.40,
    "solid1_threshold": 52,
    "solid2_threshold": 46,
    "confidence_min": 62,
    "draw_threshold": 28,
    "avoid_threshold": 52,
    "version": 1,
}


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't exist"""
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            match_id TEXT NOT NULL,
            home_team TEXT NOT NULL,
            away_team TEXT NOT NULL,
            league TEXT,
            kickoff TEXT,
            home_win_prob INTEGER,
            draw_prob INTEGER,
            away_win_prob INTEGER,
            confidence INTEGER,
            decision TEXT,
            decision_type TEXT,
            predicted_score TEXT,
            actual_result TEXT,
            correct INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(date, match_id)
        );

        CREATE TABLE IF NOT EXISTS daily_accuracy (
            date TEXT PRIMARY KEY,
            total INTEGER DEFAULT 0,
            correct INTEGER DEFAULT 0,
            percentage REAL DEFAULT 0,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS learning_weights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            weights_json TEXT NOT NULL,
            overall_accuracy REAL DEFAULT 0,
            total_predictions INTEGER DEFAULT 0,
            learned_at TEXT DEFAULT CURRENT_TIMESTAMP,
            version INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS learning_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            old_weights TEXT,
            new_weights TEXT,
            accuracy_before REAL,
            accuracy_after REAL,
            changes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_predictions_date ON predictions(date);
        CREATE INDEX IF NOT EXISTS idx_predictions_match ON predictions(match_id);
        """)


# ══════════════════════════════════════════
#  PREDICTIONS
# ══════════════════════════════════════════

def save_prediction(date: str, p: dict):
    with get_conn() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO predictions
            (date, match_id, home_team, away_team, league, kickoff,
             home_win_prob, draw_prob, away_win_prob, confidence,
             decision, decision_type, predicted_score, actual_result, correct)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            date, p["match_id"], p["home_team"], p["away_team"],
            p.get("league", ""), p.get("kickoff", ""),
            p["home_win_prob"], p["draw_prob"], p["away_win_prob"],
            p["confidence"], p["decision"], p["decision_type"],
            p.get("predicted_score", ""), p.get("actual_result"), p.get("correct"),
        ))


def get_predictions(date: str) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM predictions WHERE date = ? ORDER BY kickoff", (date,)
        ).fetchall()
        return [dict(r) for r in rows]


def update_match_result(match_id: str, date: str, actual_result: str, correct: bool):
    with get_conn() as conn:
        conn.execute("""
            UPDATE predictions SET actual_result = ?, correct = ?
            WHERE match_id = ? AND date = ?
        """, (actual_result, int(correct), match_id, date))


def recalculate_accuracy(date: str) -> dict:
    with get_conn() as conn:
        row = conn.execute("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN correct = 1 THEN 1 ELSE 0 END) as correct_count
            FROM predictions WHERE date = ? AND correct IS NOT NULL
        """, (date,)).fetchone()
        total = row["total"] or 0
        correct = row["correct_count"] or 0
        percentage = round(correct / total * 100, 1) if total > 0 else 0
        conn.execute("""
            INSERT OR REPLACE INTO daily_accuracy (date, total, correct, percentage, updated_at)
            VALUES (?, ?, ?, ?, ?)
        """, (date, total, correct, percentage, datetime.utcnow().isoformat()))
        return {"date": date, "total": total, "correct": correct, "percentage": percentage}


def get_accuracy(date: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM daily_accuracy WHERE date = ?", (date,)).fetchone()
        return dict(row) if row else None


def get_accuracy_history() -> list:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT da.*, COUNT(p.id) as total_predictions
            FROM daily_accuracy da
            LEFT JOIN predictions p ON p.date = da.date
            GROUP BY da.date ORDER BY da.date DESC LIMIT 30
        """).fetchall()
        return [dict(r) for r in rows]


def get_overall_stats() -> dict:
    with get_conn() as conn:
        row = conn.execute("""
            SELECT COUNT(*) as total_predictions,
                   SUM(CASE WHEN correct = 1 THEN 1 ELSE 0 END) as total_correct,
                   COUNT(DISTINCT date) as total_days
            FROM predictions WHERE correct IS NOT NULL
        """).fetchone()
        total = row["total_predictions"] or 0
        correct = row["total_correct"] or 0
        days = row["total_days"] or 0
        overall_pct = round(correct / total * 100, 1) if total > 0 else 0
        best_day = conn.execute(
            "SELECT date, percentage FROM daily_accuracy ORDER BY percentage DESC LIMIT 1"
        ).fetchone()
        return {
            "total_predictions": total,
            "total_correct": correct,
            "total_days": days,
            "overall_accuracy": overall_pct,
            "best_day": dict(best_day) if best_day else None,
        }


# ══════════════════════════════════════════
#  LEARNING WEIGHTS
# ══════════════════════════════════════════

def get_weights() -> dict:
    """Get current learning weights — returns defaults if none saved yet"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT weights_json FROM learning_weights ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row:
            try:
                w = json.loads(row["weights_json"])
                # Merge with defaults in case new keys were added
                merged = {**DEFAULT_WEIGHTS, **w}
                return merged
            except Exception:
                pass
    return DEFAULT_WEIGHTS.copy()


def save_weights(weights: dict, overall_accuracy: float, total_predictions: int, changes: list = None):
    """Save new learned weights"""
    with get_conn() as conn:
        old_row = conn.execute(
            "SELECT weights_json FROM learning_weights ORDER BY id DESC LIMIT 1"
        ).fetchone()
        old_weights = old_row["weights_json"] if old_row else json.dumps(DEFAULT_WEIGHTS)
        old_acc_row = conn.execute(
            "SELECT percentage FROM daily_accuracy ORDER BY date DESC LIMIT 1"
        ).fetchone()
        old_acc = old_acc_row["percentage"] if old_acc_row else 0

        version = (weights.get("version") or 1) + 1
        weights["version"] = version

        conn.execute("""
            INSERT INTO learning_weights (weights_json, overall_accuracy, total_predictions, version)
            VALUES (?, ?, ?, ?)
        """, (json.dumps(weights), overall_accuracy, total_predictions, version))

        conn.execute("""
            INSERT INTO learning_log (date, old_weights, new_weights, accuracy_before, accuracy_after, changes)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            datetime.utcnow().date().isoformat(),
            old_weights,
            json.dumps(weights),
            old_acc,
            overall_accuracy,
            json.dumps(changes or []),
        ))


def get_learning_history() -> list:
    """Get history of all learning sessions"""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT date, accuracy_before, accuracy_after, changes, created_at
            FROM learning_log ORDER BY id DESC LIMIT 20
        """).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["changes"] = json.loads(d["changes"])
            except Exception:
                d["changes"] = []
            result.append(d)
        return result


# ══════════════════════════════════════════
#  ANALYSIS DATA FOR LEARNING
# ══════════════════════════════════════════

def get_decision_accuracy() -> dict:
    """Get accuracy breakdown by decision type — used for learning"""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT decision_type, decision,
                   COUNT(*) as total,
                   SUM(CASE WHEN correct = 1 THEN 1 ELSE 0 END) as correct_count
            FROM predictions
            WHERE correct IS NOT NULL AND decision_type IS NOT NULL
            GROUP BY decision_type, decision
        """).fetchall()
        result = {}
        for r in rows:
            key = r["decision"]
            result[key] = {
                "type": r["decision_type"],
                "total": r["total"],
                "correct": r["correct_count"],
                "accuracy": round(r["correct_count"] / r["total"] * 100, 1) if r["total"] > 0 else 0,
            }
        return result


def get_confidence_accuracy() -> list:
    """Get accuracy by confidence bucket — used for learning"""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT
                CASE
                    WHEN confidence < 50 THEN 'low'
                    WHEN confidence < 65 THEN 'medium'
                    WHEN confidence < 80 THEN 'high'
                    ELSE 'very_high'
                END as bucket,
                COUNT(*) as total,
                SUM(CASE WHEN correct = 1 THEN 1 ELSE 0 END) as correct_count
            FROM predictions
            WHERE correct IS NOT NULL
            GROUP BY bucket
        """).fetchall()
        return [dict(r) for r in rows]
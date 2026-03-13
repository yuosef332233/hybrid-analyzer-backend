"""
db.py — SQLite database layer for predictions and accuracy tracking
"""
import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.getenv("DB_PATH", "predictions.db")


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

        CREATE INDEX IF NOT EXISTS idx_predictions_date ON predictions(date);
        CREATE INDEX IF NOT EXISTS idx_predictions_match ON predictions(match_id);
        """)


def save_prediction(date: str, p: dict):
    """Insert or ignore a prediction"""
    with get_conn() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO predictions
            (date, match_id, home_team, away_team, league, kickoff,
             home_win_prob, draw_prob, away_win_prob, confidence,
             decision, decision_type, predicted_score, actual_result, correct)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            date,
            p["match_id"],
            p["home_team"],
            p["away_team"],
            p.get("league", ""),
            p.get("kickoff", ""),
            p["home_win_prob"],
            p["draw_prob"],
            p["away_win_prob"],
            p["confidence"],
            p["decision"],
            p["decision_type"],
            p.get("predicted_score", ""),
            p.get("actual_result"),
            p.get("correct"),
        ))


def get_predictions(date: str) -> list:
    """Get all predictions for a date"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM predictions WHERE date = ? ORDER BY kickoff",
            (date,)
        ).fetchall()
        return [dict(r) for r in rows]


def update_match_result(match_id: str, date: str, actual_result: str, correct: bool):
    """Update actual result and correct flag for a match"""
    with get_conn() as conn:
        conn.execute("""
            UPDATE predictions
            SET actual_result = ?, correct = ?
            WHERE match_id = ? AND date = ?
        """, (actual_result, int(correct), match_id, date))


def recalculate_accuracy(date: str) -> dict:
    """Recalculate and store accuracy for a given date"""
    with get_conn() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN correct = 1 THEN 1 ELSE 0 END) as correct_count
            FROM predictions
            WHERE date = ? AND correct IS NOT NULL
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
    """Get accuracy for a specific date"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM daily_accuracy WHERE date = ?", (date,)
        ).fetchone()
        return dict(row) if row else None


def get_accuracy_history() -> list:
    """Get accuracy history for all days, most recent first"""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT da.*, COUNT(p.id) as total_predictions
            FROM daily_accuracy da
            LEFT JOIN predictions p ON p.date = da.date
            GROUP BY da.date
            ORDER BY da.date DESC
            LIMIT 30
        """).fetchall()
        return [dict(r) for r in rows]


def get_overall_stats() -> dict:
    """Get overall accuracy stats across all time"""
    with get_conn() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*) as total_predictions,
                SUM(CASE WHEN correct = 1 THEN 1 ELSE 0 END) as total_correct,
                COUNT(DISTINCT date) as total_days
            FROM predictions
            WHERE correct IS NOT NULL
        """).fetchone()

        total = row["total_predictions"] or 0
        correct = row["total_correct"] or 0
        days = row["total_days"] or 0
        overall_pct = round(correct / total * 100, 1) if total > 0 else 0

        best_day = conn.execute("""
            SELECT date, percentage FROM daily_accuracy
            ORDER BY percentage DESC LIMIT 1
        """).fetchone()

        return {
            "total_predictions": total,
            "total_correct": correct,
            "total_days": days,
            "overall_accuracy": overall_pct,
            "best_day": dict(best_day) if best_day else None,
        }
import traceback
import json
import os
import asyncio
from datetime import date, datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import sport_api
import analyzer

app = FastAPI(title="Hybrid Intelligence Analyzer API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Simple file-based storage (no DB needed) ───
PREDICTIONS_FILE = "predictions_store.json"

def load_predictions() -> dict:
    if os.path.exists(PREDICTIONS_FILE):
        with open(PREDICTIONS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_predictions(data: dict):
    with open(PREDICTIONS_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ─── Models ───
class AnalyzeRequest(BaseModel):
    home_team_id: int
    away_team_id: int
    league_id: int
    season: int = 2024
    home_context: Optional[str] = ""
    away_context: Optional[str] = ""

class UpdateResultRequest(BaseModel):
    match_id: str
    actual_home_goals: int
    actual_away_goals: int


# ─── Existing endpoints ───
@app.get("/")
def root():
    return {"status": "Hybrid Intelligence Analyzer API is running ✅ v2.0"}

@app.get("/teams")
async def get_teams(league_id: int, season: int = 2024):
    try:
        teams = await sport_api.get_teams(league_id, season)
        return {"teams": teams}
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())

@app.get("/teams/search")
async def search_teams(q: str):
    try:
        teams = await sport_api.search_teams(q)
        return {"teams": teams}
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())

@app.post("/analyze")
async def analyze_match(req: AnalyzeRequest):
    try:
        home_stats, away_stats, h2h = await asyncio.gather(
            sport_api.get_team_stats(req.home_team_id, req.league_id, req.season),
            sport_api.get_team_stats(req.away_team_id, req.league_id, req.season),
            sport_api.get_h2h(req.home_team_id, req.away_team_id),
        )
        result = analyzer.run_analysis(
            home_stats=home_stats,
            away_stats=away_stats,
            h2h_fixtures=h2h,
            home_team_id=req.home_team_id,
            away_team_id=req.away_team_id,
            home_context=req.home_context or "",
            away_context=req.away_context or "",
        )
        return result
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())


# ─── NEW: Today's matches + auto predictions ───
@app.get("/today")
async def get_today_predictions():
    """Get all today's matches with AI predictions, auto-saved"""
    try:
        today = date.today().isoformat()
        store = load_predictions()

        # Return cached if already generated today
        if today in store and store[today].get("predictions"):
            return {
                "date": today,
                "predictions": store[today]["predictions"],
                "accuracy": store[today].get("accuracy"),
                "cached": True
            }

        # Fetch today's matches
        try:
            matches = await sport_api.get_todays_matches()
        except Exception as e:
            matches = []
        if not matches:
            return {"date": today, "predictions": [], "accuracy": None, "message": "No matches today"}

        # Run predictions for each match
        predictions = []
        for m in matches:
            try:
                home_stats, away_stats, h2h = await asyncio.gather(
                    sport_api.get_team_stats(m["home_team"]["id"], m["league_id"], 2024),
                    sport_api.get_team_stats(m["away_team"]["id"], m["league_id"], 2024),
                    sport_api.get_h2h(m["home_team"]["id"], m["away_team"]["id"]),
                )
                result = analyzer.run_analysis(
                    home_stats=home_stats,
                    away_stats=away_stats,
                    h2h_fixtures=h2h,
                    home_team_id=m["home_team"]["id"],
                    away_team_id=m["away_team"]["id"],
                )
                predictions.append({
                    "match_id": str(m["match_id"]),
                    "home_team": m["home_team"]["name"],
                    "away_team": m["away_team"]["name"],
                    "league": m["league_name"],
                    "kickoff": m["kickoff"],
                    "home_win_prob": result["home_win_prob"],
                    "draw_prob": result["draw_prob"],
                    "away_win_prob": result["away_win_prob"],
                    "confidence": result["confidence"],
                    "decision": result["decision"],
                    "decision_type": result["decision_type"],
                    "predicted_score": f"{result['predicted_home_goals']}-{result['predicted_away_goals']}",
                    "actual_result": None,  # filled later
                    "correct": None,
                })
            except Exception:
                continue

        # Save to store
        store[today] = {
            "predictions": predictions,
            "accuracy": None,
            "generated_at": datetime.utcnow().isoformat()
        }
        save_predictions(store)

        # Build recommendations
        recs = analyzer.build_recommendations(predictions)

        return {
            "date": today,
            "predictions": predictions,
            "recommendations": recs,
            "accuracy": None,
            "cached": False
        }

    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())


@app.get("/today/recommendations")
async def get_recommendations():
    """Get today's top picks: solid bets + value bets (against the odds)"""
    try:
        today = date.today().isoformat()
        store = load_predictions()

        predictions = []
        if today in store:
            predictions = store[today].get("predictions", [])

        if not predictions:
            # Auto-generate
            resp = await get_today_predictions()
            predictions = resp.get("predictions", [])

        recs = analyzer.build_recommendations(predictions)
        return {"date": today, "recommendations": recs}

    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())


@app.post("/results/update")
async def update_result(req: UpdateResultRequest):
    """Update actual result for a match and recalculate accuracy"""
    try:
        today = date.today().isoformat()
        store = load_predictions()

        if today not in store:
            raise HTTPException(status_code=404, detail="No predictions for today")

        predictions = store[today]["predictions"]
        updated = False

        for p in predictions:
            if p["match_id"] == req.match_id:
                hg = req.actual_home_goals
                ag = req.actual_away_goals
                p["actual_result"] = f"{hg}-{ag}"

                # Check if prediction was correct
                if hg > ag:
                    actual_outcome = "home"
                elif ag > hg:
                    actual_outcome = "away"
                else:
                    actual_outcome = "draw"

                predicted_outcome = (
                    "home" if p["home_win_prob"] > p["away_win_prob"] and p["home_win_prob"] > p["draw_prob"]
                    else "away" if p["away_win_prob"] > p["home_win_prob"] and p["away_win_prob"] > p["draw_prob"]
                    else "draw"
                )
                p["correct"] = (actual_outcome == predicted_outcome)
                updated = True
                break

        if not updated:
            raise HTTPException(status_code=404, detail="Match not found")

        # Recalculate accuracy
        completed = [p for p in predictions if p["correct"] is not None]
        if completed:
            correct_count = sum(1 for p in completed if p["correct"])
            accuracy = round(correct_count / len(completed) * 100, 1)
            store[today]["accuracy"] = {
                "percentage": accuracy,
                "correct": correct_count,
                "total": len(completed),
                "updated_at": datetime.utcnow().isoformat()
            }

        store[today]["predictions"] = predictions
        save_predictions(store)

        return {
            "success": True,
            "accuracy": store[today].get("accuracy")
        }

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())


@app.get("/accuracy/history")
async def get_accuracy_history():
    """Get accuracy stats for all past days"""
    try:
        store = load_predictions()
        history = []
        for day, data in sorted(store.items(), reverse=True):
            acc = data.get("accuracy")
            total = len(data.get("predictions", []))
            history.append({
                "date": day,
                "accuracy": acc,
                "total_predictions": total,
            })
        return {"history": history}
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())
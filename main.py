import traceback
import asyncio
import os
from datetime import date, datetime, timedelta
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import sport_api
import analyzer
import db

app = FastAPI(title="Hybrid Intelligence Analyzer API", version="3.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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


async def auto_update_accuracy():
    while True:
        now = datetime.utcnow()
        target = now.replace(hour=23, minute=0, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        try:
            today = date.today().isoformat()
            predictions = db.get_predictions(today)
            if not predictions:
                continue
            finished = await sport_api.get_finished_matches(today)
            finished_map = {f["match_id"]: f for f in finished}
            updated = False
            for p in predictions:
                if p["correct"] is not None:
                    continue
                result = finished_map.get(p["match_id"])
                if not result:
                    continue
                hg, ag = result["home_goals"], result["away_goals"]
                actual_result = f"{hg}-{ag}"
                if hg > ag: actual_outcome = "home"
                elif ag > hg: actual_outcome = "away"
                else: actual_outcome = "draw"
                hw, aw, dw = p["home_win_prob"], p["away_win_prob"], p["draw_prob"]
                if hw >= aw and hw >= dw: predicted_outcome = "home"
                elif aw >= hw and aw >= dw: predicted_outcome = "away"
                else: predicted_outcome = "draw"
                db.update_match_result(p["match_id"], today, actual_result, actual_outcome == predicted_outcome)
                updated = True
            if updated:
                db.recalculate_accuracy(today)
        except Exception:
            pass


@app.on_event("startup")
async def startup():
    db.init_db()
    asyncio.create_task(auto_update_accuracy())


@app.get("/")
def root():
    return {"status": "Hybrid Intelligence Analyzer API is running ✅ v3.1"}


@app.get("/teams")
async def get_teams(league_id: int, season: int = 2024):
    try:
        teams = await sport_api.get_teams(league_id, season)
        return {"teams": teams}
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())


@app.get("/teams/search")
async def search_teams(q: str, league_id: int = 0):
    try:
        teams = await sport_api.search_teams(q, league_id)
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


@app.get("/today")
async def get_today_predictions():
    try:
        today = date.today().isoformat()
        cached = db.get_predictions(today)
        if cached:
            accuracy = db.get_accuracy(today)
            return {"date": today, "predictions": cached, "accuracy": accuracy, "cached": True}

        matches = await sport_api.get_todays_matches()
        if not matches:
            return {"date": today, "predictions": [], "accuracy": None, "message": "No matches today"}

        predictions = []
        for m in matches:
            try:
                home_stats, away_stats, h2h = await asyncio.gather(
                    sport_api.get_team_stats(m["home_team"]["id"], m["league_id"], 2024),
                    sport_api.get_team_stats(m["away_team"]["id"], m["league_id"], 2024),
                    sport_api.get_h2h(m["home_team"]["id"], m["away_team"]["id"]),
                )
                result = analyzer.run_analysis(
                    home_stats=home_stats, away_stats=away_stats, h2h_fixtures=h2h,
                    home_team_id=m["home_team"]["id"], away_team_id=m["away_team"]["id"],
                )
                prediction = {
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
                    "actual_result": None,
                    "correct": None,
                }
                predictions.append(prediction)
                db.save_prediction(today, prediction)
            except Exception:
                continue

        recs = analyzer.build_recommendations(predictions)
        return {"date": today, "predictions": predictions, "recommendations": recs, "accuracy": None, "cached": False}
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())


@app.get("/today/recommendations")
async def get_recommendations():
    try:
        today = date.today().isoformat()
        predictions = db.get_predictions(today)
        if not predictions:
            resp = await get_today_predictions()
            predictions = resp.get("predictions", [])
        recs = analyzer.build_recommendations(predictions)
        return {"date": today, "recommendations": recs}
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())


@app.post("/results/update")
async def update_result(req: UpdateResultRequest):
    try:
        today = date.today().isoformat()
        predictions = db.get_predictions(today)
        if not predictions:
            raise HTTPException(status_code=404, detail="No predictions for today")
        match = next((p for p in predictions if p["match_id"] == req.match_id), None)
        if not match:
            raise HTTPException(status_code=404, detail="Match not found")
        hg, ag = req.actual_home_goals, req.actual_away_goals
        if hg > ag: actual_outcome = "home"
        elif ag > hg: actual_outcome = "away"
        else: actual_outcome = "draw"
        hw, aw, dw = match["home_win_prob"], match["away_win_prob"], match["draw_prob"]
        if hw >= aw and hw >= dw: predicted_outcome = "home"
        elif aw >= hw and aw >= dw: predicted_outcome = "away"
        else: predicted_outcome = "draw"
        db.update_match_result(req.match_id, today, f"{hg}-{ag}", actual_outcome == predicted_outcome)
        accuracy = db.recalculate_accuracy(today)
        return {"success": True, "accuracy": accuracy}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())


@app.post("/results/auto-update")
async def auto_update_today():
    try:
        today = date.today().isoformat()
        predictions = db.get_predictions(today)
        if not predictions:
            return {"message": "No predictions for today"}
        finished = await sport_api.get_finished_matches(today)
        finished_map = {f["match_id"]: f for f in finished}
        updated_count = 0
        for p in predictions:
            if p["correct"] is not None:
                continue
            result = finished_map.get(p["match_id"])
            if not result:
                continue
            hg, ag = result["home_goals"], result["away_goals"]
            if hg > ag: actual_outcome = "home"
            elif ag > hg: actual_outcome = "away"
            else: actual_outcome = "draw"
            hw, aw, dw = p["home_win_prob"], p["away_win_prob"], p["draw_prob"]
            if hw >= aw and hw >= dw: predicted_outcome = "home"
            elif aw >= hw and aw >= dw: predicted_outcome = "away"
            else: predicted_outcome = "draw"
            db.update_match_result(p["match_id"], today, f"{hg}-{ag}", actual_outcome == predicted_outcome)
            updated_count += 1
        accuracy = db.recalculate_accuracy(today) if updated_count > 0 else db.get_accuracy(today)
        return {"updated": updated_count, "finished_found": len(finished), "accuracy": accuracy}
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())


@app.get("/accuracy/history")
async def get_accuracy_history():
    try:
        return {"history": db.get_accuracy_history()}
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())


@app.get("/accuracy/stats")
async def get_overall_stats():
    try:
        return db.get_overall_stats()
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())


@app.post("/learn")
async def trigger_learning():
    """Manually trigger learning from past predictions"""
    try:
        result = analyzer.learn_from_history()
        return result
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())


@app.get("/learn/weights")
async def get_current_weights():
    """Get current AI weights"""
    try:
        weights = db.get_weights()
        return {"weights": weights, "default": db.DEFAULT_WEIGHTS}
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())


@app.get("/learn/history")
async def get_learning_history():
    """Get history of all learning sessions"""
    try:
        return {"history": db.get_learning_history()}
    except Exception:
        raise HTTPException(status_code=500, detail=traceback.format_exc())
import traceback
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import asyncio
import sport_api
import analyzer

app = FastAPI(title="Hybrid Intelligence Analyzer API", version="1.0.0")

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

@app.get("/")
def root():
    return {"status": "Hybrid Intelligence Analyzer API is running ✅"}

@app.get("/teams")
async def get_teams(league_id: int, season: int = 2024):
    try:
        teams = await sport_api.get_teams(league_id, season)
        return {"teams": teams}
    except Exception as e:
        raise HTTPException(status_code=500, detail=traceback.format_exc())

@app.get("/teams/search")
async def search_teams(q: str):
    try:
        teams = await sport_api.search_teams(q)
        return {"teams": teams}
    except Exception as e:
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=traceback.format_exc())
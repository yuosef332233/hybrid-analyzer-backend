import httpx
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("FOOTBALL_API_KEY")
BASE_URL = "https://api.football-data.org/v4"
HEADERS = {"X-Auth-Token": API_KEY}

LEAGUE_MAP = {
    39: "PL", 140: "PD", 135: "SA", 78: "BL1",
    61: "FL1", 2: "CL", 3: "EL", 848: "EC"
}

async def get_teams(league_id: int, season: int) -> list:
    code = LEAGUE_MAP.get(league_id, "PL")
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{BASE_URL}/competitions/{code}/teams",
            headers=HEADERS, timeout=10
        )
        data = r.json()
        return [
            {"id": t["id"], "name": t["name"]}
            for t in data.get("teams", [])
        ]

async def search_teams(query: str) -> list:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{BASE_URL}/teams",
            headers=HEADERS,
            params={"name": query, "limit": 8},
            timeout=10
        )
        data = r.json()
        return [
            {"id": t["id"], "name": t["name"]}
            for t in data.get("teams", [])
        ]

async def get_team_stats(team_id: int, league_id: int, season: int) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{BASE_URL}/teams/{team_id}/matches",
            headers=HEADERS,
            params={"status": "FINISHED", "limit": 10},
            timeout=10
        )
        data = r.json()
        matches = data.get("matches", [])

        if not matches:
            return {}

        wins, draws, losses = 0, 0, 0
        goals_for, goals_against = 0, 0
        form = []

        for m in matches[-5:]:
            home_id = m["homeTeam"]["id"]
            hg = m["score"]["fullTime"]["home"] or 0
            ag = m["score"]["fullTime"]["away"] or 0
            is_home = home_id == team_id
            gf = hg if is_home else ag
            ga = ag if is_home else hg
            goals_for += gf
            goals_against += ga
            if gf > ga:
                wins += 1; form.append("W")
            elif gf == ga:
                draws += 1; form.append("D")
            else:
                losses += 1; form.append("L")

        played = wins + draws + losses
        return {
            "form": form,
            "wins": wins,
            "draws": draws,
            "losses": losses,
            "goals_for_avg": round(goals_for / played, 2) if played else 1.2,
            "goals_against_avg": round(goals_against / played, 2) if played else 1.2,
        }

async def get_h2h(team1_id: int, team2_id: int, last: int = 10) -> list:
    """Fetch H2H from multiple seasons for better coverage"""
    h2h = []
    async with httpx.AsyncClient() as client:
        # Try fetching from team1 matches — large limit for more history
        for limit in [50, 100]:
            r = await client.get(
                f"{BASE_URL}/teams/{team1_id}/matches",
                headers=HEADERS,
                params={"status": "FINISHED", "limit": limit},
                timeout=15
            )
            data = r.json()
            all_matches = data.get("matches", [])

            for m in all_matches:
                home_id = m["homeTeam"]["id"]
                away_id = m["awayTeam"]["id"]
                if home_id == team2_id or away_id == team2_id:
                    hg = m["score"]["fullTime"]["home"]
                    ag = m["score"]["fullTime"]["away"]
                    if hg is None or ag is None:
                        continue
                    # Avoid duplicates
                    match_id = m.get("id")
                    if not any(x.get("match_id") == match_id for x in h2h):
                        h2h.append({
                            "match_id": match_id,
                            "teams": {
                                "home": {"id": home_id},
                                "away": {"id": away_id}
                            },
                            "goals": {"home": hg, "away": ag}
                        })

            if len(h2h) >= last:
                break

    return h2h[:last]
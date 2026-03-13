import httpx
import os
from datetime import date
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("FOOTBALL_API_KEY")
BASE_URL = "https://api.football-data.org/v4"
HEADERS = {"X-Auth-Token": API_KEY}

# football-data.org competition codes
LEAGUE_MAP = {
    39: "PL",    # Premier League
    140: "PD",   # La Liga
    135: "SA",   # Serie A
    78: "BL1",   # Bundesliga
    61: "FL1",   # Ligue 1
    2: "CL",     # Champions League
    3: "EL",     # Europa League
    848: "ECL",  # Conference League
    94: "PPL",   # Primeira Liga
    88: "DED",   # Eredivisie
}

# Fallback team IDs for Europa & Conference League (common clubs)
EUROPA_TEAMS = {
    "Manchester United": 66, "Roma": 100, "Lazio": 98, "Bayer Leverkusen": 3,
    "Atalanta": 102, "Lyon": 80, "Porto": 211, "Benfica": 211,
    "Ajax": 610, "Fenerbahce": 610, "Galatasaray": 610, "Rangers": 401,
    "Real Sociedad": 92, "Villarreal": 94, "Sevilla": 559, "Fiorentina": 99,
    "West Ham": 563, "Slavia Praha": 678, "Olympiakos": 583,
    "Braga": 228, "Anderlecht": 246, "Gent": 341,
}

CONFERENCE_TEAMS = {
    "Chelsea": 61, "Fiorentina": 99, "Hearts": 390, "Villarreal": 94,
    "Olimpija Ljubljana": 1887, "PAOK": 586, "Rapid Wien": 792,
    "Molde": 498, "Shamrock Rovers": 744, "Djurgarden": 397,
    "Cercle Brugge": 341, "Legia Warsaw": 715, "Vitoria Guimaraes": 229,
    "Heidenheim": 4123, "Betis": 558, "Panathinaikos": 585,
}


async def get_teams(league_id: int, season: int) -> list:
    code = LEAGUE_MAP.get(league_id)

    # For Conference League — use manual list + search
    if league_id == 848:
        teams = []
        seen = set()
        for name, tid in CONFERENCE_TEAMS.items():
            if tid not in seen:
                teams.append({"id": tid, "name": name})
                seen.add(tid)
        # Also try API
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    f"{BASE_URL}/competitions/ECL/teams",
                    headers=HEADERS, timeout=10
                )
                if r.status_code == 200:
                    data = r.json()
                    for t in data.get("teams", []):
                        if t["id"] not in seen:
                            teams.append({"id": t["id"], "name": t["name"]})
                            seen.add(t["id"])
        except Exception:
            pass
        return teams

    # For Europa League — combine API + manual
    if league_id == 3:
        teams = []
        seen = set()
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    f"{BASE_URL}/competitions/EL/teams",
                    headers=HEADERS, timeout=10
                )
                if r.status_code == 200:
                    data = r.json()
                    for t in data.get("teams", []):
                        if t["id"] not in seen:
                            teams.append({"id": t["id"], "name": t["name"]})
                            seen.add(t["id"])
        except Exception:
            pass
        # Add manual fallback
        for name, tid in EUROPA_TEAMS.items():
            if tid not in seen:
                teams.append({"id": tid, "name": name})
                seen.add(tid)
        return teams

    if not code:
        return []

    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{BASE_URL}/competitions/{code}/teams",
            headers=HEADERS, timeout=10
        )
        if r.status_code != 200:
            return []
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
    h2h = []
    async with httpx.AsyncClient() as client:
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


async with httpx.AsyncClient(timeout=30) as client: 
    """Fetch all matches scheduled for today across all supported leagues"""
    today = date.today().isoformat()
    all_matches = []
    seen_ids = set()

    async with httpx.AsyncClient() as client:
        # Fetch all matches today from API
        r = await client.get(
            f"{BASE_URL}/matches",
            headers=HEADERS,
            params={"dateFrom": today, "dateTo": today},
            timeout=15
        )
        if r.status_code == 200:
            data = r.json()
            for m in data.get("matches", []):
                mid = m.get("id")
                if mid in seen_ids:
                    continue
                seen_ids.add(mid)

                competition = m.get("competition", {})
                league_id = competition.get("id", 0)

                # Map API competition ID to our league_id
                api_to_our = {
                    2021: 39,   # PL
                    2014: 140,  # La Liga
                    2019: 135,  # Serie A
                    2002: 78,   # Bundesliga
                    2015: 61,   # Ligue 1
                    2001: 2,    # CL
                    2146: 3,    # EL
                    2148: 848,  # ECL
                    2017: 94,   # PPL
                    2003: 88,   # Eredivisie
                }
                our_league_id = api_to_our.get(league_id, league_id)

                all_matches.append({
                    "match_id": mid,
                    "home_team": {
                        "id": m["homeTeam"]["id"],
                        "name": m["homeTeam"]["name"],
                    },
                    "away_team": {
                        "id": m["awayTeam"]["id"],
                        "name": m["awayTeam"]["name"],
                    },
                    "league_id": our_league_id,
                    "league_name": competition.get("name", ""),
                    "kickoff": m.get("utcDate", ""),
                    "status": m.get("status", "SCHEDULED"),
                    "score": {
                        "home": m["score"]["fullTime"]["home"],
                        "away": m["score"]["fullTime"]["away"],
                    } if m.get("score") else None
                })

    return all_matches
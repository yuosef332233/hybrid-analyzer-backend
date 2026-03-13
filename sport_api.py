import httpx
import os
from datetime import date
from dotenv import load_dotenv

load_dotenv()

# ── API 1: football-data.org ──
FDORG_KEY = os.getenv("FOOTBALL_API_KEY")
FDORG_URL = "https://api.football-data.org/v4"
FDORG_HEADERS = {"X-Auth-Token": FDORG_KEY}

# ── API 2: SoccerFootball (RapidAPI) ──
SFI_KEY = os.getenv("SOCCERFOOTBALL_API_KEY")
SFI_URL = "https://soccer-football-info.p.rapidapi.com"
SFI_HEADERS = {
    "x-rapidapi-key": SFI_KEY,
    "x-rapidapi-host": "soccer-football-info.p.rapidapi.com",
}

# ── API 3: SportMonks ──
SM_KEY = os.getenv("SPORTMONKS_API_KEY")
SM_URL = "https://api.sportmonks.com/v3/football"

# ── League mapping (football-data.org codes) ──
LEAGUE_MAP = {
    39: "PL", 140: "PD", 135: "SA", 78: "BL1",
    61: "FL1", 2: "CL", 3: "EL", 848: "ECL",
    94: "PPL", 88: "DED",
}

# ── SoccerFootball league IDs ──
SFI_LEAGUE_MAP = {
    39: "1", 140: "2", 135: "3", 78: "4",
    61: "5", 2: "132", 3: "133", 848: "134",
    94: "6", 88: "7",
}

# ── SportMonks season IDs (verified 2025/26) ──
SM_SEASON_MAP = {
    39: 25583,   # Premier League
    140: 25659,  # La Liga
    135: 25533,  # Serie A
    78: 25646,   # Bundesliga
    61: 25651,   # Ligue 1
    2: 25580,    # Champions League
    3: 25582,    # Europa League
    848: 25581,  # Conference League
}

# ── football-data.org competition IDs → our league_id ──
API_TO_OUR = {
    2021: 39, 2014: 140, 2019: 135, 2002: 78,
    2015: 61, 2001: 2, 2146: 3, 2154: 848,
    2017: 94, 2003: 88,
}

# ── In-memory cache for SportMonks standings ──
# key: league_id → {team_id: stats_dict}
_sm_standings_cache = {}


# ══════════════════════════════════════════
#  SPORTMONKS STANDINGS CACHE
# ══════════════════════════════════════════

async def _load_sm_standings(league_id: int) -> dict:
    """Load standings from SportMonks for a league — cached in memory"""
    if league_id in _sm_standings_cache:
        return _sm_standings_cache[league_id]

    season_id = SM_SEASON_MAP.get(league_id)
    if not season_id or not SM_KEY:
        return {}

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(
                f"{SM_URL}/standings/seasons/{season_id}",
                params={"api_token": SM_KEY, "include": "details"},
            )
            if r.status_code != 200:
                return {}

            standings = {}
            # type_id mapping from SportMonks
            # 129=played, 130=wins, 131=draws, 132=losses
            # 133=goals_for, 134=goals_against
            for entry in r.json().get("data", []):
                team_id = entry.get("participant_id")
                if not team_id:
                    continue
                details = {d["type_id"]: d["value"] for d in entry.get("details", [])}
                played = details.get(129, 1) or 1
                gf = details.get(133, 0) or 0
                ga = details.get(134, 0) or 0
                wins = details.get(130, 0) or 0
                draws = details.get(131, 0) or 0
                losses = details.get(132, 0) or 0
                standings[team_id] = {
                    "wins": wins,
                    "draws": draws,
                    "losses": losses,
                    "goals_for_avg": round(gf / played, 2),
                    "goals_against_avg": round(ga / played, 2),
                    "form": [],
                    "source": "sportmonks",
                }
            _sm_standings_cache[league_id] = standings
            return standings
    except Exception:
        return {}


# ══════════════════════════════════════════
#  TEAMS
# ══════════════════════════════════════════

async def get_teams(league_id: int, season: int) -> list:
    """Fetch teams — SportMonks first (with SM IDs), then fdorg"""
    teams = []
    seen = set()

    # ── SportMonks ──
    season_id = SM_SEASON_MAP.get(league_id)
    if season_id and SM_KEY:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(
                    f"{SM_URL}/teams/seasons/{season_id}",
                    params={"api_token": SM_KEY, "per_page": 50},
                )
                if r.status_code == 200:
                    for t in r.json().get("data", []):
                        if t.get("placeholder"):
                            continue
                        name = t.get("name") or t.get("short_code", "")
                        tid = t.get("id")
                        if tid and name and tid not in seen:
                            teams.append({"id": tid, "name": name, "source": "sportmonks"})
                            seen.add(tid)
        except Exception:
            pass

    # ── football-data.org fallback (only if SM returned nothing) ──
    if not teams:
        code = LEAGUE_MAP.get(league_id)
        if code:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    r = await client.get(
                        f"{FDORG_URL}/competitions/{code}/teams",
                        headers=FDORG_HEADERS,
                    )
                    if r.status_code == 200:
                        for t in r.json().get("teams", []):
                            if t["id"] not in seen:
                                teams.append({"id": t["id"], "name": t["name"], "source": "fdorg"})
                                seen.add(t["id"])
            except Exception:
                pass

    return teams


async def search_teams(query: str, league_id: int = 0) -> list:
    results = []
    seen = set()

    if SM_KEY:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{SM_URL}/teams/search/{query}",
                    params={"api_token": SM_KEY},
                )
                if r.status_code == 200:
                    for t in r.json().get("data", [])[:8]:
                        tid = t.get("id")
                        name = t.get("name", "")
                        if tid and name and tid not in seen:
                            results.append({"id": tid, "name": name, "source": "sportmonks"})
                            seen.add(tid)
        except Exception:
            pass

    if len(results) < 4:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{FDORG_URL}/teams",
                    headers=FDORG_HEADERS,
                    params={"name": query, "limit": 8},
                )
                if r.status_code == 200:
                    for t in r.json().get("teams", []):
                        if t["id"] not in seen:
                            results.append({"id": t["id"], "name": t["name"], "source": "fdorg"})
                            seen.add(t["id"])
        except Exception:
            pass

    return results[:8]


# ══════════════════════════════════════════
#  TEAM STATS
# ══════════════════════════════════════════

async def get_team_stats(team_id: int, league_id: int, season: int) -> dict:
    """
    Get stats — tries SportMonks standings first (correct IDs),
    then fdorg recent matches for form data.
    """
    sm_stats = {}
    fdorg_stats = {}

    # ── SportMonks standings (season-level stats) ──
    standings = await _load_sm_standings(league_id)
    if standings and team_id in standings:
        sm_stats = standings[team_id]

    # ── football-data.org (recent match form) ──
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{FDORG_URL}/teams/{team_id}/matches",
                headers=FDORG_HEADERS,
                params={"status": "FINISHED", "limit": 10},
            )
            if r.status_code == 200:
                matches = r.json().get("matches", [])
                if matches:
                    wins = draws = losses = 0
                    goals_for = goals_against = 0
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
                        if gf > ga: wins += 1; form.append("W")
                        elif gf == ga: draws += 1; form.append("D")
                        else: losses += 1; form.append("L")
                    played = wins + draws + losses or 1
                    fdorg_stats = {
                        "form": form,
                        "wins": wins, "draws": draws, "losses": losses,
                        "goals_for_avg": round(goals_for / played, 2),
                        "goals_against_avg": round(goals_against / played, 2),
                        "source": "fdorg",
                    }
    except Exception:
        pass

    # ── Merge ──
    if not sm_stats and not fdorg_stats:
        return {}

    if sm_stats and fdorg_stats:
        return {
            "form": fdorg_stats.get("form", []),
            "wins": sm_stats["wins"],
            "draws": sm_stats["draws"],
            "losses": sm_stats["losses"],
            "goals_for_avg": round((sm_stats["goals_for_avg"] * 0.6 + fdorg_stats["goals_for_avg"] * 0.4), 2),
            "goals_against_avg": round((sm_stats["goals_against_avg"] * 0.6 + fdorg_stats["goals_against_avg"] * 0.4), 2),
            "source": "merged",
        }

    return sm_stats or fdorg_stats


# ══════════════════════════════════════════
#  H2H
# ══════════════════════════════════════════

async def get_h2h(team1_id: int, team2_id: int, last: int = 10) -> list:
    h2h = []
    seen_ids = set()

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            for limit in [50, 100]:
                r = await client.get(
                    f"{FDORG_URL}/teams/{team1_id}/matches",
                    headers=FDORG_HEADERS,
                    params={"status": "FINISHED", "limit": limit},
                )
                for m in r.json().get("matches", []):
                    home_id = m["homeTeam"]["id"]
                    away_id = m["awayTeam"]["id"]
                    if home_id == team2_id or away_id == team2_id:
                        hg = m["score"]["fullTime"]["home"]
                        ag = m["score"]["fullTime"]["away"]
                        if hg is None or ag is None:
                            continue
                        mid = m.get("id")
                        if mid not in seen_ids:
                            h2h.append({
                                "match_id": mid,
                                "teams": {"home": {"id": home_id}, "away": {"id": away_id}},
                                "goals": {"home": hg, "away": ag},
                            })
                            seen_ids.add(mid)
                if len(h2h) >= last:
                    break
    except Exception:
        pass

    return h2h[:last]


# ══════════════════════════════════════════
#  TODAY'S MATCHES
# ══════════════════════════════════════════

async def get_todays_matches() -> list:
    today = date.today().isoformat()
    all_matches = []
    seen_ids = set()

    # ── football-data.org (main source for today) ──
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{FDORG_URL}/matches",
                headers=FDORG_HEADERS,
                params={"dateFrom": today, "dateTo": today},
            )
            if r.status_code == 200:
                for m in r.json().get("matches", []):
                    mid = str(m.get("id", ""))
                    if mid in seen_ids:
                        continue
                    seen_ids.add(mid)
                    competition = m.get("competition", {})
                    our_league_id = API_TO_OUR.get(competition.get("id", 0), 0)
                    all_matches.append({
                        "match_id": mid,
                        "home_team": {"id": m["homeTeam"]["id"], "name": m["homeTeam"]["name"]},
                        "away_team": {"id": m["awayTeam"]["id"], "name": m["awayTeam"]["name"]},
                        "league_id": our_league_id,
                        "league_name": competition.get("name", ""),
                        "kickoff": m.get("utcDate", ""),
                        "status": m.get("status", "SCHEDULED"),
                        "score": None,
                        "source": "fdorg",
                    })
    except Exception:
        pass

    return all_matches


# ══════════════════════════════════════════
#  FETCH RESULTS
# ══════════════════════════════════════════

async def get_finished_matches(target_date: str) -> list:
    finished = []
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{FDORG_URL}/matches",
                headers=FDORG_HEADERS,
                params={"dateFrom": target_date, "dateTo": target_date, "status": "FINISHED"},
            )
            if r.status_code == 200:
                for m in r.json().get("matches", []):
                    hg = m["score"]["fullTime"]["home"]
                    ag = m["score"]["fullTime"]["away"]
                    if hg is None or ag is None:
                        continue
                    finished.append({
                        "match_id": str(m.get("id", "")),
                        "home_goals": int(hg),
                        "away_goals": int(ag),
                    })
    except Exception:
        pass
    return finished
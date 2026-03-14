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

# ── League mapping (football-data.org codes) ──
LEAGUE_MAP = {
    39: "PL", 140: "PD", 135: "SA", 78: "BL1",
    61: "FL1", 2: "CL", 3: "EL", 848: "ECL",
    94: "PPL", 88: "DED",
    45: "FAC", 48: "ELC",
}

# ── football-data.org competition IDs → our league_id ──
API_TO_OUR = {
    2021: 39, 2014: 140, 2019: 135, 2002: 78,
    2015: 61, 2001: 2, 2146: 3, 2154: 848,
    2017: 94, 2003: 88,
}

# ── In-memory cache ──
_teams_cache = {}       # league_id → list of teams
_standings_cache = {}   # league_id → {team_id: stats}
_form_cache = {}        # team_id → stats dict


# ══════════════════════════════════════════
#  TEAMS
# ══════════════════════════════════════════

async def get_teams(league_id: int, season: int) -> list:
    """Fetch teams from football-data.org (consistent IDs)"""
    cache_key = f"{league_id}_{season}"
    if cache_key in _teams_cache:
        return _teams_cache[cache_key]

    teams = []
    code = LEAGUE_MAP.get(league_id)
    if code:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(
                    f"{FDORG_URL}/competitions/{code}/teams",
                    headers=FDORG_HEADERS,
                    params={"season": season},
                )
                if r.status_code == 200:
                    for t in r.json().get("teams", []):
                        teams.append({
                            "id": t["id"],
                            "name": t["name"],
                            "shortName": t.get("shortName", t["name"]),
                            "source": "fdorg",
                        })
        except Exception:
            pass

    if teams:
        _teams_cache[cache_key] = teams
    return teams


async def search_teams(query: str, league_id: int = 0) -> list:
    """Search teams — from cache first, then API"""
    results = []
    seen = set()
    query_lower = query.lower()

    # Search in all cached teams first
    for cached_teams in _teams_cache.values():
        for t in cached_teams:
            if query_lower in t["name"].lower() and t["id"] not in seen:
                results.append(t)
                seen.add(t["id"])

    # If league specified and not enough results, fetch that league's teams
    if league_id and len(results) < 4:
        teams = await get_teams(league_id, 2024)
        for t in teams:
            if query_lower in t["name"].lower() and t["id"] not in seen:
                results.append(t)
                seen.add(t["id"])

    return results[:8]


# ══════════════════════════════════════════
#  STANDINGS (season-level stats from fdorg)
# ══════════════════════════════════════════

async def _load_fdorg_standings(league_id: int) -> dict:
    """Load standings from football-data.org — gives season-level wins/losses/goals"""
    if league_id in _standings_cache:
        return _standings_cache[league_id]

    code = LEAGUE_MAP.get(league_id)
    if not code:
        return {}

    standings = {}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{FDORG_URL}/competitions/{code}/standings",
                headers=FDORG_HEADERS,
            )
            if r.status_code == 200:
                for group in r.json().get("standings", []):
                    for entry in group.get("table", []):
                        team = entry.get("team", {})
                        team_id = team.get("id")
                        if not team_id:
                            continue
                        played = entry.get("playedGames", 1) or 1
                        gf = entry.get("goalsFor", 0) or 0
                        ga = entry.get("goalsAgainst", 0) or 0
                        standings[team_id] = {
                            "wins": entry.get("won", 0),
                            "draws": entry.get("draw", 0),
                            "losses": entry.get("lost", 0),
                            "goals_for_avg": round(gf / played, 2),
                            "goals_against_avg": round(ga / played, 2),
                            "source": "fdorg_standings",
                        }
        _standings_cache[league_id] = standings
    except Exception:
        pass

    return standings


# ══════════════════════════════════════════
#  TEAM STATS
# ══════════════════════════════════════════

async def get_team_stats(team_id: int, league_id: int, season: int) -> dict:
    """
    Get team stats using football-data.org only — consistent IDs guaranteed.
    Merges standings (season stats) + recent matches (form).
    """
    # Check form cache
    if team_id in _form_cache:
        form_stats = _form_cache[team_id]
    else:
        form_stats = {}
        # ── Recent matches for form ──
        try:
            async with httpx.AsyncClient(timeout=12) as client:
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
                            hg = m["score"]["fullTime"].get("home") or 0
                            ag = m["score"]["fullTime"].get("away") or 0
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
                        played = wins + draws + losses or 1
                        form_stats = {
                            "form": form,
                            "wins": wins,
                            "draws": draws,
                            "losses": losses,
                            "goals_for_avg": round(goals_for / played, 2),
                            "goals_against_avg": round(goals_against / played, 2),
                            "source": "fdorg",
                        }
                        _form_cache[team_id] = form_stats
        except Exception:
            pass

    # ── Season standings stats ──
    standings = await _load_fdorg_standings(league_id)
    standing_stats = standings.get(team_id, {})

    # ── Merge ──
    if standing_stats and form_stats:
        return {
            "form": form_stats.get("form", []),
            "wins": standing_stats["wins"],
            "draws": standing_stats["draws"],
            "losses": standing_stats["losses"],
            "goals_for_avg": round(
                standing_stats["goals_for_avg"] * 0.6 + form_stats["goals_for_avg"] * 0.4, 2
            ),
            "goals_against_avg": round(
                standing_stats["goals_against_avg"] * 0.6 + form_stats["goals_against_avg"] * 0.4, 2
            ),
            "source": "merged",
        }
    elif standing_stats:
        return {**standing_stats, "form": []}
    elif form_stats:
        return form_stats

    return {}


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
                if r.status_code != 200:
                    break
                for m in r.json().get("matches", []):
                    home_id = m["homeTeam"]["id"]
                    away_id = m["awayTeam"]["id"]
                    if home_id == team2_id or away_id == team2_id:
                        hg = m["score"]["fullTime"].get("home")
                        ag = m["score"]["fullTime"].get("away")
                        if hg is None or ag is None:
                            continue
                        mid = m.get("id")
                        if mid not in seen_ids:
                            h2h.append({
                                "match_id": mid,
                                "teams": {
                                    "home": {"id": home_id},
                                    "away": {"id": away_id},
                                },
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

    # ── football-data.org ──
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

                    status = m.get("status", "SCHEDULED")
                    # Skip already finished or postponed
                    if status in ("FINISHED", "POSTPONED", "CANCELLED"):
                        continue

                    competition = m.get("competition", {})
                    our_league_id = API_TO_OUR.get(competition.get("id", 0), 0)

                    # Skip unknown leagues
                    if our_league_id == 0:
                        continue

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
                        "status": status,
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
                params={
                    "dateFrom": target_date,
                    "dateTo": target_date,
                    "status": "FINISHED",
                },
            )
            if r.status_code == 200:
                for m in r.json().get("matches", []):
                    hg = m["score"]["fullTime"].get("home")
                    ag = m["score"]["fullTime"].get("away")
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
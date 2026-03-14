import httpx
import os
from datetime import date, timedelta
from dotenv import load_dotenv

load_dotenv()

SM_KEY = os.getenv("SPORTMONKS_API_KEY")
SM_URL = "https://api.sportmonks.com/v3/football"

# SportMonks season IDs (2025/26)
SM_SEASON_MAP = {
    39: 25583,   # Premier League
    140: 25659,  # La Liga
    135: 25533,  # Serie A
    78: 25646,   # Bundesliga
    61: 25651,   # Ligue 1
    2: 25580,    # Champions League
    3: 25582,    # Europa League
    848: 25581,  # Conference League
    45: 25584,   # FA Cup
    48: 25585,   # League Cup
    143: 25660,  # Copa del Rey
    137: 25534,  # Coppa Italia
    81: 25647,   # DFB Pokal
    66: 25652,   # Coupe de France
}

# SportMonks league_id → our league_id
SM_LEAGUE_TO_OURS = {
    8: 39,     # Premier League
    564: 140,  # La Liga
    384: 135,  # Serie A
    82: 78,    # Bundesliga
    301: 61,   # Ligue 1
    2: 2,      # Champions League
    5: 3,      # Europa League
    72: 848,   # Conference League
    24: 45,    # FA Cup
    25: 48,    # League Cup
    238: 143,  # Copa del Rey
    65: 137,   # Coppa Italia
    38: 81,    # DFB Pokal
    182: 66,   # Coupe de France
}

# Reverse: season_id → our league_id
SEASON_TO_OURS = {v: k for k, v in SM_SEASON_MAP.items()}

# In-memory cache
_teams_cache = {}
_standings_cache = {}
_form_cache = {}


def _params(**kwargs):
    return {"api_token": SM_KEY, **kwargs}


def _extract_scores(scores: list, home_id: int, away_id: int) -> tuple:
    """
    Extract final home/away goals from SportMonks scores array.
    Each score: {participant_id, score: {goals}, description}
    Priority: CURRENT > 2ND_HALF > 1ST_HALF
    """
    for desc in ("CURRENT", "2ND_HALF", "1ST_HALF"):
        h = a = None
        for s in scores:
            if s.get("description") != desc:
                continue
            pid = s.get("participant_id")
            goals = s.get("score", {}).get("goals", 0) or 0
            if pid == home_id:
                h = goals
            elif pid == away_id:
                a = goals
        if h is not None and a is not None:
            return h, a
    return 0, 0


# ══════════════════════════════════════════
#  TEAMS
# ══════════════════════════════════════════

async def get_teams(league_id: int, season: int) -> list:
    if league_id in _teams_cache:
        return _teams_cache[league_id]

    season_id = SM_SEASON_MAP.get(league_id)
    if not season_id:
        return []

    teams = []
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            page = 1
            while True:
                r = await client.get(
                    f"{SM_URL}/teams/seasons/{season_id}",
                    params=_params(per_page=50, page=page),
                )
                if r.status_code != 200:
                    break
                data = r.json().get("data", [])
                if not data:
                    break
                for t in data:
                    if t.get("placeholder"):
                        continue
                    teams.append({
                        "id": t["id"],
                        "name": t.get("name", ""),
                        "shortName": t.get("short_code", t.get("name", "")),
                        "source": "sportmonks",
                    })
                pagination = r.json().get("pagination", {})
                if page >= pagination.get("last_page", 1):
                    break
                page += 1
    except Exception:
        pass

    if teams:
        _teams_cache[league_id] = teams
    return teams


async def search_teams(query: str, league_id: int = 0) -> list:
    results = []
    seen = set()
    query_lower = query.lower()

    for cached in _teams_cache.values():
        for t in cached:
            if query_lower in t["name"].lower() and t["id"] not in seen:
                results.append(t)
                seen.add(t["id"])

    if len(results) < 3:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{SM_URL}/teams/search/{query}",
                    params=_params(),
                )
                if r.status_code == 200:
                    for t in r.json().get("data", [])[:8]:
                        tid = t.get("id")
                        name = t.get("name", "")
                        if tid and name and tid not in seen:
                            results.append({
                                "id": tid,
                                "name": name,
                                "shortName": t.get("short_code", name),
                                "source": "sportmonks",
                            })
                            seen.add(tid)
        except Exception:
            pass

    return results[:8]


# ══════════════════════════════════════════
#  STANDINGS
# ══════════════════════════════════════════

async def _load_standings(league_id: int) -> dict:
    if league_id in _standings_cache:
        return _standings_cache[league_id]

    season_id = SM_SEASON_MAP.get(league_id)
    if not season_id:
        return {}

    standings = {}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(
                f"{SM_URL}/standings/seasons/{season_id}",
                params=_params(include="details"),
            )
            if r.status_code == 200:
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
                        "source": "sportmonks",
                    }
        _standings_cache[league_id] = standings
    except Exception:
        pass

    return standings


# ══════════════════════════════════════════
#  TEAM STATS — form via fixtures/between
# ══════════════════════════════════════════

async def _get_form(team_id: int) -> dict:
    """Get last 5 finished matches for a team using fixtures/between endpoint"""
    if team_id in _form_cache:
        return _form_cache[team_id]

    today = date.today().isoformat()
    # Look back 3 months — enough for 5 matches for any team
    from_date = (date.today() - timedelta(days=90)).isoformat()

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{SM_URL}/fixtures/between/{from_date}/{today}/{team_id}",
                params=_params(
                    include="scores;participants",
                    per_page=50,
                ),
            )
            if r.status_code != 200:
                return {}

            form = []
            gf_total = ga_total = wins = draws = losses = 0

            # Only finished fixtures, sort by date descending in Python (API ignores sort param)
            all_fixtures = [f for f in r.json().get("data", []) if f.get("state_id") in (5, 6, 7)]
            all_fixtures.sort(key=lambda x: x.get("starting_at", ""), reverse=True)
            fixtures = all_fixtures[:5]

            for f in fixtures:
                participants = f.get("participants", [])
                home_p = next((p for p in participants if p.get("meta", {}).get("location") == "home"), None)
                away_p = next((p for p in participants if p.get("meta", {}).get("location") == "away"), None)
                if not home_p or not away_p:
                    continue

                home_id = home_p["id"]
                away_id = away_p["id"]
                is_home = home_id == team_id

                ft_home, ft_away = _extract_scores(f.get("scores", []), home_id, away_id)

                gf = ft_home if is_home else ft_away
                ga = ft_away if is_home else ft_home
                gf_total += gf
                ga_total += ga

                if gf > ga:
                    wins += 1; form.append("W")
                elif gf == ga:
                    draws += 1; form.append("D")
                else:
                    losses += 1; form.append("L")

            if not form:
                return {}

            played = wins + draws + losses or 1
            result = {
                "form": form,
                "wins": wins,
                "draws": draws,
                "losses": losses,
                "goals_for_avg": round(gf_total / played, 2),
                "goals_against_avg": round(ga_total / played, 2),
                "source": "sportmonks",
            }
            _form_cache[team_id] = result
            return result

    except Exception:
        return {}


async def get_team_stats(team_id: int, league_id: int, season: int) -> dict:
    standings = await _load_standings(league_id)
    standing_stats = standings.get(team_id, {})
    form_stats = await _get_form(team_id)

    if standing_stats and form_stats:
        return {
            "form": form_stats.get("form", []),
            "wins": standing_stats["wins"],
            "draws": standing_stats["draws"],
            "losses": standing_stats["losses"],
            "goals_for_avg": round(standing_stats["goals_for_avg"] * 0.6 + form_stats["goals_for_avg"] * 0.4, 2),
            "goals_against_avg": round(standing_stats["goals_against_avg"] * 0.6 + form_stats["goals_against_avg"] * 0.4, 2),
            "source": "merged",
        }
    return standing_stats or form_stats or {}


# ══════════════════════════════════════════
#  H2H
# ══════════════════════════════════════════

async def get_h2h(team1_id: int, team2_id: int, last: int = 10) -> list:
    h2h = []
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{SM_URL}/fixtures/head-to-head/{team1_id}/{team2_id}",
                params=_params(include="scores;participants", per_page=last),
            )
            if r.status_code == 200:
                for f in r.json().get("data", []):
                    if f.get("state_id") not in (5, 6, 7):
                        continue
                    participants = f.get("participants", [])
                    home_p = next((p for p in participants if p.get("meta", {}).get("location") == "home"), None)
                    away_p = next((p for p in participants if p.get("meta", {}).get("location") == "away"), None)
                    if not home_p or not away_p:
                        continue

                    ft_home, ft_away = _extract_scores(
                        f.get("scores", []), home_p["id"], away_p["id"]
                    )

                    h2h.append({
                        "match_id": f.get("id"),
                        "teams": {
                            "home": {"id": home_p["id"]},
                            "away": {"id": away_p["id"]},
                        },
                        "goals": {"home": ft_home, "away": ft_away},
                    })
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

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{SM_URL}/fixtures/date/{today}",
                params=_params(include="participants;league", per_page=100),
            )
            if r.status_code == 200:
                for f in r.json().get("data", []):
                    mid = str(f.get("id", ""))
                    if mid in seen_ids:
                        continue

                    sm_league_id = f.get("league_id")
                    our_league_id = SM_LEAGUE_TO_OURS.get(sm_league_id, 0)
                    if our_league_id == 0:
                        our_league_id = SEASON_TO_OURS.get(f.get("season_id"), 0)
                    if our_league_id == 0:
                        continue

                    state_id = f.get("state_id")
                    if state_id in (5, 6, 7, 10):
                        continue

                    participants = f.get("participants", [])
                    home = next((p for p in participants if p.get("meta", {}).get("location") == "home"), None)
                    away = next((p for p in participants if p.get("meta", {}).get("location") == "away"), None)
                    if not home or not away:
                        continue

                    seen_ids.add(mid)
                    league_info = f.get("league", {})
                    league_name = league_info.get("name", "") if isinstance(league_info, dict) else ""

                    all_matches.append({
                        "match_id": mid,
                        "home_team": {"id": home["id"], "name": home.get("name", "")},
                        "away_team": {"id": away["id"], "name": away.get("name", "")},
                        "league_id": our_league_id,
                        "league_name": league_name,
                        "kickoff": f.get("starting_at", ""),
                        "status": str(state_id),
                        "source": "sportmonks",
                    })
    except Exception:
        pass

    return all_matches


# ══════════════════════════════════════════
#  FINISHED MATCHES
# ══════════════════════════════════════════

async def get_finished_matches(target_date: str) -> list:
    finished = []
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{SM_URL}/fixtures/date/{target_date}",
                params=_params(include="scores;participants", per_page=100),
            )
            if r.status_code == 200:
                for f in r.json().get("data", []):
                    if f.get("state_id") not in (5, 6, 7):
                        continue

                    sm_league_id = f.get("league_id")
                    our_league_id = SM_LEAGUE_TO_OURS.get(sm_league_id, 0)
                    if our_league_id == 0:
                        our_league_id = SEASON_TO_OURS.get(f.get("season_id"), 0)
                    if our_league_id == 0:
                        continue

                    participants = f.get("participants", [])
                    home_p = next((p for p in participants if p.get("meta", {}).get("location") == "home"), None)
                    away_p = next((p for p in participants if p.get("meta", {}).get("location") == "away"), None)
                    if not home_p or not away_p:
                        continue

                    ft_home, ft_away = _extract_scores(
                        f.get("scores", []), home_p["id"], away_p["id"]
                    )

                    finished.append({
                        "match_id": str(f.get("id", "")),
                        "home_goals": int(ft_home),
                        "away_goals": int(ft_away),
                    })
    except Exception:
        pass
    return finished
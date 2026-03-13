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
    39: "PL",
    140: "PD",
    135: "SA",
    78: "BL1",
    61: "FL1",
    2: "CL",
    3: "EL",
    848: "ECL",
    94: "PPL",
    88: "DED",
}

# ── SoccerFootball league IDs ──
SFI_LEAGUE_MAP = {
    39: "1",
    140: "2",
    135: "3",
    78: "4",
    61: "5",
    2: "132",
    3: "133",
    848: "134",
    94: "6",
    88: "7",
}

# ── SportMonks league IDs (verified) ──
SM_LEAGUE_MAP = {
    39: 8,
    140: 564,
    135: 384,
    78: 82,
    61: 301,
    2: 2,
    3: 5,
    848: 2286,
}

# ── SportMonks current season IDs (verified) ──
SM_SEASON_MAP = {
    2: 25580,    # Champions League 2025/26
    3: 25582,    # Europa League 2025/26
    848: 25581,  # Conference League 2025/26
}

# ── football-data.org → our league_id ──
API_TO_OUR = {
    2021: 39,
    2014: 140,
    2019: 135,
    2002: 78,
    2015: 61,
    2001: 2,
    2146: 3,
    2154: 848,
    2017: 94,
    2003: 88,
}


# ══════════════════════════════════════════
#  TEAMS
# ══════════════════════════════════════════

async def _get_teams_sportmonks(league_id: int, season: int) -> list:
    """Get teams from SportMonks API using season endpoint"""
    if not SM_KEY:
        return []
    season_id = SM_SEASON_MAP.get(league_id)
    if not season_id:
        return []
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{SM_URL}/teams/seasons/{season_id}",
                params={"api_token": SM_KEY, "per_page": 50},
            )
            if r.status_code == 200:
                teams = []
                for t in r.json().get("data", []):
                    if t.get("placeholder"):
                        continue
                    name = t.get("name") or t.get("short_code", "")
                    if t.get("id") and name:
                        teams.append({
                            "id": t["id"],
                            "name": name,
                            "source": "sportmonks",
                        })
                return teams
    except Exception:
        pass
    return []


async def get_teams(league_id: int, season: int) -> list:
    """Fetch teams — tries SportMonks first, then SoccerFootball, then football-data.org"""
    teams = []
    seen = set()

    # ── API 3: SportMonks (best coverage for Europa/Conference) ──
    sm_teams = await _get_teams_sportmonks(league_id, season)
    for t in sm_teams:
        if t["id"] not in seen:
            teams.append(t)
            seen.add(t["id"])

    # ── API 2: SoccerFootball ──
    if len(teams) < 5:
        sfi_league = SFI_LEAGUE_MAP.get(league_id)
        if sfi_league and SFI_KEY:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    r = await client.get(
                        f"{SFI_URL}/teams/by/league/",
                        headers=SFI_HEADERS,
                        params={"league_id": sfi_league, "season": str(season)},
                    )
                    if r.status_code == 200:
                        for t in r.json().get("result", []):
                            tid = t.get("id") or t.get("team_id")
                            name = t.get("name") or t.get("team_name")
                            if tid and name and tid not in seen:
                                teams.append({"id": tid, "name": name, "source": "sfi"})
                                seen.add(tid)
            except Exception:
                pass

    # ── API 1: football-data.org ──
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
    """Search teams by name — filtered by league if provided"""
    results = []
    seen = set()

    # ── SportMonks search (best for Europa/Conference) ──
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
                            results.append({"id": tid, "name": name})
                            seen.add(tid)
        except Exception:
            pass

    # ── SoccerFootball search ──
    if len(results) < 4 and SFI_KEY:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{SFI_URL}/teams/search/",
                    headers=SFI_HEADERS,
                    params={"name": query},
                )
                if r.status_code == 200:
                    for t in r.json().get("result", [])[:6]:
                        tid = t.get("id") or t.get("team_id")
                        name = t.get("name") or t.get("team_name")
                        if tid and name and tid not in seen:
                            results.append({"id": tid, "name": name})
                            seen.add(tid)
        except Exception:
            pass

    # ── football-data.org fallback ──
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
                            results.append({"id": t["id"], "name": t["name"]})
                            seen.add(t["id"])
        except Exception:
            pass

    return results[:8]


# ══════════════════════════════════════════
#  TEAM STATS
# ══════════════════════════════════════════

async def _get_stats_sportmonks(team_id: int, league_id: int, season: int) -> dict:
    """Get team stats from SportMonks"""
    sm_league = SM_LEAGUE_MAP.get(league_id)
    if not sm_league or not SM_KEY:
        return {}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{SM_URL}/statistics/seasons/teams/{team_id}",
                params={
                    "api_token": SM_KEY,
                    "filters": f"leagueId:{sm_league}",
                    "include": "details",
                },
            )
            if r.status_code != 200:
                return {}
            data = r.json().get("data", [])
            if not data:
                return {}
            s = data[0]
            details = {d.get("type", {}).get("developer_name", ""): d.get("value", {}) for d in s.get("details", [])}

            wins = details.get("WINS", {}).get("total", 0) or 0
            draws = details.get("DRAWS", {}).get("total", 0) or 0
            losses = details.get("LOST", {}).get("total", 0) or 0
            gf = details.get("GOALS", {}).get("home", 0) + details.get("GOALS", {}).get("away", 0) or 0
            ga = details.get("GOALS_CONCEDED", {}).get("home", 0) + details.get("GOALS_CONCEDED", {}).get("away", 0) or 0
            played = wins + draws + losses or 1

            return {
                "wins": wins,
                "draws": draws,
                "losses": losses,
                "goals_for_avg": round(gf / played, 2),
                "goals_against_avg": round(ga / played, 2),
                "form": [],
                "source": "sportmonks",
            }
    except Exception:
        return {}


async def _get_stats_sfi(team_id: int, league_id: int, season: int) -> dict:
    """Get team stats from SoccerFootball API"""
    sfi_league = SFI_LEAGUE_MAP.get(league_id)
    if not sfi_league or not SFI_KEY:
        return {}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{SFI_URL}/statistics/teams/by/league/season/",
                headers=SFI_HEADERS,
                params={"team_id": str(team_id), "league_id": sfi_league, "season": str(season)},
            )
            if r.status_code != 200:
                return {}
            result = r.json().get("result", [])
            if not result:
                return {}
            s = result[0]
            played = s.get("played", 0) or 1
            gf = s.get("goals_for", 0) or 0
            ga = s.get("goals_against", 0) or 0
            form_str = s.get("form", "") or ""
            form = [c for c in form_str.upper() if c in ("W", "D", "L")][-5:]
            return {
                "form": form,
                "wins": s.get("wins", 0) or 0,
                "draws": s.get("draws", 0) or 0,
                "losses": s.get("losses", 0) or 0,
                "goals_for_avg": round(gf / played, 2),
                "goals_against_avg": round(ga / played, 2),
                "source": "sfi",
            }
    except Exception:
        return {}


async def _get_stats_fdorg(team_id: int) -> dict:
    """Get team stats from football-data.org"""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{FDORG_URL}/teams/{team_id}/matches",
                headers=FDORG_HEADERS,
                params={"status": "FINISHED", "limit": 10},
            )
            if r.status_code != 200:
                return {}
            matches = r.json().get("matches", [])
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

            played = wins + draws + losses or 1
            return {
                "form": form,
                "wins": wins,
                "draws": draws,
                "losses": losses,
                "goals_for_avg": round(goals_for / played, 2),
                "goals_against_avg": round(goals_against / played, 2),
                "source": "fdorg",
            }
    except Exception:
        return {}


async def get_team_stats(team_id: int, league_id: int, season: int) -> dict:
    """Merge stats from all APIs for best accuracy"""
    sm_stats = await _get_stats_sportmonks(team_id, league_id, season)
    sfi_stats = await _get_stats_sfi(team_id, league_id, season)
    fdorg_stats = await _get_stats_fdorg(team_id)

    if not sm_stats and not sfi_stats and not fdorg_stats:
        return {}

    # Best form: fdorg (match-by-match)
    best_form = (fdorg_stats.get("form") or sfi_stats.get("form") or sm_stats.get("form") or [])

    # Best stats: sportmonks > sfi > fdorg
    best_stats = sm_stats or sfi_stats or fdorg_stats

    # Merge goals averages if multiple sources
    sources = [s for s in [sm_stats, sfi_stats, fdorg_stats] if s]
    if len(sources) >= 2:
        gf_avg = round(sum(s.get("goals_for_avg", 1.2) for s in sources) / len(sources), 2)
        ga_avg = round(sum(s.get("goals_against_avg", 1.2) for s in sources) / len(sources), 2)
    else:
        gf_avg = best_stats.get("goals_for_avg", 1.2)
        ga_avg = best_stats.get("goals_against_avg", 1.2)

    return {
        "form": best_form,
        "wins": best_stats.get("wins", 0),
        "draws": best_stats.get("draws", 0),
        "losses": best_stats.get("losses", 0),
        "goals_for_avg": gf_avg,
        "goals_against_avg": ga_avg,
        "source": "merged" if len(sources) >= 2 else best_stats.get("source", "unknown"),
    }


# ══════════════════════════════════════════
#  H2H
# ══════════════════════════════════════════

async def get_h2h(team1_id: int, team2_id: int, last: int = 10) -> list:
    """Get head-to-head results"""
    h2h = []
    seen_ids = set()

    # ── SoccerFootball H2H ──
    if SFI_KEY:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{SFI_URL}/fixtures/h2h/",
                    headers=SFI_HEADERS,
                    params={"team1_id": str(team1_id), "team2_id": str(team2_id), "limit": str(last)},
                )
                if r.status_code == 200:
                    for m in r.json().get("result", []):
                        mid = m.get("id") or m.get("fixture_id")
                        hg = m.get("score", {}).get("home") or m.get("home_goals")
                        ag = m.get("score", {}).get("away") or m.get("away_goals")
                        hid = m.get("home_team", {}).get("id") or m.get("home_team_id")
                        aid = m.get("away_team", {}).get("id") or m.get("away_team_id")
                        if mid and hg is not None and ag is not None and mid not in seen_ids:
                            h2h.append({
                                "match_id": mid,
                                "teams": {"home": {"id": hid}, "away": {"id": aid}},
                                "goals": {"home": hg, "away": ag},
                            })
                            seen_ids.add(mid)
        except Exception:
            pass

    # ── football-data.org fallback ──
    if len(h2h) < 5:
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
    """Fetch all matches today"""
    today = date.today().isoformat()
    all_matches = []
    seen_ids = set()

    # ── SoccerFootball ──
    if SFI_KEY:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(
                    f"{SFI_URL}/fixtures/by/date/",
                    headers=SFI_HEADERS,
                    params={"date": today},
                )
                if r.status_code == 200:
                    sfi_to_our = {v: k for k, v in SFI_LEAGUE_MAP.items()}
                    for m in r.json().get("result", []):
                        mid = str(m.get("id") or m.get("fixture_id") or "")
                        if not mid or mid in seen_ids:
                            continue
                        seen_ids.add(mid)
                        league_info = m.get("league", {}) or {}
                        our_league_id = sfi_to_our.get(str(league_info.get("id", "")), 0)
                        home = m.get("home_team", {}) or {}
                        away = m.get("away_team", {}) or {}
                        all_matches.append({
                            "match_id": mid,
                            "home_team": {"id": home.get("id", 0), "name": home.get("name", "")},
                            "away_team": {"id": away.get("id", 0), "name": away.get("name", "")},
                            "league_id": our_league_id,
                            "league_name": league_info.get("name", ""),
                            "kickoff": m.get("date") or m.get("kickoff") or "",
                            "status": m.get("status", "SCHEDULED"),
                            "score": None,
                            "source": "sfi",
                        })
        except Exception:
            pass

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
                    competition = m.get("competition", {})
                    our_league_id = API_TO_OUR.get(competition.get("id", 0), competition.get("id", 0))
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
#  FETCH RESULTS (for accuracy tracking)
# ══════════════════════════════════════════

async def get_finished_matches(target_date: str) -> list:
    """Fetch finished matches for a given date"""
    finished = []

    if SFI_KEY:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(
                    f"{SFI_URL}/fixtures/by/date/",
                    headers=SFI_HEADERS,
                    params={"date": target_date},
                )
                if r.status_code == 200:
                    for m in r.json().get("result", []):
                        if m.get("status", "") not in ("FT", "FINISHED", "finished", "AET", "PEN"):
                            continue
                        score = m.get("score", {}) or {}
                        hg = score.get("home")
                        ag = score.get("away")
                        if hg is None or ag is None:
                            continue
                        finished.append({
                            "match_id": str(m.get("id") or m.get("fixture_id")),
                            "home_goals": int(hg),
                            "away_goals": int(ag),
                        })
        except Exception:
            pass

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{FDORG_URL}/matches",
                headers=FDORG_HEADERS,
                params={"dateFrom": target_date, "dateTo": target_date, "status": "FINISHED"},
            )
            if r.status_code == 200:
                seen = {f["match_id"] for f in finished}
                for m in r.json().get("matches", []):
                    mid = str(m.get("id", ""))
                    if mid in seen:
                        continue
                    hg = m["score"]["fullTime"]["home"]
                    ag = m["score"]["fullTime"]["away"]
                    if hg is None or ag is None:
                        continue
                    finished.append({
                        "match_id": mid,
                        "home_goals": int(hg),
                        "away_goals": int(ag),
                    })
    except Exception:
        pass

    return finished
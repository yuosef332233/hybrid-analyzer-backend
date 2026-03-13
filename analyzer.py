def form_to_score(form: list) -> float:
    return sum(20 if r == "W" else 10 if r == "D" else 0 for r in form)


def compute_rating(stats: dict) -> float:
    if not stats:
        return 65.0
    gf = stats.get("goals_for_avg", 1.2)
    ga = stats.get("goals_against_avg", 1.2)
    w = stats.get("wins", 0)
    l = stats.get("losses", 0)
    source_bonus = 2 if stats.get("source") == "merged" else 0
    rating = 65 + (gf - ga) * 10 + (w - l) * 3 + source_bonus
    return round(min(95, max(40, rating)), 1)


def auto_context(stats: dict, team_name: str, is_home: bool) -> dict:
    if not stats:
        return {"mod": 0, "factors": []}

    form = stats.get("form", [])
    gf = stats.get("goals_for_avg", 1.2)
    ga = stats.get("goals_against_avg", 1.2)

    mod = 0
    factors = []

    if is_home:
        mod += 5
        factors.append({"icon": "🏟️", "label": "Home ground advantage", "impact": 5, "type": "positive"})

    recent = form[-5:] if len(form) >= 5 else form
    win_count = recent.count("W")
    loss_count = recent.count("L")

    if win_count >= 4:
        mod += 12
        factors.append({"icon": "🔥", "label": f"Excellent form — {win_count} wins in last 5", "impact": 12, "type": "positive"})
    elif win_count >= 3:
        mod += 7
        factors.append({"icon": "⚡", "label": f"Good form — {win_count} wins in last 5", "impact": 7, "type": "positive"})
    elif loss_count >= 4:
        mod -= 12
        factors.append({"icon": "📉", "label": f"Poor form — {loss_count} losses in last 5", "impact": -12, "type": "negative"})
    elif loss_count >= 3:
        mod -= 7
        factors.append({"icon": "⚠️", "label": f"Struggling — {loss_count} losses in last 5", "impact": -7, "type": "negative"})

    if len(form) >= 3:
        last3 = form[-3:]
        if all(r == "W" for r in last3):
            mod += 5
            factors.append({"icon": "✨", "label": "3-game winning streak", "impact": 5, "type": "positive"})
        elif all(r == "L" for r in last3):
            mod -= 5
            factors.append({"icon": "💔", "label": "3-game losing streak", "impact": -5, "type": "negative"})

    if gf >= 2.5:
        mod += 8
        factors.append({"icon": "⚽", "label": f"Clinical attack — {gf} goals/game avg", "impact": 8, "type": "positive"})
    elif gf >= 1.8:
        mod += 4
        factors.append({"icon": "🎯", "label": f"Solid attack — {gf} goals/game avg", "impact": 4, "type": "positive"})
    elif gf <= 0.8:
        mod -= 6
        factors.append({"icon": "😶", "label": f"Weak attack — {gf} goals/game avg", "impact": -6, "type": "negative"})

    if ga <= 0.8:
        mod += 7
        factors.append({"icon": "🛡️", "label": f"Solid defense — {ga} goals conceded avg", "impact": 7, "type": "positive"})
    elif ga >= 2.2:
        mod -= 7
        factors.append({"icon": "🚨", "label": f"Leaky defense — {ga} goals conceded avg", "impact": -7, "type": "negative"})
    elif ga >= 1.8:
        mod -= 3
        factors.append({"icon": "😬", "label": f"Vulnerable defense — {ga} goals conceded avg", "impact": -3, "type": "negative"})

    if stats.get("source") == "merged":
        mod += 2

    return {"mod": mod, "factors": factors}


def analyze_h2h(h2h_fixtures: list, home_team_id: int, away_team_id: int) -> dict:
    if not h2h_fixtures:
        return {"mod": 0, "home_wins": 0, "away_wins": 0, "draws": 0, "total": 0}

    home_wins = away_wins = draws = 0

    for m in h2h_fixtures:
        goals = m.get("goals", {})
        hg = goals.get("home", 0) or 0
        ag = goals.get("away", 0) or 0
        teams = m.get("teams", {})
        match_home_id = teams.get("home", {}).get("id")

        if match_home_id == home_team_id:
            if hg > ag: home_wins += 1
            elif ag > hg: away_wins += 1
            else: draws += 1
        else:
            if ag > hg: home_wins += 1
            elif hg > ag: away_wins += 1
            else: draws += 1

    total = home_wins + away_wins + draws
    if total == 0:
        return {"mod": 0, "home_wins": 0, "away_wins": 0, "draws": 0, "total": 0}

    mod = 0
    if home_wins / total >= 0.6: mod += 6
    elif away_wins / total >= 0.6: mod -= 6
    elif home_wins > away_wins: mod += 3
    elif away_wins > home_wins: mod -= 3

    return {"mod": mod, "home_wins": home_wins, "away_wins": away_wins, "draws": draws, "total": total}


def predict_score(home_stats, away_stats, home_rating: float, away_rating: float) -> tuple:
    """
    Smart score prediction based on actual stats.
    Uses goals averages + rating difference as weight.
    No forced results — pure data-driven.
    """
    gf_home = home_stats.get("goals_for_avg", 1.2) if home_stats else 1.2
    ga_away = away_stats.get("goals_against_avg", 1.2) if away_stats else 1.2
    gf_away = away_stats.get("goals_for_avg", 1.2) if away_stats else 1.2
    ga_home = home_stats.get("goals_against_avg", 1.2) if home_stats else 1.2

    # Expected goals = avg of team attack vs opponent defense
    exp_home = (gf_home + ga_away) / 2
    exp_away = (gf_away + ga_home) / 2

    # Rating difference adds small weight (max ±0.4 goals)
    rating_diff = (home_rating - away_rating) / 100
    exp_home += rating_diff * 0.4
    exp_away -= rating_diff * 0.4

    # Clamp to realistic range
    home_goals = max(0, min(5, round(exp_home)))
    away_goals = max(0, min(5, round(exp_away)))

    return home_goals, away_goals


def run_analysis(home_stats, away_stats, h2h_fixtures,
                 home_team_id: int,
                 away_team_id: int = 0,
                 home_context: str = "",
                 away_context: str = "") -> dict:

    home_form = home_stats.get("form", ["D","D","D","D","D"]) if home_stats else ["D","D","D","D","D"]
    away_form = away_stats.get("form", ["D","D","D","D","D"]) if away_stats else ["D","D","D","D","D"]

    home_rating = compute_rating(home_stats)
    away_rating = compute_rating(away_stats)

    home_momentum = form_to_score(home_form)
    away_momentum = form_to_score(away_form)

    home_ctx = auto_context(home_stats, "home", is_home=True)
    away_ctx = auto_context(away_stats, "away", is_home=False)

    h2h_analysis = analyze_h2h(h2h_fixtures, home_team_id, away_team_id)
    h2h_mod = h2h_analysis["mod"]

    home_score = (home_rating * 0.40) + (home_momentum * 0.30) + home_ctx["mod"] + h2h_mod
    away_score = (away_rating * 0.40) + (away_momentum * 0.30) + away_ctx["mod"]

    total = home_score + away_score
    home_win = max(15, min(72, (home_score / total) * 100))
    away_win = max(10, min(65, (away_score / total) * 90))
    draw = max(10, min(38, 100 - home_win - away_win + 18))

    s = home_win + draw + away_win
    home_win = round(home_win / s * 100)
    away_win = round(away_win / s * 100)
    draw = 100 - home_win - away_win

    gap = abs(home_score - away_score)
    data_bonus = 5 if (
        home_stats and home_stats.get("source") == "merged" and
        away_stats and away_stats.get("source") == "merged"
    ) else 0
    confidence = round(min(93, max(38, 50 + gap * 1.2 + data_bonus)))

    if home_win >= 52 and confidence >= 62:
        decision, dtype = "SOLID (1)", "solid"
    elif away_win >= 46 and confidence >= 60:
        decision, dtype = "SOLID (2)", "solid"
    elif draw >= 28 and abs(home_win - away_win) < 14:
        decision, dtype = "VALUE X", "value"
    elif confidence < 52:
        decision, dtype = "AVOID", "avoid"
    else:
        decision, dtype = "VALUE", "value"

    # ── Smart score — data-driven ──
    home_goals, away_goals = predict_score(home_stats, away_stats, home_rating, away_rating)

    context_factors = []
    for f in home_ctx["factors"]:
        context_factors.append({**f, "team": "home"})
    for f in away_ctx["factors"]:
        context_factors.append({**f, "team": "away"})

    if h2h_analysis["total"] >= 3:
        if h2h_mod > 0:
            context_factors.append({
                "icon": "📊", "team": "home",
                "label": f"H2H dominance — {h2h_analysis['home_wins']}W/{h2h_analysis['draws']}D/{h2h_analysis['away_wins']}L in last {h2h_analysis['total']}",
                "impact": h2h_mod, "type": "positive"
            })
        elif h2h_mod < 0:
            context_factors.append({
                "icon": "📊", "team": "away",
                "label": f"H2H advantage — {h2h_analysis['away_wins']}W/{h2h_analysis['draws']}D/{h2h_analysis['home_wins']}L in last {h2h_analysis['total']}",
                "impact": h2h_mod, "type": "negative"
            })

    return {
        "home_win_prob": home_win,
        "draw_prob": draw,
        "away_win_prob": away_win,
        "home_rating": home_rating,
        "away_rating": away_rating,
        "home_form": home_form,
        "away_form": away_form,
        "confidence": confidence,
        "decision": decision,
        "decision_type": dtype,
        "predicted_home_goals": home_goals,
        "predicted_away_goals": away_goals,
        "context_factors": context_factors,
        "h2h": h2h_analysis,
        "data_source": home_stats.get("source", "unknown") if home_stats else "none",
    }


def build_recommendations(predictions: list) -> dict:
    if not predictions:
        return {"solid_picks": [], "value_picks": []}

    solid = []
    for p in predictions:
        conf = p.get("confidence", 0)
        hw = p.get("home_win_prob", 0)
        aw = p.get("away_win_prob", 0)
        dw = p.get("draw_prob", 0)
        max_prob = max(hw, aw, dw)

        if conf >= 65 and max_prob >= 50:
            if hw == max_prob:
                pick, outcome, prob = p["home_team"], "Win", hw
            elif aw == max_prob:
                pick, outcome, prob = p["away_team"], "Win", aw
            else:
                pick, outcome, prob = "Draw", "Draw", dw

            solid.append({
                "match": f"{p['home_team']} vs {p['away_team']}",
                "league": p.get("league", ""),
                "pick": pick,
                "outcome": outcome,
                "probability": prob,
                "confidence": conf,
                "kickoff": p.get("kickoff", ""),
                "predicted_score": p.get("predicted_score", ""),
                "reason": f"AI confidence {conf}% — {pick} at {prob}% probability",
            })

    solid = sorted(solid, key=lambda x: x["confidence"], reverse=True)[:5]

    value = []
    for p in predictions:
        hw = p.get("home_win_prob", 0)
        aw = p.get("away_win_prob", 0)
        conf = p.get("confidence", 0)

        if aw >= 35 and hw > aw and conf >= 55:
            gap = hw - aw
            if gap <= 20:
                value.append({
                    "match": f"{p['home_team']} vs {p['away_team']}",
                    "league": p.get("league", ""),
                    "pick": p["away_team"],
                    "outcome": "Upset Win",
                    "probability": aw,
                    "confidence": conf,
                    "kickoff": p.get("kickoff", ""),
                    "reason": f"AI gives {p['away_team']} {aw}% despite being away — gap only {gap}%",
                    "predicted_score": p.get("predicted_score", ""),
                })
        elif hw >= 30 and aw > hw and conf >= 55:
            gap = aw - hw
            if gap <= 18:
                value.append({
                    "match": f"{p['home_team']} vs {p['away_team']}",
                    "league": p.get("league", ""),
                    "pick": p["home_team"],
                    "outcome": "Home Upset",
                    "probability": hw,
                    "confidence": conf,
                    "kickoff": p.get("kickoff", ""),
                    "reason": f"AI gives {p['home_team']} {hw}% at home despite being underdogs — gap only {gap}%",
                    "predicted_score": p.get("predicted_score", ""),
                })

    value = sorted(value, key=lambda x: x["probability"], reverse=True)[:5]

    return {"solid_picks": solid, "value_picks": value}
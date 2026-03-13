def form_to_score(form: list) -> float:
    return sum(20 if r == "W" else 10 if r == "D" else 0 for r in form)

def compute_rating(stats: dict) -> float:
    if not stats:
        return 65.0
    gf = stats.get("goals_for_avg", 1.2)
    ga = stats.get("goals_against_avg", 1.2)
    w = stats.get("wins", 0)
    l = stats.get("losses", 0)
    rating = 65 + (gf - ga) * 10 + (w - l) * 3
    return round(min(95, max(40, rating)), 1)

def auto_context(stats: dict, team_name: str, is_home: bool) -> dict:
    if not stats:
        return {"mod": 0, "factors": []}

    form = stats.get("form", [])
    gf = stats.get("goals_for_avg", 1.2)
    ga = stats.get("goals_against_avg", 1.2)
    wins = stats.get("wins", 0)
    losses = stats.get("losses", 0)

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

    return {"mod": mod, "factors": factors}


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

    home_ctx_mod = home_ctx["mod"]
    away_ctx_mod = away_ctx["mod"]

    home_score = (home_rating * 0.45) + (home_momentum * 0.35) + home_ctx_mod
    away_score = (away_rating * 0.45) + (away_momentum * 0.35) + away_ctx_mod

    total = home_score + away_score
    home_win = max(15, min(72, (home_score / total) * 100))
    away_win = max(10, min(65, (away_score / total) * 90))
    draw = max(10, min(38, 100 - home_win - away_win + 18))

    s = home_win + draw + away_win
    home_win = round(home_win / s * 100)
    away_win = round(away_win / s * 100)
    draw = 100 - home_win - away_win

    gap = abs(home_score - away_score)
    confidence = round(min(91, max(38, 50 + gap * 1.2)))

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

    gf_home = home_stats.get("goals_for_avg", 1.2) if home_stats else 1.2
    ga_away = away_stats.get("goals_against_avg", 1.2) if away_stats else 1.2
    gf_away = away_stats.get("goals_for_avg", 1.2) if away_stats else 1.2
    ga_home = home_stats.get("goals_against_avg", 1.2) if home_stats else 1.2

    home_goals = max(0, min(4, round((gf_home + ga_away) / 2)))
    away_goals = max(0, min(4, round((gf_away + ga_home) / 2 - 0.3)))

    context_factors = []
    for f in home_ctx["factors"]:
        context_factors.append({**f, "team": "home"})
    for f in away_ctx["factors"]:
        context_factors.append({**f, "team": "away"})

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
    }


def build_recommendations(predictions: list) -> dict:
    """
    Build two recommendation lists from today's predictions:
    1. solid_picks — top 5 most confident predictions
    2. value_picks — top 5 'against the tide' (underdog likely to win)
    """
    if not predictions:
        return {"solid_picks": [], "value_picks": []}

    # ── Solid picks: high confidence + clear winner ──
    solid = []
    for p in predictions:
        conf = p.get("confidence", 0)
        hw = p.get("home_win_prob", 0)
        aw = p.get("away_win_prob", 0)
        dw = p.get("draw_prob", 0)

        max_prob = max(hw, aw, dw)
        if conf >= 65 and max_prob >= 50:
            if hw == max_prob:
                pick = p["home_team"]
                outcome = "Win"
                prob = hw
            elif aw == max_prob:
                pick = p["away_team"]
                outcome = "Win"
                prob = aw
            else:
                pick = "Draw"
                outcome = "Draw"
                prob = dw

            solid.append({
                "match": f"{p['home_team']} vs {p['away_team']}",
                "league": p.get("league", ""),
                "pick": pick,
                "outcome": outcome,
                "probability": prob,
                "confidence": conf,
                "kickoff": p.get("kickoff", ""),
                "predicted_score": p.get("predicted_score", ""),
            })

    # Sort by confidence desc, take top 5
    solid = sorted(solid, key=lambda x: x["confidence"], reverse=True)[:5]

    # ── Value picks: underdog has higher AI probability than expected ──
    # "Against the tide" = away team wins but home_win_prob > away_win_prob
    # OR home_win_prob is low but AI still picks home
    value = []
    for p in predictions:
        hw = p.get("home_win_prob", 0)
        aw = p.get("away_win_prob", 0)
        conf = p.get("confidence", 0)

        # Away underdog: away_win_prob surprisingly high (>=35%) but lower than home
        if aw >= 35 and hw > aw and conf >= 55:
            gap = hw - aw
            if gap <= 20:  # Close gap = real upset potential
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

        # Home underdog: home team has surprisingly low prob but AI still sees value
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

    # Sort by probability desc, take top 5
    value = sorted(value, key=lambda x: x["probability"], reverse=True)[:5]

    return {
        "solid_picks": solid,
        "value_picks": value,
    }
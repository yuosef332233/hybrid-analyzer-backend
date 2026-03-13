import db as _db

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


def auto_context(stats: dict, team_name: str, is_home: bool, weights: dict) -> dict:
    if not stats:
        return {"mod": 0, "factors": []}

    form = stats.get("form", [])
    gf = stats.get("goals_for_avg", 1.2)
    ga = stats.get("goals_against_avg", 1.2)

    mod = 0
    factors = []

    home_adv = weights.get("home_advantage", 5.0)
    if is_home:
        mod += home_adv
        factors.append({"icon": "🏟️", "label": "Home ground advantage", "impact": home_adv, "type": "positive"})

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
        match_home_id = m.get("teams", {}).get("home", {}).get("id")
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
    gf_home = home_stats.get("goals_for_avg", 1.2) if home_stats else 1.2
    ga_away = away_stats.get("goals_against_avg", 1.2) if away_stats else 1.2
    gf_away = away_stats.get("goals_for_avg", 1.2) if away_stats else 1.2
    ga_home = home_stats.get("goals_against_avg", 1.2) if home_stats else 1.2

    exp_home = (gf_home + ga_away) / 2
    exp_away = (gf_away + ga_home) / 2

    rating_diff = (home_rating - away_rating) / 100
    exp_home += rating_diff * 0.4
    exp_away -= rating_diff * 0.4

    return max(0, min(5, round(exp_home))), max(0, min(5, round(exp_away)))


def run_analysis(home_stats, away_stats, h2h_fixtures,
                 home_team_id: int,
                 away_team_id: int = 0,
                 home_context: str = "",
                 away_context: str = "") -> dict:

    # ── Load learned weights ──
    try:
        weights = _db.get_weights()
    except Exception:
        weights = _db.DEFAULT_WEIGHTS.copy()

    home_form = home_stats.get("form", ["D","D","D","D","D"]) if home_stats else ["D","D","D","D","D"]
    away_form = away_stats.get("form", ["D","D","D","D","D"]) if away_stats else ["D","D","D","D","D"]

    home_rating = compute_rating(home_stats)
    away_rating = compute_rating(away_stats)

    home_momentum = form_to_score(home_form)
    away_momentum = form_to_score(away_form)

    home_ctx = auto_context(home_stats, "home", is_home=True, weights=weights)
    away_ctx = auto_context(away_stats, "away", is_home=False, weights=weights)

    h2h_analysis = analyze_h2h(h2h_fixtures, home_team_id, away_team_id)
    h2h_mod = h2h_analysis["mod"]

    # ── Use learned weights ──
    r_w = weights.get("rating_weight", 0.40)
    f_w = weights.get("form_weight", 0.30)

    home_score = (home_rating * r_w) + (home_momentum * f_w) + home_ctx["mod"] + h2h_mod
    away_score = (away_rating * r_w) + (away_momentum * f_w) + away_ctx["mod"]

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

    # ── Use learned thresholds ──
    solid1_t = weights.get("solid1_threshold", 52)
    solid2_t = weights.get("solid2_threshold", 46)
    conf_min = weights.get("confidence_min", 62)
    draw_t   = weights.get("draw_threshold", 28)
    avoid_t  = weights.get("avoid_threshold", 52)

    if home_win >= solid1_t and confidence >= conf_min:
        decision, dtype = "SOLID (1)", "solid"
    elif away_win >= solid2_t and confidence >= conf_min:
        decision, dtype = "SOLID (2)", "solid"
    elif draw >= draw_t and abs(home_win - away_win) < 14:
        decision, dtype = "VALUE X", "value"
    elif confidence < avoid_t:
        decision, dtype = "AVOID", "avoid"
    else:
        decision, dtype = "VALUE", "value"

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
        "weights_version": weights.get("version", 1),
    }


def learn_from_history() -> dict:
    """
    Analyze past predictions and adjust weights to improve accuracy.
    Called automatically every night after accuracy is updated.
    """
    try:
        current_weights = _db.get_weights()
        stats = _db.get_overall_stats()
        decision_acc = _db.get_decision_accuracy()
        conf_acc = _db.get_confidence_accuracy()

        total = stats.get("total_predictions", 0)
        if total < 10:
            return {"message": "Not enough data yet — need at least 10 predictions", "learned": False}

        overall_acc = stats.get("overall_accuracy", 0)
        new_weights = current_weights.copy()
        changes = []

        # ── Learn from decision accuracy ──
        solid1_acc = decision_acc.get("SOLID (1)", {}).get("accuracy", 50)
        solid2_acc = decision_acc.get("SOLID (2)", {}).get("accuracy", 50)
        avoid_acc  = decision_acc.get("AVOID", {}).get("accuracy", 50)
        draw_acc   = decision_acc.get("VALUE X", {}).get("accuracy", 50)

        # If SOLID (1) accuracy is low → raise threshold (be more selective)
        if solid1_acc < 55 and decision_acc.get("SOLID (1)", {}).get("total", 0) >= 5:
            new_weights["solid1_threshold"] = min(60, current_weights["solid1_threshold"] + 1)
            changes.append(f"SOLID(1) accuracy {solid1_acc}% → raised threshold to {new_weights['solid1_threshold']}")

        # If SOLID (1) accuracy is high → lower threshold slightly (catch more)
        elif solid1_acc > 72 and decision_acc.get("SOLID (1)", {}).get("total", 0) >= 5:
            new_weights["solid1_threshold"] = max(48, current_weights["solid1_threshold"] - 1)
            changes.append(f"SOLID(1) accuracy {solid1_acc}% → lowered threshold to {new_weights['solid1_threshold']}")

        # Same for SOLID (2)
        if solid2_acc < 50 and decision_acc.get("SOLID (2)", {}).get("total", 0) >= 5:
            new_weights["solid2_threshold"] = min(55, current_weights["solid2_threshold"] + 1)
            changes.append(f"SOLID(2) accuracy {solid2_acc}% → raised threshold to {new_weights['solid2_threshold']}")
        elif solid2_acc > 68 and decision_acc.get("SOLID (2)", {}).get("total", 0) >= 5:
            new_weights["solid2_threshold"] = max(42, current_weights["solid2_threshold"] - 1)
            changes.append(f"SOLID(2) accuracy {solid2_acc}% → lowered threshold to {new_weights['solid2_threshold']}")

        # If AVOID accuracy is low → lower the avoid threshold (avoid less, predict more)
        if avoid_acc < 45 and decision_acc.get("AVOID", {}).get("total", 0) >= 5:
            new_weights["avoid_threshold"] = max(48, current_weights["avoid_threshold"] - 1)
            changes.append(f"AVOID accuracy {avoid_acc}% → lowered avoid threshold to {new_weights['avoid_threshold']}")
        elif avoid_acc > 65:
            new_weights["avoid_threshold"] = min(58, current_weights["avoid_threshold"] + 1)
            changes.append(f"AVOID accuracy {avoid_acc}% → raised avoid threshold to {new_weights['avoid_threshold']}")

        # Draw accuracy
        if draw_acc < 30 and decision_acc.get("VALUE X", {}).get("total", 0) >= 5:
            new_weights["draw_threshold"] = min(35, current_weights["draw_threshold"] + 1)
            changes.append(f"Draw accuracy {draw_acc}% → raised draw threshold to {new_weights['draw_threshold']}")
        elif draw_acc > 50 and decision_acc.get("VALUE X", {}).get("total", 0) >= 5:
            new_weights["draw_threshold"] = max(22, current_weights["draw_threshold"] - 1)
            changes.append(f"Draw accuracy {draw_acc}% → lowered draw threshold to {new_weights['draw_threshold']}")

        # ── Learn from confidence buckets ──
        for bucket in conf_acc:
            b = bucket.get("bucket")
            b_total = bucket.get("total", 0)
            b_correct = bucket.get("correct_count", 0)
            b_acc = round(b_correct / b_total * 100, 1) if b_total > 0 else 0

            # If high confidence predictions are wrong often → raise confidence minimum
            if b == "high" and b_acc < 50 and b_total >= 5:
                new_weights["confidence_min"] = min(70, current_weights["confidence_min"] + 1)
                changes.append(f"High confidence bucket accuracy {b_acc}% → raised conf_min to {new_weights['confidence_min']}")
            elif b == "high" and b_acc > 70 and b_total >= 5:
                new_weights["confidence_min"] = max(58, current_weights["confidence_min"] - 1)
                changes.append(f"High confidence bucket accuracy {b_acc}% → lowered conf_min to {new_weights['confidence_min']}")

        if not changes:
            return {
                "message": "No adjustments needed — current weights performing well",
                "learned": False,
                "overall_accuracy": overall_acc,
                "weights_version": current_weights.get("version", 1),
            }

        # Save new weights
        _db.save_weights(new_weights, overall_acc, total, changes)

        return {
            "message": f"Learned {len(changes)} adjustments",
            "learned": True,
            "changes": changes,
            "overall_accuracy": overall_acc,
            "old_weights": current_weights,
            "new_weights": new_weights,
            "weights_version": new_weights.get("version", 1),
        }

    except Exception as e:
        return {"message": f"Learning error: {str(e)}", "learned": False}


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
            if hw == max_prob: pick, outcome, prob = p["home_team"], "Win", hw
            elif aw == max_prob: pick, outcome, prob = p["away_team"], "Win", aw
            else: pick, outcome, prob = "Draw", "Draw", dw

            solid.append({
                "match": f"{p['home_team']} vs {p['away_team']}",
                "league": p.get("league", ""),
                "pick": pick, "outcome": outcome, "probability": prob,
                "confidence": conf, "kickoff": p.get("kickoff", ""),
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
                    "pick": p["away_team"], "outcome": "Upset Win",
                    "probability": aw, "confidence": conf,
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
                    "pick": p["home_team"], "outcome": "Home Upset",
                    "probability": hw, "confidence": conf,
                    "kickoff": p.get("kickoff", ""),
                    "reason": f"AI gives {p['home_team']} {hw}% at home despite being underdogs — gap only {gap}%",
                    "predicted_score": p.get("predicted_score", ""),
                })

    value = sorted(value, key=lambda x: x["probability"], reverse=True)[:5]
    return {"solid_picks": solid, "value_picks": value}
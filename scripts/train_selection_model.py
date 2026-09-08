"""Offline RF vs logged rules-v2: only displayed, hard-filter-passed candidates."""
import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory, mkdtemp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

VERSION = "selection-rf-v1"
MIN_REQUESTS = 10  # Execution floor, NOT evidence of statistical significance.


def timestamp(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("timezone required")
    return parsed.astimezone(timezone.utc)


def number(value, minimum=0, maximum=1e9):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("numeric snapshot feature required")
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError("out-of-range snapshot feature")
    return float(value)


def features(item, constraints, created_at):
    """Only pre-choice facts. No IDs, names, rank, feedback or future data as features."""
    score = item["score_breakdown"]
    if score["hard_constraints"] != "pass":
        raise ValueError("hard filter did not pass")
    price = number(item["menu"]["price_krw"], 1, 1000000)
    distance = number(item["distance"])
    budget = constraints.get("budget_krw")
    if budget is not None and price > number(budget, 1, 1000000):
        raise ValueError("over budget")
    limit = constraints.get("max_distance_m")
    if limit is not None and distance > number(limit, 1, 20000):
        raise ValueError("too far")
    route = item.get("route")
    seconds = number(route["seconds"]) if route else -1
    walking = constraints.get("walking_minutes_max")
    if walking is not None and (seconds < 0 or seconds > number(walking, 1, 120) * 60):
        raise ValueError("walking constraint failed")
    # Historical snapshots stay historical; never compare their evidence age with today's date.
    weather = score.get("weather_score")
    return {
        "price_krw": price, "distance_m": distance, "walking_seconds": seconds,
        "budget_ratio": price / budget if budget is not None else -1,
        "soft_matches": number(score["soft_matches"], 0, 40),
        "evidence_completeness": number(score["evidence_completeness"], 0, 1),
        "evidence_age_days": number(score["evidence_age_days"], 0, 90),
        "weather_prior": number(weather, -1e6, 1e6) if weather is not None else 0,
        "weather_missing": int(weather is None),
        "category": str(score.get("weather_category") or "unknown")[:80],
        "hour_kst": created_at.astimezone(timezone(timedelta(hours=9))).hour,
        "weekday_kst": created_at.astimezone(timezone(timedelta(hours=9))).weekday(),
    }


def load_groups(database, as_of):
    """Read a consistent, read-only DB snapshot; never turn unobserved choices into negatives."""
    groups, skipped = [], Counter()
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True)) as con:
        con.execute("BEGIN")
        # ponytail: portfolio-sized logs in memory; stream request batches if volume grows.
        requests = con.execute("SELECT id, snapshot_json, created_at FROM recommendation_requests").fetchall()
        events = {}
        for request_id, event_type, place_id, created in con.execute(
                "SELECT request_id, event_type, place_id, created_at FROM events"):
            events.setdefault(request_id, []).append((event_type, place_id, created))
    for request_id, raw, created in requests:
        try:
            started = timestamp(created)
            snapshot = json.loads(raw)
            if started >= as_of:
                skipped["after_cutoff"] += 1
                continue
            if snapshot.get("schema_version") != 3 or snapshot.get("ranking_version") != "rules-v2":
                skipped["unsupported_snapshot_version"] += 1
                continue
            items = snapshot["recommendations"]
            if not 2 <= len(items) <= 3:
                skipped["not_comparable_candidate_count"] += 1
                continue
            if (len({p["id"] for p in items}) != len(items)
                    or [p["rank"] for p in items] != list(range(1, len(items) + 1))):
                raise ValueError("invalid ranks or duplicate candidates")
            rows = [{"place_id": p["id"], "rule_rank": p["rank"],
                     "features": features(p, snapshot["constraints"], started)} for p in items]
            observed = [(kind, pid, timestamp(t)) for kind, pid, t in events.get(request_id, [])]
            observed = [e for e in observed if started <= e[2] < as_of]
            views = [t for kind, _, t in observed if kind == "recommendations_viewed"]
            choices = [(pid, t) for kind, pid, t in observed if kind == "restaurant_selected"]
            if not views or not choices:
                skipped["missing_view_or_selection"] += 1
                continue
            selected = {pid for pid, _ in choices}
            if len(selected) != 1 or not selected.issubset({p["id"] for p in items}):
                skipped["ambiguous_selection"] += 1
                continue
            chosen = next(iter(selected))
            label_at = min(t for _, t in choices)
            if min(views) > label_at or any(kind == "restaurant_rejected" and pid == chosen
                                           for kind, pid, _ in observed):
                skipped["conflicting_feedback"] += 1
                continue
            for row in rows:
                row["label"] = int(row["place_id"] == chosen)
            groups.append({"request_id": request_id, "created_at": started,
                           "label_at": label_at, "rows": rows})
        except (KeyError, TypeError, ValueError, OverflowError, AttributeError):
            skipped["invalid_or_unsafe_snapshot"] += 1
    groups.sort(key=lambda g: (g["created_at"], g["request_id"]))
    return groups, {"requests_total": len(requests), "events_total": sum(map(len, events.values())),
                    "selection_events_total": sum(kind == "restaurant_selected"
                                                  for rows in events.values() for kind, _, _ in rows),
                    "usable_requests": len(groups), "candidate_rows": sum(len(g["rows"]) for g in groups),
                    "excluded_requests": dict(skipped)}


def time_split(groups):
    """Keep entire requests together; training labels must exist before the test period."""
    if len(groups) < MIN_REQUESTS:
        return [], [], None, 0
    cutoff = groups[int(len(groups) * 0.8)]["created_at"]
    early = [g for g in groups if g["created_at"] < cutoff]
    train = [g for g in early if g["label_at"] < cutoff]
    test = [g for g in groups if g["created_at"] >= cutoff]
    return train, test, cutoff, len(early) - len(train)


def ranking_metrics(ranks):
    return {"ndcg_at_3": sum(1 / math.log2(r + 1) if r <= 3 else 0 for r in ranks) / len(ranks),
            "mrr": sum(1 / r for r in ranks) / len(ranks),
            "top1_agreement": sum(r == 1 for r in ranks) / len(ranks)}


def train_compare(database, as_of=None, synthetic=False):
    as_of = as_of or datetime.now(timezone.utc)
    groups, counts = load_groups(database, as_of)
    train, test, cutoff, purged = time_split(groups)
    report = {"version": VERSION, "data_kind": "synthetic_demo" if synthetic else "recorded_events",
              "as_of": as_of.isoformat(), "counts": counts, "production_ranking": "rules-v2",
              "scope": "displayed_hard_pass_candidates_only", "status": "insufficient_data",
              "split": {"method": "request_time_80_20_with_label_cutoff", "train_requests": len(train),
                        "test_requests": len(test), "purged_delayed_labels": purged,
                        "cutoff": cutoff.isoformat() if cutoff else None},
              "limitations": ["선택이 있는 요청의 노출 후보 2~3곳만 비교; 미노출 후보는 학습/평가하지 않음",
                              "노출/위치 편향이 있는 오프라인 평가; 실제 선택률 개선이나 인과 효과가 아님",
                              "선택 확률 점수는 보정되지 않음; 운영 정렬로 자동 적용하지 않음",
                              "최소 10건은 실행 조건일 뿐 성능 검증에 충분한 표본 수가 아님"]}
    if len(train) < 6 or len(test) < 2:
        report["reason"] = "노출·단일 선택·안전 스냅샷이 있는 요청 10건 이상과 시간 분할 후 학습 6건/평가 2건 이상 필요"
        return report, None
    # Offline-only dependency: the app's startup and recommendation path do not import sklearn.
    import sklearn
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.feature_extraction import DictVectorizer
    from sklearn.pipeline import make_pipeline

    model = make_pipeline(DictVectorizer(sparse=False), RandomForestClassifier(
        n_estimators=100, max_depth=6, min_samples_leaf=2, random_state=42, n_jobs=1))
    rows = [row for group in train for row in group["rows"]]
    model.fit([r["features"] for r in rows], [r["label"] for r in rows],
              randomforestclassifier__sample_weight=[1 / len(g["rows"]) for g in train for _ in g["rows"]])
    rules_ranks, rf_ranks, comparisons = [], [], []
    for group in test:
        rows = group["rows"]
        probabilities = model.predict_proba([r["features"] for r in rows])[:, list(model.classes_).index(1)]
        # Python's stable sort preserves the existing rule rank when RF scores tie.
        order = sorted(range(len(rows)), key=lambda i: -probabilities[i])
        chosen = next(i for i, row in enumerate(rows) if row["label"] == 1)
        rules_ranks.append(rows[chosen]["rule_rank"])
        rf_ranks.append(order.index(chosen) + 1)
        comparisons.append({"request_id": group["request_id"], "candidates": [
            {"place_id": row["place_id"], "rule_rank": row["rule_rank"], "rf_rank": order.index(i) + 1,
             "selection_score": float(probabilities[i]), "selected": bool(row["label"])}
            for i, row in enumerate(rows)]})
    rules, rf = ranking_metrics(rules_ranks), ranking_metrics(rf_ranks)
    report.update(status="evaluated", sklearn_version=sklearn.__version__,
                  model_parameters=model[-1].get_params(),
                  feature_names=model[0].get_feature_names_out().tolist(),
                  rules=rules, random_forest=rf, delta={k: rf[k] - rules[k] for k in rules},
                  comparisons=comparisons,
                  conclusion="합성 실습 결과이며 실제 성능이 아님" if synthetic else "오프라인 비교 완료; 운영은 규칙 정렬 유지")
    return report, model


def create_demo(database):
    """Isolated, deterministic fixture through the real hard filters. Never use the app DB."""
    from datetime import date
    from random import Random
    from unittest.mock import patch
    from uuid import uuid4
    import db
    import recommendation as rec

    db.init_db(database)
    evidence = {"title": "SYNTHETIC ONLY", "url": "https://example.com/synthetic-only",
                "observed_on": date.today().isoformat(), "excerpt": "합성 테스트 메뉴"}
    c = rec.MealConstraints(location_text=None, walking_minutes_max=None, max_distance_m=2000,
                           budget_krw=15000, excluded_ingredients=[], allergens=[], excluded_foods=[],
                           dish_tags=[], atmosphere_tags=[], hard_fields=[], dietary_requirements=[],
                           open_now=False, unknown_terms=[], source_spans=[])
    rng = Random(42)
    for n in range(40):
        prices = rng.sample([7000, 9000, 11000], 3)
        menus = [rec.MenuRecord(place_id=str(i + 1), restaurant_name="합성 식당", menu_name="합성 메뉴",
                                price_krw=price, menu_evidence=evidence) for i, price in enumerate(prices)]
        # Fourth candidate must be rejected by the real budget filter.
        menus.append(rec.MenuRecord(place_id="4", restaurant_name="합성 제외 식당", menu_name="합성 초과 메뉴",
                                    price_krw=30000, menu_evidence=evidence))
        db.upsert_menus(database, menus)
        places = [dict(id=str(i + 1), place_name="합성 식당", distance=(i + 1) * 100,
                       category_name="음식점 > 한식") for i in range(4)]
        with patch.object(rec, "search_candidates", return_value=places):
            result = rec.recommend(c, {"lat": 37.5, "lon": 127.0}, database)
        assert all(p["id"] != "4" for p in result["recommendations"])
        # Synthetic choice rule intentionally prefers price; it is NOT real behavior.
        chosen = min(result["recommendations"], key=lambda p: p["menu"]["price_krw"])["id"]
        started = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(seconds=n * 3)
        with patch.object(db, "utcnow", return_value=started.isoformat()):
            db.save_request(database, "synthetic-only", result)
        for seconds, kind, pid in [(1, "recommendations_viewed", None), (2, "restaurant_selected", chosen)]:
            with patch.object(db, "utcnow", return_value=(started + timedelta(seconds=seconds)).isoformat()):
                db.record_event(database, "synthetic-only", rec.EventInput(
                    id=uuid4(), request_id=result["request_id"], event_type=kind, place_id=pid))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--database", type=Path, default=ROOT / "instance/where_food.db")
    source.add_argument("--demo", action="store_true", help="Synthetic temp DB; never changes your app DB")
    parser.add_argument("--output-root", type=Path, default=ROOT / "instance/selection-rf")
    args = parser.parse_args()
    try:
        if args.demo:
            with TemporaryDirectory(prefix="where-food-rf-demo-") as temp:
                database = Path(temp) / "demo.db"
                create_demo(database)
                report, model = train_compare(database, synthetic=True,
                                              as_of=datetime.now(timezone.utc) + timedelta(days=1))
        else:
            report, model = train_compare(args.database)
        args.output_root.mkdir(parents=True, exist_ok=True)
        output = Path(mkdtemp(prefix="demo-" if args.demo else "recorded-", dir=args.output_root))
        if model is not None:
            import joblib
            joblib.dump({"version": VERSION, "model": model, "report": report}, output / "model.joblib")
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        print(json.dumps({"status": report["status"], "data_kind": report["data_kind"],
                          "counts": report["counts"], "report": str(output / "report.json"),
                          "model_saved": model is not None}, ensure_ascii=False, indent=2))
        return 0 if model is not None else 2
    except (OSError, sqlite3.Error, ImportError, ValueError) as error:
        parser.exit(1, f"학습 실패 ({type(error).__name__}). DB 경로/형식과 requirements-model.txt 설치를 확인하세요.\n")


if __name__ == "__main__":
    sys.exit(main())

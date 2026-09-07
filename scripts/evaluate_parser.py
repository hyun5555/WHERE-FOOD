"""Evaluate the real local parser only; no restaurant APIs or app database writes."""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
from statistics import median
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
from recommendation import PARSER_INSTRUCTIONS, MealConstraints, RecommendationError, parse_constraints, parser_health


EMPTY = dict(location_text=None, walking_minutes_max=None, max_distance_m=None,
             budget_krw=None, excluded_ingredients=[], allergens=[], excluded_foods=[],
             dish_tags=[], atmosphere_tags=[], hard_fields=[], dietary_requirements=[], open_now=False, unknown_terms=[])
# Hand-labelled synthetic requests. Grow this starter set before claiming production quality.
CASES = [
    ("budget", "강남역에서 1만 5천 원 이하 식당", {"location_text": "강남역", "budget_krw": 15000}),
    ("full", "강남역에서 도보 10분, 1만 5천 원 이하, 얼큰한 국물인데 땅콩은 빼고 조용한 곳",
     {"location_text": "강남역", "walking_minutes_max": 10, "budget_krw": 15000,
      "dish_tags": ["얼큰한", "국물"], "excluded_ingredients": ["땅콩"], "atmosphere_tags": ["조용한"]}),
    ("allergy", "땅콩 알레르기가 있어. 12000원 이하로 추천해줘", {"allergens": ["땅콩"], "budget_krw": 12000}),
    ("exclusion", "우유는 빼고 추천해줘", {"excluded_ingredients": ["우유"]}),
    ("distance", "강남역에서 1.2km 이내, 1.5만원 이하", {"location_text": "강남역", "max_distance_m": 1200, "budget_krw": 15000}),
    ("hard_atmosphere", "반드시 조용한 곳", {"atmosphere_tags": ["조용한"], "hard_fields": ["atmosphere_tags"]}),
    ("no_invention", "식당 추천해줘", {}),
    ("no_allergy", "땅콩 알레르기는 없어. 9000원 이하", {"budget_krw": 9000}),
    ("vegan", "비건 메뉴 추천해줘", {"dietary_requirements": ["vegan"]}),
    ("vegetarian", "락토오보 채식 메뉴로 추천해줘", {"dietary_requirements": ["vegetarian"]}),
    ("pescatarian", "페스코 식단으로 추천해줘", {"dietary_requirements": ["pescatarian"]}),
    ("open_now", "지금 영업 중인 식당", {"open_now": True}),
    ("vegan_open", "강남역에서 지금 영업 중인 비건 식당, 15000원 이하",
     {"location_text": "강남역", "open_now": True, "dietary_requirements": ["vegan"], "budget_krw": 15000}),
    ("two_allergies", "땅콩과 우유 알레르기가 있어", {"allergens": ["땅콩", "우유"]}),
    ("two_exclusions", "땅콩과 우유는 빼고", {"excluded_ingredients": ["땅콩", "우유"]}),
    ("negative_taste", "매운 건 싫지만 따뜻한 국물은 좋아", {"excluded_foods": ["매운"], "dish_tags": ["따뜻한", "국물"]}),
    ("hard_dish", "반드시 얼큰한 국물", {"dish_tags": ["얼큰한", "국물"], "hard_fields": ["dish_tags"]}),
    ("no_open_constraint", "영업 여부는 상관없어. 10000원 이하", {"budget_krw": 10000}),
    ("conflicting_budget", "예산은 10000원 이하와 20000원 이상을 동시에 만족해야 해", {"unknown_terms": True}),
    ("unsupported_booking", "내일 오후 7시에 예약 가능한 곳", {"unknown_terms": True}),
    # Frozen holdout: do not tune prompts on these and continue calling them unseen.
    ("holdout_location", "홍대입구역에서 12000원 이하", {"location_text": "홍대입구역", "budget_krw": 12000}),
    ("holdout_budget_comma", "15,000원 이하로 추천해줘", {"budget_krw": 15000}),
    ("holdout_budget_decimal", "1.2만원 이하 식당", {"budget_krw": 12000}),
    ("holdout_walk", "도보 5분 이내", {"walking_minutes_max": 5}),
    ("holdout_metres", "800m 이내 식당", {"max_distance_m": 800}),
    ("holdout_both_distance", "도보 10분 이내이고 직선거리 500m 이내", {"walking_minutes_max": 10, "max_distance_m": 500}),
    ("holdout_allergy_exclude", "해산물 알레르기가 있고 회는 제외", {"allergens": ["해산물"], "excluded_foods": ["회"]}),
    ("holdout_negation", "우유 알레르기는 없지만 땅콩 알레르기는 있어", {"allergens": ["땅콩"]}),
    ("holdout_empty", "아무거나 추천해줘", {}),
    ("holdout_soft_atmosphere", "가능하면 조용한 곳", {"atmosphere_tags": ["조용한"]}),
    ("holdout_mandatory", "꼭 조용한 곳, 18000원 이하", {"atmosphere_tags": ["조용한"], "hard_fields": ["atmosphere_tags"], "budget_krw": 18000}),
    ("holdout_vegan_alias", "완전채식 메뉴로 추천해줘", {"dietary_requirements": ["vegan"]}),
    ("holdout_vegetarian", "채식 메뉴를 먹고 싶어", {"dietary_requirements": ["vegetarian"]}),
    ("holdout_open_alias", "지금 문 연 곳 중 10000원 이하", {"open_now": True, "budget_krw": 10000}),
    ("holdout_future_open", "내일 오전 9시에 문 여는 곳", {"unknown_terms": True}),
    ("holdout_halal", "할랄 인증 식당", {"unknown_terms": True}),
    ("holdout_under", "1만원 미만으로 추천해줘", {"unknown_terms": True}),
    ("holdout_total_budget", "세 명이 합쳐 30000원 이하", {"unknown_terms": True}),
    ("holdout_flexible_budget", "1만원 아래면 좋지만 1만 2천 원까지는 괜찮아", {"unknown_terms": True}),
    ("holdout_rating", "가까운 곳, 단 평점보다 조용한 분위기가 중요", {"atmosphere_tags": ["조용한"], "unknown_terms": True}),
]


def evaluate(cases, *, return_results=False):
    results, timings = [], []
    for name, query, changes in cases:
        started = perf_counter()
        try:
            actual = parse_constraints(query).model_dump(mode="json")
            expected = {**EMPTY, **changes}
            differences = {}
            for field, value in expected.items():
                found = actual[field]
                if field == "unknown_terms" and value is True:
                    equal = bool(found)
                else:
                    equal = sorted(found) == sorted(value) if isinstance(value, list) else found == value
                if not equal:
                    differences[field] = {"expected": value, "actual": found}
            result = {"case": name, "passed": not differences, "differences": differences}
        except RecommendationError as error:
            result = {"case": name, "passed": False, "code": error.code, "error": str(error)}
            if error.code == "parse_failed" and error.__cause__:
                # Synthetic evaluation inputs only; never expose internals through the HTTP API.
                result["validation_error"] = str(error.__cause__)
        elapsed = round(perf_counter() - started, 3)
        timings.append(elapsed)
        result["seconds"] = elapsed
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    summary = {"cases": len(results), "passed": sum(r["passed"] for r in results),
               "p50_seconds": median(timings), "p95_seconds": sorted(timings)[math.ceil(.95 * len(timings)) - 1]}
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return {"summary": summary, "results": results} if return_results else summary


if __name__ == "__main__":
    load_dotenv(ROOT / ".env")
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--query", help="Parse one sentence and print validated JSON instead of evaluating.")
    cli.add_argument("--limit", type=int, choices=range(1, len(CASES) + 1), default=len(CASES))
    cli.add_argument("--split", choices=("all", "dev", "holdout"), default="all")
    cli.add_argument("--output", type=Path, help="Write a reproducible JSON report (synthetic cases only).")
    args = cli.parse_args()
    health = parser_health()
    print(json.dumps({"parser": health}, ensure_ascii=False), flush=True)
    if not health["ready"]:
        sys.exit(1)
    if args.query is not None:
        if not 1 <= len(args.query.strip()) <= 500:
            cli.error("문장은 1~500자여야 합니다.")
        try:
            print(parse_constraints(args.query).model_dump_json(indent=2))
        except RecommendationError as error:
            cli.exit(1, f"{error.code}: {error}\n")
    else:
        cases = [case for case in CASES if args.split == "all" or case[0].startswith("holdout_") == (args.split == "holdout")]
        report = evaluate(cases[:args.limit], return_results=True)
        report["parser"] = health
        report["split"] = args.split
        report["evaluated_at"] = datetime.now(timezone.utc).isoformat()
        report["prompt_schema_sha256"] = sha256((PARSER_INSTRUCTIONS + json.dumps(MealConstraints.model_json_schema(), ensure_ascii=False)).encode()).hexdigest()
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        summary = report["summary"]
        sys.exit(0 if summary["passed"] == summary["cases"] else 1)

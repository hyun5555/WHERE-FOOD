"""Evaluate the real local parser only; no restaurant APIs or app database writes."""
import argparse
import json
import math
from pathlib import Path
from statistics import median
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
from recommendation import RecommendationError, parse_constraints, parser_health


EMPTY = dict(location_text=None, walking_minutes_max=None, max_distance_m=None,
             budget_krw=None, excluded_ingredients=[], allergens=[], excluded_foods=[],
             dish_tags=[], atmosphere_tags=[], hard_fields=[], unknown_terms=[])
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
]


def evaluate(cases):
    results, timings = [], []
    for name, query, changes in cases:
        started = perf_counter()
        try:
            actual = parse_constraints(query).model_dump(mode="json")
            expected = {**EMPTY, **changes}
            differences = {}
            for field, value in expected.items():
                found = actual[field]
                equal = sorted(found) == sorted(value) if isinstance(value, list) else found == value
                if not equal:
                    differences[field] = {"expected": value, "actual": found}
            result = {"case": name, "passed": not differences, "differences": differences}
        except RecommendationError as error:
            result = {"case": name, "passed": False, "code": error.code, "error": str(error)}
        elapsed = round(perf_counter() - started, 3)
        timings.append(elapsed)
        result["seconds"] = elapsed
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    summary = {"cases": len(results), "passed": sum(r["passed"] for r in results),
               "p50_seconds": median(timings), "p95_seconds": sorted(timings)[math.ceil(.95 * len(timings)) - 1]}
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return summary


if __name__ == "__main__":
    load_dotenv(ROOT / ".env")
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--query", help="Parse one sentence and print validated JSON instead of evaluating.")
    cli.add_argument("--limit", type=int, choices=range(1, len(CASES) + 1), default=len(CASES))
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
        summary = evaluate(CASES[:args.limit])
        sys.exit(0 if summary["passed"] == summary["cases"] else 1)

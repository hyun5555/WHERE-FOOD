"""Run the real app with existing menu evidence in a disposable DB (no fake API data)."""
import argparse
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory, mkdtemp
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from flask import g, request
from app import app
from scripts.import_menu_data import import_csv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--map-check", action="store_true", help="Require a JavaScript key and show the real map before model/search calls.")
    args = parser.parse_args()
    if args.map_check and not os.environ.get("KAKAO_JAVASCRIPT_KEY", "").strip():
        parser.error("지도 확인에는 .env의 KAKAO_JAVASCRIPT_KEY 설정이 필요합니다. 키와 SDK 도메인을 설정한 뒤 다시 실행하세요.")
    app.config["MAP_CHECK_MODE"] = args.map_check
    output_root = ROOT / "instance" / "demo"
    output_root.mkdir(parents=True, exist_ok=True)
    output = Path(mkdtemp(prefix="session-", dir=output_root))
    observations = []

    @app.before_request
    def start_timer():
        g.demo_started = monotonic()

    @app.after_request
    def record_observation(response):
        if request.path in ("/api/constraints", "/api/recommend", "/api/events"):
            data = response.get_json(silent=True) or {}
            started = getattr(g, "demo_started", None)
            record = {"endpoint": request.path, "http_status": response.status_code,
                      "elapsed_ms": round((monotonic() - started) * 1000) if started is not None else None}
            for key in ("status", "code", "workflow", "rag", "diagnostics", "confirmation"):
                if key in data:
                    record[key] = data[key]
            record["budget_krw"] = data.get("constraints", {}).get("budget_krw")
            if request.path == "/api/recommend":
                record["recommendations"] = [{"name": p["place_name"], "rank": p["rank"],
                    "menu": p["menu"], "score_breakdown": p["score_breakdown"],
                    "explanation_method": p.get("explanation", {}).get("method")}
                    for p in data.get("recommendations", [])]
            # Never export draft tokens, cookies, coordinates, raw queries or session IDs.
            observations.append(record)
            (output / "observations.json").write_text(json.dumps(observations, ensure_ascii=False, indent=2), encoding="utf-8")
        return response

    with TemporaryDirectory(prefix="where-food-demo-") as temp:
        app.config["DATABASE_PATH"] = str(Path(temp) / "demo.db")
        imported = import_csv(ROOT / "data/menu_items.csv", app.config["DATABASE_PATH"])
        print(f"DEMO: {imported} existing menus, temporary DB; observations: {output}", flush=True)
        if args.map_check:
            print(f"MAP CHECK: http://127.0.0.1:{args.port}/ — key configured; domain authorization and visible map still require browser verification.", flush=True)
        app.run(host="127.0.0.1", port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()

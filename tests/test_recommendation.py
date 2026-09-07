"""Run: .venv/bin/python -m unittest discover -s tests -v

Synthetic evidence is confined to these tests and is never imported to the app DB.
"""
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase, main
from unittest.mock import MagicMock, patch
from uuid import uuid4
import json
import os

from app import app, convert_grid
import db
import recommendation as rec
from scripts.import_menu_data import import_csv


def constraints(**changes):
    values = dict(location_text=None, walking_minutes_max=10, max_distance_m=None,
                  budget_krw=15000, excluded_ingredients=["땅콩"], allergens=[],
                  excluded_foods=[], dish_tags=["얼큰한", "국물"], atmosphere_tags=["조용한"],
                  hard_fields=[], unknown_terms=[], source_spans=[])
    values.update(changes)
    return rec.MealConstraints(**values)


def evidence(text="테스트용 메뉴 근거"):
    return dict(title="TEST ONLY", url="https://example.com/test-only",
                observed_on=date.today().isoformat(), excerpt=text)


def menu(place_id="1", **changes):
    values = dict(place_id=place_id, restaurant_name="테스트 식당 " + place_id,
                  menu_name="테스트 국밥", price_krw=15000, menu_evidence=evidence(),
                  tags=[dict(term=t, evidence=evidence(t)) for t in ["얼큰한", "국물"]],
                  absent_ingredients=[dict(term="땅콩", evidence=evidence("테스트: 땅콩 미사용"))])
    values.update(changes)
    return rec.MenuRecord(**values)


def place(place_id="1"):
    return dict(id=place_id, place_name="테스트 식당 " + place_id, distance="500",
                x="127.03", y="37.50", place_url="https://place.map.kakao.com/" + place_id,
                address_name="테스트 주소", road_address_name="테스트 도로")


class MealFlowTest(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.path = str(Path(self.temp.name) / "test.db")
        self.old_config = {k: app.config[k] for k in ("TESTING", "DATABASE_PATH", "SECRET_KEY")}
        app.config.update(TESTING=True, DATABASE_PATH=self.path, SECRET_KEY="test-only")
        self.client = app.test_client()
        db.init_db(self.path)

    def tearDown(self):
        app.config.update(self.old_config)
        self.temp.cleanup()

    def call_recommend(self, records=None, c=None, routes=None):
        records = records if records is not None else [menu(str(i)) for i in range(1, 5)]
        db.upsert_menus(self.path, records)
        places = list({m.place_id: place(m.place_id) for m in records}.values())
        routes = routes or (lambda origin, p: dict(seconds=600, distance_m=700,
                                                  source_url=p["place_url"], observed_at=db.utcnow()))
        with patch.object(rec, "parse_constraints", return_value=c or constraints()), \
             patch.object(rec, "search_candidates", return_value=places), \
             patch.object(rec, "walking_route", side_effect=routes):
            return self.client.post("/api/recommend", json={"query": "테스트 요청", "lat": 37.5, "lon": 127.0})

    def test_full_flow_top_three_and_feedback(self):
        response = self.call_recommend()
        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertEqual(result["status"], "ok")
        self.assertEqual([p["rank"] for p in result["recommendations"]], [1, 2, 3])
        self.assertEqual(len({p["id"] for p in result["recommendations"]}), 3)
        self.assertIn("'조용한' 여부 미확인", result["recommendations"][0]["unknown"])
        for p in result["recommendations"]:
            self.assertLessEqual(p["menu"]["price_krw"], 15000)
            self.assertLessEqual(p["route"]["seconds"], 600)
            self.assertTrue(all(m["source"]["url"] for m in p["matches"]))
        for event_type, place_id in [("recommendations_viewed", None), ("restaurant_selected", "1")]:
            event = dict(id=str(uuid4()), request_id=result["request_id"], event_type=event_type, place_id=place_id)
            self.assertEqual(self.client.post("/api/events", json=event).status_code, 204)
            self.assertEqual(self.client.post("/api/events", json=event).status_code, 204)
        with db.connect(self.path) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM events").fetchone()[0], 2)
            self.assertEqual(con.execute("SELECT rank FROM events WHERE place_id='1'").fetchone()[0], 1)
            snapshot = json.loads(con.execute("SELECT snapshot_json FROM recommendation_requests").fetchone()[0])
        self.assertNotIn("origin", snapshot)
        self.assertNotIn("x", snapshot["recommendations"][0])

    def test_unknown_exclusion_never_passes(self):
        failures, _, _ = rec.checks_for_menu(menu(absent_ingredients=[]), constraints())
        self.assertIn("땅콩 미사용 근거 없음", failures)

    def test_budget_boundary_and_unknown_price(self):
        self.assertFalse(rec.checks_for_menu(menu(), constraints())[0])
        self.assertIn("예산 초과", rec.checks_for_menu(menu(price_krw=15001), constraints())[0])
        self.assertIn("가격 미확인", rec.checks_for_menu(menu(price_krw=None), constraints())[0])

    def test_numeric_source_units(self):
        self.assertEqual(rec.numeric_value("1만 5천 원 이하", "budget_krw"), 15000)
        self.assertEqual(rec.numeric_value("15,000원", "budget_krw"), 15000)
        self.assertEqual(rec.numeric_value("1.5만원", "budget_krw"), 15000)
        self.assertEqual(rec.numeric_value("1.2km 이내", "max_distance_m"), 1200)
        self.assertEqual(rec.numeric_value("도보 10분", "walking_minutes_max"), 10)
        with self.assertRaises(ValueError):
            rec.numeric_value("1만원 미만", "budget_krw")

    def test_stale_and_future_evidence(self):
        for days in (91, -1):
            source = evidence()
            source["observed_on"] = (date.today() - timedelta(days=days)).isoformat()
            self.assertTrue(rec.checks_for_menu(menu(menu_evidence=source), constraints())[0])

    def test_absence_does_not_prove_allergy_safety(self):
        self.assertTrue(rec.checks_for_menu(menu(), constraints(allergens=["땅콩"]))[0])
        record = menu(allergy_checks=[dict(term="땅콩", cross_contact_checked=False, evidence=evidence())])
        self.assertTrue(rec.checks_for_menu(record, constraints(allergens=["땅콩"]))[0])

    def test_hard_atmosphere_rejects_unknown(self):
        self.assertIn("필수 특성 '조용한' 미확인", rec.checks_for_menu(menu(), constraints(hard_fields=["atmosphere_tags"]))[0])

    def test_partial_does_not_pad_or_duplicate_restaurant(self):
        records = [menu("1"), menu("1", menu_name="두 번째 메뉴", price_krw=11000),
                   menu("2"), menu("3", price_krw=15001), menu("4", absent_ingredients=[])]
        result = self.call_recommend(records).get_json()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["recommendations"]), 2)
        self.assertEqual(len({p["id"] for p in result["recommendations"]}), 2)

    def test_route_failure_and_time_boundary(self):
        def route(origin, p):
            if p["id"] == "1":
                return None
            return dict(seconds=601, distance_m=500, source_url=p["place_url"])
        result = self.call_recommend(routes=route).get_json()
        self.assertEqual(result["recommendations"], [])
        self.assertIn("도보 경로 미확인", result["diagnostics"]["rejected"])

    def test_empty_database(self):
        result = self.call_recommend(records=[]).get_json()
        self.assertEqual(result["recommendations"], [])
        self.assertIn("메뉴 데이터가 아직 없습니다", result["message"])

    def test_foreign_session_and_unshown_place_rejected(self):
        result = self.call_recommend().get_json()
        event = dict(id=str(uuid4()), request_id=result["request_id"], event_type="restaurant_selected", place_id="1")
        self.assertEqual(app.test_client().post("/api/events", json=event).status_code, 400)
        event["place_id"] = "9999"
        self.assertEqual(self.client.post("/api/events", json=event).status_code, 400)
        event["rank"] = 1
        self.assertEqual(self.client.post("/api/events", json=event).status_code, 400)

    def test_invalid_inputs_and_cross_origin(self):
        for value in [None, [], {}, {"query": " "}, {"query": "x" * 501},
                      {"query": "x", "lat": True, "lon": 127.0},
                      {"query": "x", "lat": 91.0, "lon": 127.0},
                      {"query": "x", "lat": 37.5}]:
            with self.subTest(value=value):
                self.assertEqual(self.client.post("/api/recommend", json=value).status_code, 400)
        self.assertEqual(self.client.post("/api/recommend", json={"query": "x"}, headers={"Origin": "https://evil.example"}).status_code, 403)

    def test_missing_parser_key_is_explicit(self):
        for enabled, key in [("", ""), ("1", ""), ("0", "project-test-key")]:
            with self.subTest(enabled=enabled, key_present=bool(key)), patch.dict(os.environ, {
                "OPENAI_API_KEY": "shared-key-must-never-be-used",
                "WHERE_FOOD_ENABLE_OPENAI": enabled, "WHERE_FOOD_OPENAI_API_KEY": key,
            }), patch("openai.OpenAI") as client:
                response = self.client.post("/api/recommend", json={"query": "강남역에서 국밥"})
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.get_json()["code"], "parser_not_configured")
                self.assertFalse(self.client.get("/api/health").get_json()["parser_configured"])
                client.assert_not_called()

    def test_unsupported_terms_request_clarification(self):
        result = self.call_recommend(c=constraints(unknown_terms=["비건 전용 주방"])).get_json()
        self.assertEqual(result["status"], "clarification_required")
        self.assertEqual(result["recommendations"], [])

    def test_location_choice_is_revalidated(self):
        c = constraints(location_text="강남역")
        payload = rec.RecommendInput(query="강남역", origin_place_id="999")
        with patch.object(rec, "kakao_get", return_value={"documents": [place("1"), place("2")]}):
            origin, options = rec.resolve_origin(c, payload)
        self.assertIsNone(origin)
        self.assertEqual(options, [])

    def test_real_seed_import_is_idempotent_and_missing_ingredients_stay_unknown(self):
        count = import_csv(Path(__file__).resolve().parents[1] / "data/menu_items.csv", self.path)
        self.assertGreater(count, 0)
        self.assertEqual(import_csv(Path(__file__).resolve().parents[1] / "data/menu_items.csv", self.path), count)
        self.assertEqual(db.menu_count(self.path), count)
        for raw in db.get_menus(self.path, ["273280172", "16060565", "1879763670"]):
            self.assertEqual(raw["absent_ingredients"], [])
            self.assertEqual(raw["allergy_checks"], [])

    def test_import_failure_does_not_delete_existing_data(self):
        db.upsert_menus(self.path, [menu()])
        path = Path(self.temp.name) / "broken.csv"
        path.write_text("place_id,restaurant_name,menu_name,price_krw,menu_evidence\n1,x,x,nope,{}\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            import_csv(path, self.path)
        self.assertEqual(db.menu_count(self.path), 1)

    def test_parser_rejects_unanchored_evidence_and_refusal(self):
        parsed = constraints(location_text=None, walking_minutes_max=None, budget_krw=None,
                             excluded_ingredients=[], dish_tags=[], atmosphere_tags=[],
                             source_spans=[rec.SourceSpan(field="budget_krw", text="없는 원문")])
        with patch.dict(os.environ, {
            "OPENAI_API_KEY": "shared-key-must-never-be-used",
            "WHERE_FOOD_ENABLE_OPENAI": "1", "WHERE_FOOD_OPENAI_API_KEY": "test-not-a-real-key",
        }), patch("openai.OpenAI") as client:
            create = client.return_value.__enter__.return_value.responses.parse
            create.return_value = SimpleNamespace(status="completed", output_parsed=parsed)
            with self.assertRaises(rec.RecommendationError):
                rec.parse_constraints("안녕")
            client.assert_called_with(api_key="test-not-a-real-key", timeout=25, max_retries=0)
            create.return_value = SimpleNamespace(status="completed", output_parsed=None)
            with self.assertRaises(rec.RecommendationError):
                rec.parse_constraints("안녕")

    def test_weather_failure_does_not_predict_fake_zero_degrees(self):
        with patch.dict(os.environ, {"WEATHER_API_KEY": ""}), patch.object(rec, "kakao_get", return_value={}), patch("app.weather_hints") as predict:
            response = self.client.post("/get-initial-data", json={"lat": 37.5, "lon": 127.0})
        self.assertEqual(response.status_code, 200)
        self.assertIn("error", response.get_json()["weather"])
        self.assertFalse(predict.called)
        self.assertEqual(convert_grid(37.5665, 126.9780), (60, 127))


if __name__ == "__main__":
    main()

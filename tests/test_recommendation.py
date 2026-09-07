"""Run: .venv/bin/python -m unittest discover -s tests -v

Synthetic evidence is confined to these tests and is never imported to the app DB.
"""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import MagicMock, patch
from uuid import uuid4
from contextlib import redirect_stdout
from io import StringIO
import json
import os

from app import app, convert_grid, weather_ranking
import db
import recommendation as rec
from scripts.import_menu_data import import_csv
from scripts.evaluate_parser import evaluate, EMPTY, CASES


def constraints(**changes):
    values = dict(location_text=None, walking_minutes_max=10, max_distance_m=None,
                  budget_krw=15000, excluded_ingredients=["땅콩"], allergens=[],
                  excluded_foods=[], dish_tags=["얼큰한", "국물"], atmosphere_tags=["조용한"],
                  hard_fields=[], dietary_requirements=[], open_now=False, unknown_terms=[], source_spans=[])
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
        # Tests must never contact a real model, even when API keys or Ollama exist.
        session_patch = patch.object(rec.requests, "Session")
        self.ollama = session_patch.start().return_value.__enter__.return_value
        self.addCleanup(session_patch.stop)
        env_patch = patch.dict(os.environ, {"WHERE_FOOD_OLLAMA_TIMEOUT_SECONDS": "120"})
        env_patch.start()
        self.addCleanup(env_patch.stop)
        weather_patch = patch("app.weather_ranking", return_value={"scores": {}, "available": False})
        self.weather_ranking = weather_patch.start()
        self.addCleanup(weather_patch.stop)

    def mock_ollama(self, content=None, **changes):
        data = dict(done=True, done_reason="stop", message={"content": content or "{}"})
        data.update(changes)
        self.ollama.request.return_value = MagicMock(status_code=200)
        self.ollama.request.return_value.json.return_value = data
        return data

    def tearDown(self):
        app.config.update(self.old_config)
        self.temp.cleanup()

    def draft(self, c=None):
        with patch.object(rec, "parse_constraints", return_value=c or constraints()):
            response = self.client.post("/api/constraints", json={"query": "테스트 요청"})
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def confirmed_payload(self, draft, **changes):
        return {"draft_token": draft["draft_token"], "confirmed": True,
                "constraints": draft["constraints"], "lat": 37.5, "lon": 127.0, **changes}

    def call_recommend(self, records=None, c=None, routes=None):
        records = records if records is not None else [menu(str(i)) for i in range(1, 5)]
        db.upsert_menus(self.path, records)
        places = list({m.place_id: place(m.place_id) for m in records}.values())
        routes = routes or (lambda origin, p: dict(seconds=600, distance_m=700,
                                                  source_url=p["place_url"], observed_at=db.utcnow()))
        draft = self.draft(c)
        with patch.object(rec, "parse_constraints", side_effect=AssertionError("search must not parse")), \
             patch.object(rec, "search_candidates", return_value=places), \
             patch.object(rec, "walking_route", side_effect=routes):
            return self.client.post("/api/recommend", json=self.confirmed_payload(draft))

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

    def test_local_json_reaches_existing_filter_and_feedback(self):
        parsed = constraints(walking_minutes_max=None, dish_tags=[], atmosphere_tags=[], source_spans=[
            rec.SourceSpan(field="budget_krw", text="15000원 이하"),
            rec.SourceSpan(field="excluded_ingredients", text="땅콩 빼고")])
        self.mock_ollama(parsed.model_dump_json())
        db.upsert_menus(self.path, [menu("1")])
        draft = self.client.post("/api/constraints", json={"query": "15000원 이하, 땅콩 빼고"}).get_json()
        with patch.object(rec, "search_candidates", return_value=[place("1")]):
            response = self.client.post("/api/recommend", json=self.confirmed_payload(draft))
        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertEqual(result["parser"]["model"], "qwen3.5:9b")
        self.assertEqual(result["recommendations"][0]["id"], "1")
        event = dict(id=str(uuid4()), request_id=result["request_id"], event_type="restaurant_selected", place_id="1")
        self.assertEqual(self.client.post("/api/events", json=event).status_code, 204)

    def test_unknown_exclusion_never_passes(self):
        failures, _, _ = rec.checks_for_menu(menu(absent_ingredients=[]), constraints())
        self.assertIn("땅콩 미사용 근거 없음", failures)

    def test_extract_only_does_not_search_or_save_request(self):
        with patch.object(rec, "search_candidates") as search, patch.object(rec, "kakao_get") as places:
            draft = self.draft()
        search.assert_not_called()
        places.assert_not_called()
        self.assertEqual(draft["status"], "review_required")
        self.assertNotIn("source_spans", draft["constraints"])
        with db.connect(self.path) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM recommendation_requests").fetchone()[0], 0)

    def test_confirmed_budget_edit_filters_and_records_provenance(self):
        draft = self.draft(constraints(walking_minutes_max=None))
        payload = self.confirmed_payload(draft)
        payload["constraints"]["budget_krw"] = 10000
        db.upsert_menus(self.path, [menu("1", price_krw=10000), menu("2", price_krw=10001)])
        with patch.object(rec, "parse_constraints", side_effect=AssertionError("unexpected inference")), \
             patch.object(rec, "search_candidates", return_value=[place("1"), place("2")]):
            result = self.client.post("/api/recommend", json=payload).get_json()
        self.assertEqual([p["id"] for p in result["recommendations"]], ["1"])
        self.assertEqual(result["confirmation"]["edited_fields"], ["budget_krw"])
        self.assertEqual(result["constraints"]["source_spans"], [])
        with db.connect(self.path) as con:
            snapshot = con.execute("SELECT snapshot_json FROM recommendation_requests").fetchone()[0]
        self.assertNotIn(draft["draft_token"], snapshot)
        self.assertNotIn('"source_spans"', snapshot)

    def test_confirmation_rejects_invalid_and_forged_fields(self):
        payload = self.confirmed_payload(self.draft())
        invalid = [
            {**payload, "confirmed": False}, {**payload, "confirmed": 1},
            {**payload, "lat": True}, {**payload, "lon": None},
            {**payload, "weather_score": 999}, {**payload, "ignored_unknown_terms": ["偽造"]},
        ]
        for field, value in [("budget_krw", "10000"), ("budget_krw", True), ("budget_krw", 1.5),
                             ("budget_krw", 0), ("walking_minutes_max", 121), ("max_distance_m", 20001),
                             ("location_text", " "), ("allergens", [""]), ("allergens", ["우유"] * 21),
                             ("allergens", ["우유", "우유"]), ("allergens", ["x" * 51]),
                             ("dietary_requirements", ["halal"]), ("source_spans", []),
                             ("unknown_terms", []), ("menu_evidence", {})]:
            invalid.append({**payload, "constraints": {**payload["constraints"], field: value}})
        invalid.append({**payload, "constraints": {**payload["constraints"], "dish_tags": [], "hard_fields": ["dish_tags"]}})
        with patch.object(rec, "search_candidates") as search, patch.object(rec, "parse_constraints") as parse:
            for value in invalid:
                with self.subTest(value=value):
                    self.assertEqual(self.client.post("/api/recommend", json=value).status_code, 400)
        search.assert_not_called()
        parse.assert_not_called()

    def test_draft_session_signature_and_expiration(self):
        from itsdangerous import SignatureExpired
        payload = self.confirmed_payload(self.draft())
        self.assertEqual(app.test_client().post("/api/recommend", json=payload).get_json()["code"], "invalid_draft")
        forged = {**payload, "draft_token": payload["draft_token"] + "tampered"}
        self.assertEqual(self.client.post("/api/recommend", json=forged).get_json()["code"], "invalid_draft")
        with patch("app.draft_serializer") as serializer:
            serializer.return_value.loads.side_effect = SignatureExpired("expired")
            response = self.client.post("/api/recommend", json=payload)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["code"], "draft_expired")
        serializer.return_value.loads.assert_called_once_with(payload["draft_token"], max_age=1800)

    def test_unknown_terms_require_explicit_exclusion(self):
        draft = self.draft(constraints(unknown_terms=["내일 예약"], walking_minutes_max=None))
        payload = self.confirmed_payload(draft)
        db.upsert_menus(self.path, [menu()])
        with patch.object(rec, "search_candidates", return_value=[place()]) as search:
            result = self.client.post("/api/recommend", json=payload).get_json()
            self.assertEqual(result["workflow"]["steps"], ["RESOLVE", "CLARIFY"])
            search.assert_not_called()
            payload["ignored_unknown_terms"] = ["내일 예약"]
            result = self.client.post("/api/recommend", json=payload).get_json()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["constraints"]["unknown_terms"], [])
        self.assertEqual(result["confirmation"]["ignored_unknown_count"], 1)

    def test_location_choice_reuses_draft_without_inference(self):
        draft = self.draft(constraints(location_text="강남역", walking_minutes_max=None))
        payload = self.confirmed_payload(draft)
        with patch.object(rec, "parse_constraints", side_effect=AssertionError("unexpected inference")), \
             patch.object(rec, "kakao_get", return_value={"documents": [place("1"), place("2")]}), \
             patch.object(rec, "search_candidates", return_value=[]) as search:
            first = self.client.post("/api/recommend", json=payload).get_json()
            self.assertEqual(first["workflow"]["steps"], ["RESOLVE", "CLARIFY"])
            search.assert_not_called()
            payload["origin_place_id"] = "1"
            second = self.client.post("/api/recommend", json=payload).get_json()
            self.assertEqual(second["workflow"]["steps"], ["RESOLVE", "SEARCH_FILTER_RANK", "NO_RESULTS"])
            search.assert_called_once()

    def test_graph_branches_and_remote_tracing_disabled(self):
        # No LangSmith export even when the process environment enables it.
        import langsmith
        from langsmith.run_helpers import get_tracing_context
        original = rec.recommend
        def search(*args, **kwargs):
            self.assertIs(get_tracing_context()["enabled"], False)
            return original(*args, **kwargs)
        with patch.dict(os.environ, {"LANGSMITH_TRACING": "true", "LANGCHAIN_TRACING_V2": "true"}), \
             patch.object(langsmith.Client, "create_run") as export, patch.object(rec, "recommend", side_effect=search):
            result = self.call_recommend().get_json()
        self.assertEqual(result["workflow"], {"engine": "langgraph", "version": "meal-v1",
                                               "steps": ["RESOLVE", "SEARCH_FILTER_RANK", "RESPOND"]})
        self.assertEqual(result["status"], "ok")
        export.assert_not_called()
        none = self.call_recommend(records=[menu(price_krw=99999)]).get_json()
        self.assertEqual(none["workflow"]["steps"][-1], "NO_RESULTS")

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
        self.assertIn("필수 특성 '조용한' 미확인", rec.check_preferences(menu(), constraints(hard_fields=["atmosphere_tags"]))[0])

    def test_diet_requires_exact_fresh_evidence_not_menu_name(self):
        for diet in ("vegan", "vegetarian", "pescatarian"):
            c = constraints(dietary_requirements=[diet])
            self.assertTrue(rec.checks_for_menu(menu(menu_name="비건 샐러드"), c)[0])
            good = dict(term=diet, evidence=evidence())
            self.assertFalse(rec.checks_for_menu(menu(dietary_checks=[good]), c)[0])
            good["evidence"]["observed_on"] = (date.today() - timedelta(days=91)).isoformat()
            self.assertTrue(rec.checks_for_menu(menu(dietary_checks=[good]), c)[0])
        # Vegan classification is not evidence of allergy/cross-contact safety.
        c = constraints(dietary_requirements=["vegan"], allergens=["우유"])
        self.assertTrue(rec.checks_for_menu(menu(dietary_checks=[dict(term="vegan", evidence=evidence())]), c)[0])

    def test_hard_failure_priority(self):
        c = constraints(allergens=["우유"], dietary_requirements=["vegan"], excluded_foods=["회"])
        failures, _, _ = rec.checks_for_menu(menu(price_krw=20000, absent_ingredients=[]), c)
        self.assertEqual(failures, ["우유 알레르기·교차접촉 확인 근거 없음", "비건 식단 확인 근거 없음",
                                    "땅콩 미사용 근거 없음", "회 제외 근거 없음", "예산 초과"])

    def test_opening_status_requires_current_trusted_record(self):
        now = datetime.now(timezone.utc)
        opening = dict(is_open=True, provider="merchant_confirmed", observed_at=now,
                       valid_until=now + timedelta(minutes=10), evidence=evidence())
        c = constraints(open_now=True)
        result = self.call_recommend(records=[menu("1", opening_status=opening), menu("2")], c=c).get_json()
        self.assertEqual([p["id"] for p in result["recommendations"]], ["1"])
        self.assertIn("현재 영업 여부 미확인", result["diagnostics"]["rejected"])
        self.assertTrue(result["recommendations"][0]["opening_status"]["is_open"])
        with self.assertRaises(rec.ValidationError):
            rec.OpeningStatus(**{**opening, "provider": "unverified_blog"})
        with self.assertRaises(rec.ValidationError):
            rec.OpeningStatus(**{**opening, "valid_until": now + timedelta(hours=1)})
        with self.assertRaises(rec.ValidationError):
            rec.OpeningStatus(**{**opening, "observed_at": now.replace(tzinfo=None)})

    def test_opening_closed_stale_future_and_expiry_boundary(self):
        now = datetime.now(timezone.utc)
        base = dict(is_open=True, provider="official", observed_at=now,
                    valid_until=now + timedelta(minutes=10), evidence=evidence())
        record = rec.OpeningStatus(**base)
        self.assertTrue(record.current(now))
        self.assertFalse(record.current(record.valid_until))
        records = [
            menu("1", opening_status={**base, "is_open": False}),
            menu("2", opening_status={**base, "observed_at": now - timedelta(minutes=20), "valid_until": now - timedelta(minutes=10)}),
            menu("3", opening_status={**base, "observed_at": now + timedelta(minutes=1)}),
        ]
        result = self.call_recommend(records=records, c=constraints(open_now=True)).get_json()
        self.assertEqual(result["recommendations"], [])
        self.assertEqual(result["diagnostics"]["rejected"]["현재 영업하지 않음"], 1)
        self.assertEqual(result["diagnostics"]["rejected"]["현재 영업 여부 미확인"], 2)

    def test_newer_closed_and_conflicting_opening_records_fail_closed(self):
        now = datetime.now(timezone.utc)
        opened = dict(is_open=True, provider="official", observed_at=now - timedelta(minutes=2),
                      valid_until=now + timedelta(minutes=10), evidence=evidence())
        closed = {**opened, "is_open": False, "observed_at": now - timedelta(minutes=1)}
        for second in (closed, {**closed, "observed_at": opened["observed_at"]}):
            result = self.call_recommend(records=[menu("1", opening_status=opened),
                menu("1", menu_name="다른 메뉴", opening_status=second)], c=constraints(open_now=True)).get_json()
            self.assertEqual(result["recommendations"], [])

    def test_import_preserves_diet_and_opening_evidence(self):
        import csv
        now = datetime.now(timezone.utc)
        record = menu(dietary_checks=[dict(term="vegan", evidence=evidence())], opening_status=dict(
            is_open=True, provider="official", observed_at=now,
            valid_until=now + timedelta(minutes=10), evidence=evidence())).model_dump(mode="json")
        csv_path = Path(self.temp.name) / "verified.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=list(record))
            writer.writeheader()
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v for k, v in record.items()})
        import_csv(csv_path, self.path)
        stored = db.get_menus(self.path, ["1"])[0]
        self.assertEqual(stored["dietary_checks"][0]["term"], "vegan")
        self.assertEqual(stored["opening_status"]["observed_at"], record["opening_status"]["observed_at"])

    def test_opening_rechecked_after_slow_weather_lookup(self):
        now = datetime.now(timezone.utc)
        opening = dict(is_open=True, provider="official", observed_at=now,
                       valid_until=now + timedelta(minutes=1), evidence=evidence())
        with patch.object(rec, "datetime", wraps=datetime) as clock:
            clock.now.return_value = now
            def slow_weather(origin):
                clock.now.return_value = now + timedelta(minutes=2)
                return {"scores": {}, "available": False}
            self.weather_ranking.side_effect = slow_weather
            result = self.call_recommend(records=[menu(opening_status=opening)], c=constraints(open_now=True)).get_json()
        self.assertEqual(result["recommendations"], [])
        self.assertIn("현재 영업 여부 미확인", result["diagnostics"]["rejected"])

    def test_rank_policy_lexicographic_and_missing_weather(self):
        def candidate(id, *, soft=0, complete=.5, age=1, distance=500, category="한식", price=10000):
            return {**place(id), "category_name": "음식점 > " + category, "distance": distance, "route": None,
                    "menu": {"name": "test", "price_krw": price},
                    "score_breakdown": {"soft_matches": soft, "evidence_completeness": complete, "evidence_age_days": age}}
        weather = {"scores": {"한식": .1, "중식": .9}}
        pairs = [
            (candidate("1", soft=1, complete=.1, distance=900), candidate("2", complete=1)),
            (candidate("1", complete=.8, age=50), candidate("2", complete=.5, age=0)),
            (candidate("1", age=0, distance=900), candidate("2", age=10, distance=100)),
            (candidate("1", distance=100), candidate("2", distance=200, category="중식")),
            (candidate("1", category="중식"), candidate("2", category="한식")),
        ]
        for first, second in pairs:
            self.assertEqual(rec.rank_candidates([second, first], weather)[0]["id"], "1")
        ranked = rec.rank_candidates([candidate("2", category="중식"), candidate("1", category="미분류")], weather)
        self.assertEqual(ranked[0]["id"], "1")
        self.assertTrue(all(not p["score_breakdown"]["weather_applied"] for p in ranked))
        self.assertIsNone(ranked[0]["score_breakdown"]["weather_score"])
        invalid = rec.rank_candidates([candidate("1")], {"scores": {"한식": float("nan")}})
        self.assertIsNone(invalid[0]["score_breakdown"]["weather_score"])

    def test_quality_counts_groups_not_repeated_claims(self):
        now = datetime.now(timezone.utc)
        original = menu()
        more = menu(tags=original.tags * 4)
        self.assertEqual(rec.evidence_quality(original, [], now), rec.evidence_quality(more, [], now))
        source = evidence()
        source["observed_on"] = (date.today() - timedelta(days=30)).isoformat()
        self.assertEqual(rec.evidence_quality(original, [{"source": source}], now)["evidence_age_days"], 30)

    def test_weather_provider_uses_resolved_origin_not_client_scores(self):
        self.call_recommend(c=constraints(walking_minutes_max=None))
        self.weather_ranking.assert_called_once_with({"lat": 37.5, "lon": 127.0, "name": "선택한 위치"})
        response = self.client.post("/api/recommend", json={"query": "추천", "weather_score": 999})
        self.assertEqual(response.status_code, 400)

    def test_weather_ranking_requires_observation_and_model(self):
        origin = {"lat": 37.5, "lon": 127.0}
        with patch("app.load_weather_model", return_value=None), patch("app.weather_context") as lookup:
            self.assertFalse(weather_ranking(origin)["available"])
            lookup.assert_not_called()
        with patch("app.load_weather_model", return_value=object()), patch("app.weather_context") as lookup:
            lookup.return_value = {"weather": {"error": "확인 불가"}, "recommendations": []}
            self.assertEqual(weather_ranking(origin)["scores"], {})
            lookup.return_value = {"weather": {"observed_at": "test-observation"},
                                   "recommendations": [{"name": "한식", "weather_score": .13}]}
            result = weather_ranking(origin)
            self.assertEqual(result["scores"], {"한식": .13})
            self.assertEqual(result["observed_at"], "test-observation")
            self.assertNotIn("serviceKey", result["source"]["url"])
            lookup.assert_called_with(37.5, 127.0)

    def test_dataset_has_40_distinct_cases_and_separate_holdout(self):
        self.assertEqual(len(CASES), 40)
        self.assertEqual(len({case[1] for case in CASES}), 40)
        self.assertEqual(sum(name.startswith("holdout_") for name, _, _ in CASES), 20)

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
            for endpoint in ("/api/constraints", "/api/recommend"):
                with self.subTest(value=value, endpoint=endpoint):
                    self.assertEqual(self.client.post(endpoint, json=value).status_code, 400)
        for endpoint in ("/api/constraints", "/api/recommend"):
            self.assertEqual(self.client.post(endpoint, json={"query": "x"}, headers={"Origin": "https://evil.example"}).status_code, 403)

    def test_local_parser_ignores_cloud_keys_hosts_and_proxies(self):
        parsed = constraints(location_text="강남역", walking_minutes_max=None, budget_krw=15000,
                             excluded_ingredients=[], dish_tags=[], atmosphere_tags=[], source_spans=[
                                 rec.SourceSpan(field="location_text", text="강남역"),
                                 rec.SourceSpan(field="budget_krw", text="1만 5천 원 이하")])
        self.mock_ollama(parsed.model_dump_json())
        with patch.dict(os.environ, {
            "OPENAI_API_KEY": "shared-key-must-never-be-used",
            "WHERE_FOOD_OPENAI_API_KEY": "old-project-key-must-never-be-used",
            "WHERE_FOOD_ENABLE_OPENAI": "1", "OLLAMA_HOST": "https://remote.example",
            "OLLAMA_MODEL": "qwen3.5:cloud", "HTTPS_PROXY": "https://proxy.example",
        }):
            self.assertEqual(rec.parse_constraints("강남역에서 1만 5천 원 이하"), parsed)
        args, kwargs = self.ollama.request.call_args
        self.assertEqual(args, ("POST", "http://127.0.0.1:11434/api/chat"))
        self.assertIs(self.ollama.trust_env, False)
        self.assertFalse(kwargs["allow_redirects"])
        self.assertNotIn("headers", kwargs)
        self.assertEqual(kwargs["json"]["model"], "qwen3.5:9b")
        self.assertFalse(kwargs["json"]["think"])
        self.assertFalse(kwargs["json"]["stream"])
        self.assertEqual(kwargs["json"]["format"], rec.MealConstraints.model_json_schema())

    def test_ollama_failure_codes_and_no_retries(self):
        for error, status, code in [
            (rec.requests.ConnectionError(), 503, "ollama_unavailable"),
            (rec.requests.Timeout(), 504, "ollama_timeout"),
        ]:
            with self.subTest(code=code):
                self.ollama.request.reset_mock()
                self.ollama.request.side_effect = error
                response = self.client.post("/api/constraints", json={"query": "강남역"})
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.get_json()["code"], code)
                self.ollama.request.assert_called_once()
        self.ollama.request.side_effect = None
        for status in (301, 404, 500):
            with self.subTest(status=status):
                self.ollama.request.return_value.status_code = status
                response = self.client.post("/api/constraints", json={"query": "강남역"})
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.get_json()["code"], "ollama_model_missing" if status == 404 else "ollama_unavailable")

    def test_local_health_checks_model_without_inference(self):
        self.mock_ollama(models=[{"name": "qwen3.5:9b", "digest": "test-digest"}])
        result = self.client.get("/api/health").get_json()
        self.assertTrue(result["parser"]["ready"])
        self.assertEqual(result["parser"]["provider"], "ollama")
        self.assertEqual(self.ollama.request.call_args.args, ("GET", rec.OLLAMA_URL + "/api/tags"))
        self.mock_ollama(models=[{"name": "qwen3.5:2b"}])
        self.assertEqual(self.client.get("/api/health").get_json()["parser"]["code"], "ollama_model_missing")
        self.ollama.request.side_effect = rec.requests.ConnectionError()
        self.assertFalse(self.client.get("/api/health").get_json()["parser"]["ready"])

    def test_busy_and_invalid_timeout_do_not_call_model(self):
        rec.PARSER_LOCK.acquire()
        try:
            response = self.client.post("/api/constraints", json={"query": "강남역"})
            self.assertEqual(response.status_code, 429)
            self.assertEqual(response.get_json()["code"], "parser_busy")
        finally:
            rec.PARSER_LOCK.release()
        for value in ("0", "301", "nan", ""):
            with patch.dict(os.environ, {"WHERE_FOOD_OLLAMA_TIMEOUT_SECONDS": value}):
                response = self.client.post("/api/constraints", json={"query": "강남역"})
                self.assertEqual(response.get_json()["code"], "parser_not_configured")
        self.ollama.request.assert_not_called()

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

    def test_parser_rejects_unanchored_evidence_and_incomplete_json(self):
        parsed = constraints(location_text=None, walking_minutes_max=None, budget_krw=None,
                             excluded_ingredients=[], dish_tags=[], atmosphere_tags=[],
                             source_spans=[rec.SourceSpan(field="budget_krw", text="없는 원문")])
        for content, changes in [(parsed.model_dump_json(), {}), ("not JSON", {}),
                                 ("{}", {}), ("{}", {"done": False}),
                                 ("{}", {"done_reason": "length"}), ("{}", {"message": None})]:
            with self.subTest(changes=changes):
                self.mock_ollama(content, **changes)
                with self.assertRaises(rec.RecommendationError) as error:
                    rec.parse_constraints("안녕")
                self.assertEqual(error.exception.code, "parse_failed")
                self.assertFalse(rec.PARSER_LOCK.locked())

    def test_parser_rejects_wrong_numeric_value_and_duplicate_spans(self):
        parsed = constraints(walking_minutes_max=None, budget_krw=15001,
                             excluded_ingredients=[], dish_tags=[], atmosphere_tags=[], source_spans=[
                                 rec.SourceSpan(field="budget_krw", text="15000원 이하")])
        for case in (parsed, parsed.model_copy(update={"budget_krw": 15000, "source_spans": parsed.source_spans * 2})):
            self.mock_ollama(case.model_dump_json())
            with self.assertRaises(rec.RecommendationError):
                rec.parse_constraints("15000원 이하")

    def test_evaluation_counts_semantic_mismatch_as_failure(self):
        parsed = rec.MealConstraints(**EMPTY, source_spans=[])
        with patch("scripts.evaluate_parser.parse_constraints", return_value=parsed), redirect_stdout(StringIO()):
            summary = evaluate([("empty", "식당 추천", {}), ("omitted", "땅콩 빼고", {"excluded_ingredients": ["땅콩"]})])
        self.assertEqual(summary["cases"], 2)
        self.assertEqual(summary["passed"], 1)

    def test_weather_failure_does_not_predict_fake_zero_degrees(self):
        with patch.dict(os.environ, {"WEATHER_API_KEY": ""}), patch.object(rec, "kakao_get", return_value={}), patch("app.weather_hints") as predict:
            response = self.client.post("/get-initial-data", json={"lat": 37.5, "lon": 127.0})
        self.assertEqual(response.status_code, 200)
        self.assertIn("error", response.get_json()["weather"])
        self.assertFalse(predict.called)
        self.assertEqual(convert_grid(37.5665, 126.9780), (60, 127))

    def test_weather_observation_time_matches_hourly_api_and_hint_limit(self):
        values = {"T1H": "24", "REH": "50", "WSD": "1.5", "RN1": "강수없음", "PTY": "0"}
        response = MagicMock()
        response.json.return_value = {"response": {"body": {"items": {"item": [
            {"category": key, "obsrValue": value} for key, value in values.items()]}}}}
        with patch.dict(os.environ, {"WEATHER_API_KEY": "test-only"}), \
             patch.object(rec, "kakao_get", return_value={}), \
             patch("app.requests.get", return_value=response) as request, \
             patch("app.weather_hints", return_value=[{"name": str(i), "weather_score": .1} for i in range(5)]):
            result = self.client.post("/get-initial-data", json={"lat": 37.5, "lon": 127.0}).get_json()
        observed = datetime.fromisoformat(result["weather"]["observed_at"])
        self.assertEqual((observed.minute, observed.second, observed.microsecond), (0, 0, 0))
        self.assertEqual(request.call_args.kwargs["params"]["base_time"], observed.strftime("%H00"))
        self.assertEqual(len(result["recommendations"]), 3)


if __name__ == "__main__":
    main()

"""Offline choice learning: synthetic fixtures only, no network or app DB writes."""
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import db
from scripts import train_selection_model as training


class SelectionModelTest(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "selection.db"
        # The fixture must not contact places, weather, Ollama or any other API.
        with patch("requests.Session.request", side_effect=AssertionError("no network")), \
             patch("requests.get", side_effect=AssertionError("no network")):
            training.create_demo(self.path)
        self.as_of = datetime.now(timezone.utc) + timedelta(days=1)

    def first_request(self):
        with db.connect(self.path) as con:
            return con.execute("SELECT id, snapshot_json FROM recommendation_requests ORDER BY created_at LIMIT 1").fetchone()

    def replace_snapshot(self, request_id, snapshot):
        with db.connect(self.path) as con:
            con.execute("UPDATE recommendation_requests SET snapshot_json=? WHERE id=?",
                        (json.dumps(snapshot), request_id))

    def test_read_only_extraction_and_safety_boundary(self):
        before = self.path.read_bytes()
        groups, counts = training.load_groups(self.path, self.as_of)
        self.assertEqual(counts["usable_requests"], 40)
        self.assertEqual(counts["candidate_rows"], 120)
        self.assertEqual(before, self.path.read_bytes())
        for group in groups:
            self.assertEqual(sum(row["label"] for row in group["rows"]), 1)
            for row in group["rows"]:
                self.assertNotEqual(row["place_id"], "4")  # Real hard filter rejected it.
                self.assertLessEqual(row["features"]["price_krw"], 15000)
                self.assertTrue({"place_id", "request_id", "rank", "rule_rank", "label", "session_id"}.isdisjoint(row["features"]))
                self.assertEqual(row["features"]["weather_missing"], 1)
        request_id, raw = self.first_request()
        for mutate in (
            lambda s: s["recommendations"][0]["score_breakdown"].update(hard_constraints="fail"),
            lambda s: s["recommendations"][0]["menu"].update(price_krw=15001),
            lambda s: s["recommendations"][0].update(distance=2001),
            lambda s: s["constraints"].update(walking_minutes_max=1),
            lambda s: s["recommendations"][0]["score_breakdown"].update(weather_score=float("nan")),
            lambda s: s["recommendations"][0].update(rank=2),
            lambda s: s.update(recommendations=None),
        ):
            with self.subTest(mutate=mutate):
                snapshot = json.loads(raw)
                mutate(snapshot)
                self.replace_snapshot(request_id, snapshot)
                _, bad = training.load_groups(self.path, self.as_of)
                self.assertEqual(bad["excluded_requests"], {"invalid_or_unsafe_snapshot": 1})
        self.replace_snapshot(request_id, json.loads(raw))

    def test_missing_conflicting_feedback_and_duplicates(self):
        request_id, _ = self.first_request()
        with db.connect(self.path) as con:
            con.execute("UPDATE events SET event_type='directions_clicked' WHERE request_id=? AND event_type='restaurant_selected'", (request_id,))
        _, counts = training.load_groups(self.path, self.as_of)
        self.assertEqual(counts["excluded_requests"], {"missing_view_or_selection": 1})
        with db.connect(self.path) as con:
            con.execute("UPDATE events SET event_type='restaurant_selected' WHERE request_id=? AND event_type='directions_clicked'", (request_id,))
            original = con.execute("SELECT * FROM events WHERE request_id=? AND event_type='restaurant_selected'", (request_id,)).fetchone()
            duplicate = list(original)
            duplicate[0] = "duplicate-test-event"
            con.execute("INSERT INTO events VALUES (?, ?, ?, ?, ?, ?)", duplicate)
        self.assertEqual(training.load_groups(self.path, self.as_of)[1]["usable_requests"], 40)
        with db.connect(self.path) as con:
            con.execute("UPDATE events SET place_id=? WHERE id='duplicate-test-event'", ("2" if original[3] != "2" else "1",))
        self.assertEqual(training.load_groups(self.path, self.as_of)[1]["excluded_requests"], {"ambiguous_selection": 1})
        with db.connect(self.path) as con:
            con.execute("UPDATE events SET event_type='restaurant_rejected', place_id=? WHERE id='duplicate-test-event'", (original[3],))
        self.assertEqual(training.load_groups(self.path, self.as_of)[1]["excluded_requests"], {"conflicting_feedback": 1})

    def test_time_split_no_request_or_late_label_leakage(self):
        groups, _ = training.load_groups(self.path, self.as_of)
        train, test, cutoff, purged = training.time_split(groups)
        self.assertEqual((len(train), len(test), purged), (32, 8, 0))
        self.assertTrue({g["request_id"] for g in train}.isdisjoint(g["request_id"] for g in test))
        self.assertTrue(all(g["created_at"] < cutoff and g["label_at"] < cutoff for g in train))
        self.assertTrue(all(g["created_at"] >= cutoff for g in test))
        groups[0]["label_at"] = cutoff + timedelta(seconds=1)
        self.assertEqual(training.time_split(groups)[3], 1)
        for g in groups:
            g["created_at"] = cutoff
        self.assertEqual(training.time_split(groups)[0], [])

    def test_no_selection_means_insufficient_not_negative_training(self):
        with db.connect(self.path) as con:
            con.execute("DELETE FROM events WHERE event_type='restaurant_selected'")
        report, model = training.train_compare(self.path, self.as_of)
        self.assertIsNone(model)
        self.assertEqual(report["status"], "insufficient_data")
        self.assertEqual(report["counts"]["candidate_rows"], 0)
        self.assertNotIn("random_forest", report)
        self.assertEqual(report["production_ranking"], "rules-v2")

    def test_real_forest_training_scoring_and_trusted_reload(self):
        if importlib.util.find_spec("sklearn") is None:
            self.skipTest("Optional requirements-model.txt not installed")
        import joblib
        with db.connect(self.path) as con:
            request_id, raw = con.execute("SELECT id, snapshot_json FROM recommendation_requests ORDER BY created_at DESC LIMIT 1").fetchone()
        snapshot = json.loads(raw)
        snapshot["recommendations"][0]["score_breakdown"]["weather_category"] = "unseen-test-category"
        self.replace_snapshot(request_id, snapshot)
        before = self.path.read_bytes()
        report, model = training.train_compare(self.path, self.as_of, synthetic=True)
        self.assertEqual(report["status"], "evaluated")
        self.assertEqual(report["data_kind"], "synthetic_demo")
        self.assertEqual(report["split"]["train_requests"], 32)
        self.assertEqual(report["split"]["test_requests"], 8)
        self.assertEqual(report["production_ranking"], "rules-v2")
        for group in report["comparisons"]:
            self.assertEqual(sorted(p["rf_rank"] for p in group["candidates"]), [1, 2, 3])
            self.assertTrue(all(0 <= p["selection_score"] <= 1 for p in group["candidates"]))
            self.assertTrue(all(p["place_id"] != "4" for p in group["candidates"]))
        artifact = Path(self.temp.name) / "own-test-model.joblib"
        joblib.dump(model, artifact)
        restored = joblib.load(artifact)  # Only the artifact created in this test is trusted.
        groups, _ = training.load_groups(self.path, self.as_of)
        x = [r["features"] for r in groups[-1]["rows"]]
        self.assertEqual(model.predict_proba(x).tolist(), restored.predict_proba(x).tolist())
        self.assertEqual(before, self.path.read_bytes())
        # Test-only category must not leak into the fitted DictVectorizer.
        self.assertNotIn("category=unseen-test-category", report["feature_names"])
        expected = (1 + 1 / math.log2(3) + 0.5) / 3
        self.assertAlmostEqual(training.ranking_metrics([1, 2, 3])["ndcg_at_3"], expected)
        import numpy as np
        with patch("sklearn.pipeline.Pipeline.predict_proba", return_value=np.array([[0.5, 0.5]] * 3)):
            tied, _ = training.train_compare(self.path, self.as_of, synthetic=True)
        self.assertEqual(tied["rules"], tied["random_forest"])
        self.assertTrue(all(p["rule_rank"] == p["rf_rank"]
                            for g in tied["comparisons"] for p in g["candidates"]))

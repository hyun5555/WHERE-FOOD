"""Flask entrypoint: grounded meal decisions with optional weather hints."""
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
import math
import os
import secrets
import sqlite3
from uuid import uuid4
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, session
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import ValidationError
import requests

import db
import recommendation as rec
from workflow import run_recommendation

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32),
    DATABASE_PATH=os.environ.get("DATABASE_PATH", str(ROOT / "instance/where_food.db")),
    MAX_CONTENT_LENGTH=16 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE") == "1",
)


def database_path():
    path = str(ROOT / app.config["DATABASE_PATH"])
    db.init_db(path)
    return path


def session_id():
    if "id" not in session:
        session["id"] = str(uuid4())
    return session["id"]


@app.before_request
def check_same_origin():
    if request.method == "POST" and request.headers.get("Origin"):
        if request.headers["Origin"] != request.host_url.rstrip("/"):
            return jsonify(error="다른 사이트에서 보낸 요청은 허용하지 않습니다."), 403


@app.after_request
def private_responses(response):
    if request.path.startswith("/api/") or request.path == "/get-initial-data":
        response.headers["Cache-Control"] = "no-store"
    return response


@app.errorhandler(rec.RecommendationError)
def recommendation_error(error):
    return jsonify(error=str(error), code=error.code), error.status


@app.errorhandler(ValidationError)
def validation_error(error):
    return jsonify(error="입력 문장·위치·이벤트 형식을 확인해주세요.", code="invalid_input"), 400


@app.errorhandler(sqlite3.Error)
def database_error(error):
    app.logger.error("SQLite operation failed: %s", type(error).__name__)
    return jsonify(error="기록 저장에 실패했습니다. 다시 시도해주세요.", code="storage_unavailable"), 503


@app.errorhandler(413)
def request_too_large(error):
    return jsonify(error="요청 크기가 너무 큽니다."), 413


@app.get("/")
def index():
    session_id()
    return render_template("index.html", kakao_js_key=os.environ.get(
        "KAKAO_JAVASCRIPT_KEY", "e18d3ee9cbbf978c2e37e5fc08de3b81"))


@app.get("/api/health")
def health():
    return jsonify(
        parser=rec.parser_health(),
        places_configured=bool(os.environ.get("KAKAO_REST_API_KEY")),
        menu_count=db.menu_count(database_path()),
    )


def draft_serializer():
    return URLSafeTimedSerializer(app.secret_key, salt="meal-constraints-v1")


@app.post("/api/constraints")
def extract_constraints():
    payload = rec.RecommendInput.model_validate(request.get_json(silent=True))
    parsed = rec.parse_constraints(payload.query)
    values = parsed.model_dump(mode="json", exclude={"source_spans", "unknown_terms"})
    # Do not persist the query or draft. The signed token is not encryption: browser memory only.
    token = draft_serializer().dumps({"session": session_id(), "constraints": values,
                                      "unknown_terms": parsed.unknown_terms})
    return jsonify(draft_token=token, expires_in=1800, constraints=values, unknown_terms=parsed.unknown_terms,
                   status="review_required", parser={"provider": "ollama", "model": rec.OLLAMA_MODEL, "version": rec.PARSER_VERSION})


@app.post("/api/recommend")
def recommend_meal():
    payload = rec.ConfirmedRecommendInput.model_validate(request.get_json(silent=True), strict=True)
    try:
        draft = draft_serializer().loads(payload.draft_token, max_age=1800)
        if draft["session"] != session_id():
            raise BadSignature("different session")
    except SignatureExpired:
        return jsonify(error="조건 초안이 만료되었습니다. 다시 해석해주세요.", code="draft_expired"), 409
    except BadSignature:
        return jsonify(error="현재 세션의 조건 초안을 확인할 수 없습니다. 다시 해석해주세요.", code="invalid_draft"), 400
    if not set(payload.ignored_unknown_terms).issubset(draft["unknown_terms"]):
        return jsonify(error="제외할 미지원 조건을 확인해주세요.", code="invalid_input"), 400
    values = payload.constraints.model_dump(mode="json")
    c = rec.MealConstraints(**values, source_spans=[],
                           unknown_terms=[v for v in draft["unknown_terms"] if v not in payload.ignored_unknown_terms])
    result = run_recommendation(c, payload, database_path(), weather_ranking)
    result["confirmation"] = {"source": "user_confirmed", "confirmed_at": db.utcnow(),
                              "edited_fields": [k for k, v in values.items() if v != draft["constraints"].get(k)],
                              "ignored_unknown_count": len(set(payload.ignored_unknown_terms))}
    db.save_request(database_path(), session_id(), result)
    return jsonify(result)


@app.post("/api/events")
def record_event():
    event = rec.EventInput.model_validate(request.get_json(silent=True))
    try:
        db.record_event(database_path(), session_id(), event)
    except ValueError as error:
        return jsonify(error=str(error), code="invalid_event"), 400
    return "", 204


def convert_grid(lat, lon):
    """Existing KMA Lambert projection, coordinates in WGS84."""
    rad = math.pi / 180
    re, slat1, slat2 = 6371.00877 / 5, 30 * rad, 60 * rad
    sn = math.log(math.cos(slat1) / math.cos(slat2)) / math.log(
        math.tan(math.pi / 4 + slat2 / 2) / math.tan(math.pi / 4 + slat1 / 2))
    sf = math.tan(math.pi / 4 + slat1 / 2) ** sn * math.cos(slat1) / sn
    ro = re * sf / math.tan(math.pi / 4 + 38 * rad / 2) ** sn
    ra = re * sf / math.tan(math.pi / 4 + lat * rad / 2) ** sn
    theta = ((lon - 126) * rad + math.pi) % (2 * math.pi) - math.pi
    theta *= sn
    return int(ra * math.sin(theta) + 43.5), int(ro - ra * math.cos(theta) + 136.5)


@lru_cache(maxsize=1)
def load_weather_model():
    try:
        import joblib
        return joblib.load(ROOT / "model/weather_food_regression_model3.pkl")
    except Exception:
        app.logger.info("Optional legacy weather model unavailable")
        return None


def weather_hints(weather, region, now):
    model = load_weather_model()
    if model is None:
        return []
    try:
        import pandas as pd
        t, h, rain, wind = (weather[k] for k in ("temp", "humidity", "rain_mm", "wind_speed"))
        base = {
            "기온값": t, "습도값": h, "강수량 값": rain, "풍속값": wind,
            "기온상태": "매우 더움" if t >= 28 else "더움" if t >= 23 else "보통" if t >= 17 else "선선함" if t >= 12 else "쌀쌀함" if t >= 5 else "추움",
            "습도상태": "매우 습함" if h >= 80 else "습함" if h >= 60 else "보통" if h >= 40 else "건조",
            "강수 유형명": "없음" if rain < .1 else "아주 약한 비" if rain < 3 else "약한 비" if rain < 10 else "보통 비" if rain < 20 else "강한 비",
            "바람강도 유형명": "매우 강" if wind >= 13.9 else "강" if wind >= 9 else "약간 강" if wind >= 4 else "보통" if wind >= 1.6 else "약",
            "광역시도명": region.get("region_1depth_name", "알 수 없음"),
            "시군구명": region.get("region_2depth_name", "알 수 없음"),
            "weekday": now.weekday(), "is_weekend": int(now.weekday() >= 5), "month": now.month,
            "season": "겨울" if now.month in (12, 1, 2) else "봄" if now.month < 6 else "여름" if now.month < 9 else "가을",
        }
        foods = ["치킨", "한식", "분식", "카페/디저트", "족발/보쌈", "패스트푸드", "돈까스/일식", "피자", "찜탕", "중식", "아시안/양식", "회", "도시락"]
        scores = model.predict(pd.DataFrame([{**base, "배달상점 업종명": f} for f in foods]))
        return [{"name": f, "weather_score": round(float(s), 3)} for f, s in
                sorted(zip(foods, scores), key=lambda pair: pair[1], reverse=True) if math.isfinite(float(s))]
    except Exception:
        app.logger.info("Optional weather prediction unavailable")
        return []


@app.post("/get-initial-data")
def get_initial_data():
    raw = request.get_json(silent=True)
    if not isinstance(raw, dict):
        return jsonify(error="위치를 확인해주세요."), 400
    payload = rec.RecommendInput.model_validate({**raw, "query": "날씨"})
    if payload.lat is None:
        return jsonify(error="위치를 확인해주세요."), 400
    result = weather_context(payload.lat, payload.lon)
    result["recommendations"] = result["recommendations"][:3]
    return jsonify(result)


def weather_context(lat, lon):
    """Shared server-side observations for hints and ranking at the resolved origin."""
    # The KMA grid only covers Korea; avoid projecting poles or unsupported locations.
    if not 33 <= lat <= 39 or not 124 <= lon <= 132:
        return dict(weather={"error": "날씨는 한국 내 위치에서 지원합니다."},
                    recommendations=[], location={"name": "선택한 위치"})
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    observation = (now - timedelta(hours=int(now.minute < 40))).replace(minute=0, second=0, microsecond=0)
    x, y = convert_grid(lat, lon)
    region = {}
    try:
        docs = rec.kakao_get("/v2/local/geo/coord2address.json", {"x": lon, "y": lat}).get("documents", [])
        region = (docs[0].get("address") or {}) if docs else {}
    except rec.RecommendationError:
        pass
    result = {"location": {"name": region.get("address_name", "선택한 위치")}, "recommendations": []}
    try:
        key = os.environ.get("WEATHER_API_KEY")
        if not key:
            raise ValueError("weather not configured")
        response = requests.get("https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtNcst", params={
            "serviceKey": key, "numOfRows": 10, "pageNo": 1, "dataType": "JSON",
            "base_date": observation.strftime("%Y%m%d"), "base_time": observation.strftime("%H00"), "nx": x, "ny": y,
        }, timeout=(3, 5))
        response.raise_for_status()
        values = {i["category"]: i["obsrValue"] for i in response.json()["response"]["body"]["items"]["item"]}
        rain = 0.0 if values["RN1"] == "강수없음" else float(values["RN1"])
        weather = {"temp": float(values["T1H"]), "humidity": float(values["REH"]),
                   "wind_speed": float(values["WSD"]), "rain_mm": rain,
                   "rain_type_code": str(values["PTY"]), "sky_code": values.get("SKY"),
                   "observed_at": observation.isoformat()}
        if not all(math.isfinite(weather[k]) for k in ("temp", "humidity", "wind_speed", "rain_mm")):
            raise ValueError("invalid weather")
        result.update(weather=weather, recommendations=weather_hints(weather, region, now))
    except (requests.RequestException, ValueError, KeyError, TypeError):
        result["weather"] = {"error": "날씨를 확인하지 못했습니다. 식사 조건 검색은 계속 이용할 수 있습니다."}
    return result


def weather_ranking(origin):
    if load_weather_model() is None:
        return {"scores": {}, "available": False, "reason": "날씨 참고 모델 미설치 또는 로딩 실패"}
    context = weather_context(origin["lat"], origin["lon"])
    weather = context["weather"]
    if "error" in weather:
        return {"scores": {}, "available": False, "reason": weather["error"]}
    scores = {row["name"]: row["weather_score"] for row in context["recommendations"]}
    return {"scores": scores, "available": bool(scores), "observed_at": weather["observed_at"],
            "model": "weather_food_regression_model3.pkl", "kind": "legacy_reference_score_not_probability",
            "source": {"title": "기상청 초단기 관측 API", "url": "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtNcst"}}


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=False)

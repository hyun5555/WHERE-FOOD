# WHERE FOOD — 근거 기반 식사 추천 MVP

Flask + Vanilla JS로 자연어 → 제약 JSON → 실제 장소/메뉴 조회 → 규칙 필터 → 최대 3곳 → 선택 기록을 연결합니다.
OpenAI 파서는 제약 추출용으로 구현했지만 **현재 외부 자연어 API 호출은 기본 비활성화**입니다. 숫자·필수 조건 판정·정렬·설명은 서버 코드가 수행합니다.

## 실행

Python 3.11 이상을 사용합니다. 기존 `venv`는 Python 3.9/3.11 경로가 섞여 있어 새 `.venv`를 사용합니다.

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/import_menu_data.py
.venv/bin/python app.py
```

http://127.0.0.1:8000 에서 실행됩니다. `.env`에 `.env.example`의 설정을 반영하세요. 기존 키를 덮어쓰지 마세요.

- 공용 `OPENAI_API_KEY`는 사용하지 않습니다. 기존 환경변수와 `.env`의 키도 변경하지 않습니다.
- `WHERE_FOOD_ENABLE_OPENAI`: 기본 `0`. 별도 프로젝트 키 사용을 명시적으로 승인한 뒤에만 `1`로 설정합니다.
- `WHERE_FOOD_OPENAI_API_KEY`: 별도로 승인받은 프로젝트 전용 키. 공용 키를 복사하지 마세요. 활성화와 전용 키 중 하나라도 없으면 `/api/recommend`는 외부 호출 없이 `503 parser_not_configured`를 반환합니다.
- `WHERE_FOOD_OPENAI_MODEL`: 기본 `gpt-5-mini`. 계정에서 사용 가능한 Structured Outputs 지원 모델.
- `KAKAO_REST_API_KEY`: 장소·좌표·도보 경로 조회용.
- `KAKAO_JAVASCRIPT_KEY`: 지도 표시용 공개 앱 키. 카카오 개발자 설정에 사용하는 로컬 도메인을 등록하세요.
- `WEATHER_API_KEY`: 선택. 날씨 실패는 식당 추천을 막지 않습니다.
- `FLASK_SECRET_KEY`: 지속적인 랜덤 값. 미설정 시 프로세스마다 임시 키가 생겨 재시작 후 이전 세션 기록에 접근할 수 없습니다. 운영/여러 worker는 동일한 값 필요.
- `DATABASE_PATH`: 기본 `instance/where_food.db`. `instance/`는 Git에서 제외합니다.
- `COOKIE_SECURE=1`: HTTPS로 서비스할 때 설정합니다.

확인용 `GET /api/health`는 키의 **설정 여부**와 메뉴 개수만 반환합니다. 키 유효성 확인은 아닙니다.
실행 시점에 키를 추가했다면 서버를 재시작하세요.

기존 날씨 모델의 카테고리 힌트를 켜려면 추가 설치합니다.

```sh
.venv/bin/python -m pip install -r requirements-model.txt
```

기존 모델은 2019–2020년 집계 기반 참고 힌트로 남겨두었습니다. 실제 식당 순위에는 사용하지 않습니다.
학습·그래프 스크립트와 모델 파일은 보존했으며, Selenium과 공용 `result.png` 생성은 웹 요청 경로에서 제거했습니다.

## 구현 위치

| 파일 | 역할 |
| --- | --- |
| `app.py` | HTTP 입력 검증, 익명 세션, 추천·행동 API, 선택적 날씨 조회 |
| `recommendation.py` | Pydantic 스키마, OpenAI 파서, 위치 확인, 카카오 검색·경로, 근거 필터, 정렬 |
| `db.py` | 메뉴 upsert, 요청 스냅샷, 세션/추천 소속을 확인하는 멱등 이벤트 저장 |
| `scripts/import_menu_data.py` | 전체 CSV를 검증한 후 한 트랜잭션으로 반영 |
| `data/menu_items.csv` | 실제 출처를 가진 메뉴 초기 데이터 |
| `static/js/recommend.js` | 자연어 요청, 취소·오래된 응답 무시, 조건 변경 |
| `static/js/restaurant.js` | 근거 카드와 안전한 텍스트/링크 렌더링, 행동 전송 |
| `tests/test_recommendation.py`, `test_recommend_flow.js` | 핵심 규칙·API·화면 흐름 회귀 검사 |

## 데이터와 현재 범위

2026-09-07 카카오 공식 API에서 식당 ID와 주소를 대조했습니다. 초기 데이터는 식당 3곳·메뉴 7개입니다.
출처 게시일을 근거 기준일로 보존했으며, 오늘 링크를 열었다는 이유로 가격을 오늘 확인한 값으로 바꾸지 않았습니다.

| 식당 | 메뉴 수 | 출처 기준일 | 출처 |
| --- | --- | --- | --- |
| 사누키제면소 | 2 | 2026-06-29 | [강남구청](https://www.gangnam.go.kr/board/B_000034/1069280/view.do?mid=ID02_010804) |
| 향원 | 3 | 2026-06-29 | [강남구청](https://www.gangnam.go.kr/board/B_000034/1069279/view.do?mid=ID02_010804) |
| 장모님밥상 | 2 | 2025-12-18 | [강남구청](https://www.gangnam.go.kr/board/B_000034/1069271/view.do?mid=ID02_010804) |

초기 데이터는 메뉴명·가격 사실과 출처만 수록했습니다. 사진이나 전체 소개글은 포함하지 않았습니다.
출처 페이지에는 이용 조건이 있으므로 상용 데이터 확장은 사용 가능한 제공처/매장 확인 자료로 진행하세요.
90일보다 오래된 근거는 재확인 대상으로 제외하므로 장모님밥상은 현재 확정 추천에서 제외됩니다.
현재 데이터에는 땅콩 미사용·알레르기 교차접촉·조용함 근거가 없습니다.
따라서 예제의 땅콩 제외 조건은 결과 없음이 정상이며, 일반 메뉴로 자동 완화하지 않습니다.

먼저 “강남역에서 1만 5천 원 이하 식당”으로 확인하고, 식재료/분위기 근거를 확보한 후 더 복잡한 조건을 검증하세요.
메뉴 데이터는 자동 수집·자동 갱신하지 않습니다.

CSV의 `menu_evidence`는 다음 JSON을 셀 안에 넣습니다. `observed_on`은 실제 확인일 또는 출처의 사실 기준일입니다.

```json
{
  "title": "매장 공식 메뉴 또는 확인 기록",
  "url": "https://example.com/actual-menu-evidence",
  "observed_on": "2026-09-07",
  "excerpt": "해당 메뉴명과 1인 메뉴 가격을 입증하는 짧은 원문"
}
```

`tags`, `absent_ingredients`, `atmosphere`는 각각 `[{"term": "...", "evidence": {...}}]` 형식입니다.
`allergy_checks`는 여기에 `cross_contact_checked`가 추가됩니다. 식당의 해당 성분 미사용과 교차접촉 관리에 대한 명시적 확인 기록이 있을 때만 true입니다.
재료 목록에 이름이 없다는 사실, 메뉴명에서의 추정, 블로그 추측은 미사용/알레르기 근거가 아닙니다.
빈 배열은 **미확인**입니다. 단순 기피 재료와 알레르기는 구분하고, 알레르기는 방문 전 재확인을 안내합니다.
실제 가격이 없는 경우 `price_krw`를 비워 두면 저장할 수 있지만 추천 후보로는 통과하지 않습니다.

데이터 반영은 `(place_id, menu_name)` 단위 upsert이며 다른 메뉴·사용자 기록은 삭제하지 않습니다.
원하는 경우 `--database /path/to/file.db`로 별도 DB를 지정할 수 있습니다.

## API 계약

`POST /api/recommend`:

```json
{
  "query": "강남역에서 도보 10분, 1만 5천 원 이하",
  "lat": null,
  "lon": null,
  "origin_place_id": null
}
```

문장 내 위치가 우선입니다. 위치 결과가 여러 개면 `clarification_required`와 `location_options`를 반환합니다.
선택된 ID는 다음 요청의 `origin_place_id`로 보내며 서버는 다시 조회한 후보와 대조합니다.
장소 없는 문장에는 lat/lon이 필요합니다. 클라이언트가 추출 JSON, 금액, 추천 순위를 직접 확정하도록 허용하지 않습니다.

응답에는 `request_id`, `constraints`, `origin`, `status`, `recommendations`, `diagnostics`가 들어갑니다.
추천 항목에는 장소 정보, 대표 메뉴·가격·출처, 충족 조건의 근거, 미확인 선호, 조회 시각, 경로가 들어갑니다.

상태:

- `ok`: 3곳 확인
- `partial`: 1~2곳 확인. 조건 미충족 식당으로 3곳을 채우지 않음
- `no_results`: 검색 범위/확보 데이터에서 확인된 후보 없음
- `clarification_required`: 위치 선택·모호하거나 현재 지원하지 않는 조건 확인 필요

HTTP 오류는 JSON의 `error`, `code`로 반환합니다. 잘못된 입력은 400, 파싱 거절·실패는 422, 설정·외부 서비스·저장 장애는 503입니다.

`POST /api/events`:

```json
{
  "id": "이벤트 UUID",
  "request_id": "추천 응답의 UUID",
  "event_type": "restaurant_selected",
  "place_id": "실제로 노출된 식당 ID"
}
```

종류는 `recommendations_viewed`, `restaurant_selected`, `restaurant_rejected`, `detail_clicked`, `directions_clicked`입니다.
노출 이벤트는 place_id=null, 나머지는 실제 추천한 장소만 허용합니다. 순위와 세션 ID는 서버에서 결정합니다.
같은 이벤트 ID 재시도는 중복 저장하지 않습니다. 다른 세션/다른 요청의 식당에 대한 임의 선택 기록은 거부합니다.
원문·정확한 시작 좌표·좌표가 들어간 경로 링크는 저장 스냅샷에서 제거합니다. 메뉴·추출 조건·노출 후보·순위·출처·행동은 보존합니다.
클릭은 방문/주문이나 최종 선택의 정답으로 자동 간주하지 않습니다.

## 필터·정렬 정책

1. 근거 날짜(현재 기준 90일), 가격 존재 여부 확인
2. 예산, 제외 음식/재료, 알레르기와 필수 특성 검증
3. 요청된 직선거리 상한 검사
4. 도보 조건이 있으면 실제 경로 API의 초 단위 예상 시간을 검사. 600초는 통과, 601초는 제외
5. 같은 식당의 통과 메뉴 중 선호 일치가 많고 저렴한 메뉴 한 개 선택
6. 선호 일치 수 → 도보 시간(도보 미요청 시 직선거리) → 가격 → 장소 ID 순 정렬

검색은 기본 2km, 가까운 음식점 최대 45곳 + 현재 메뉴 카탈로그 최대 6개 상호의 검색 결과(각 5개)를 합칩니다.
검색·태그는 범위가 제한된 MVP입니다. 데이터가 늘면 지역별 카탈로그 인덱스와 검색 재현율을 먼저 개선하세요.
가격·거리 등의 숫자는 원문 단위를 서버에서 다시 계산합니다. 스키마 형식이 맞아도 LLM의 의미 추출 정확성은 별도 평가가 필요합니다.
지원하지 않는 영업시간·채식·복합 OR·전체 인원 예산 등은 파서가 `unknown_terms`로 남겨 재질문합니다. 자동 조건 완화는 하지 않습니다.
알레르기 기록은 안전 보증이 아닙니다. 누락 근거를 만들어 추천하지 않습니다.

## 검증

```sh
.venv/bin/python -m unittest discover -s tests -v
node test_recommend_flow.js
.venv/bin/python -m pip check
```

외부 호출은 테스트에서 모의 응답으로 대체합니다. 테스트 데이터는 임시 DB에만 저장합니다.
실제 카카오 검색·도보 API를 확인했습니다. 초기 브라우저 검증에서 공용 환경변수 키로 OpenAI 파싱 호출이 발생했으나, 사용 금지 요청 직후 서버를 중지하고 공용 키 자동 사용을 제거했습니다. 이후 검증은 외부 호출 없는 모의 테스트만 사용합니다.
회귀 테스트는 공용 키가 존재해도 전용 키/명시적 활성화가 없으면 OpenAI 클라이언트를 생성하지 않음을 확인합니다. 실제 모델 품질 평가는 별도 키 사용 승인 또는 로컬 파서 선택 이후에 진행해야 합니다.

## 공식 구현 참고

- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [카카오 장소 검색](https://developers.kakao.com/docs/ko/local/dev-guide)
- [카카오 도보 경로](https://developers.kakao.com/docs/ko/kakaomap/rest-api)

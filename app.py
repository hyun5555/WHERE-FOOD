# app.py
from flask import Flask, render_template, request, jsonify
from flask_caching import Cache
import requests
import datetime
import math
import joblib
import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
import time
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from flask_cors import CORS
import urllib.parse

import genimg as  gn

app = Flask(__name__)
CORS(app)

config = {
    "DEBUG": True,
    "CACHE_TYPE": "SimpleCache", 
    "CACHE_DEFAULT_TIMEOUT": 300
}
app.config.from_mapping(config)
cache = Cache(app)

# ❗️ 카카오 REST API 키
KAKAO_API_KEY = "REDACTED"
# ❗️ 기상청 API 키 디코딩
WEATHER_API_KEY = "REDACTED"


#--- ✅ 1. 모델 및 통계 테이블 로드/생성 (서버 시작 시) ---
try:
    # 회귀 모델은 전처리 파이프라인을 포함하고 있으므로, 모델 객체 하나만 로드합니다.
    regression_model = joblib.load("./model/weather_food_regression_model3.pkl")
    print("✅ 회귀 모델 로드 성공!")
except Exception as e:
    print(f"❌ 회귀 모델 로드 중 오류 발생: {e}")
    regression_model = None




# --- 헬퍼 함수
def convert_grid(lat, lon):
    RE = 6371.00877; GRID = 5.0; SLAT1 = 30.0; SLAT2 = 60.0; OLON = 126.0; OLAT = 38.0
    XO = 43; YO = 136; DEGRAD = math.pi / 180.0; re = RE / GRID; slat1 = SLAT1 * DEGRAD
    slat2 = SLAT2 * DEGRAD; olon = OLON * DEGRAD; olat = OLAT * DEGRAD
    sn = math.tan(math.pi * 0.25 + slat2 * 0.5) / math.tan(math.pi * 0.25 + slat1 * 0.5)
    sn = math.log(math.cos(slat1) / math.cos(slat2)) / math.log(sn)
    sf = math.tan(math.pi * 0.25 + slat1 * 0.5); sf = math.pow(sf, sn) * math.cos(slat1) / sn
    ro = math.tan(math.pi * 0.25 + olat * 0.5); ro = re * sf / math.pow(ro, sn)
    ra = math.tan(math.pi * 0.25 + lat * DEGRAD * 0.5); ra = re * sf / math.pow(ra, sn)
    theta = lon * DEGRAD - olon
    if theta > math.pi: theta -= 2.0 * math.pi
    if theta < -math.pi: theta += 2.0 * math.pi
    theta *= sn; x = ra * math.sin(theta) + XO + 0.5; y = ro - ra * math.cos(theta) + YO + 0.5
    return int(x), int(y)


def get_address_from_coords(api_key, lon, lat):
    headers = {"Authorization": f"KakaoAK {api_key}"}
    url = f"https://dapi.kakao.com/v2/local/geo/coord2address.json?x={lon}&y={lat}"
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        if not data['documents']: return "알 수 없음", "알 수 없음", "알 수 없음"
        address = data['documents'][0]['address']
        return address.get('address_name'), address.get('region_1depth_name'), address.get('region_2depth_name')
    except Exception as e:
        print(f"❌ 카카오 API 오류: {e}")
        return "주소 조회 실패", "주소 조회 실패", "주소 조회 실패"


# --- Selenium 웹 드라이버 설정 함수 ---
def setup_driver():
    """Selenium 웹 드라이버를 설정하고 반환합니다."""
    options = Options()
    # User-Agent 설정 (크롤링 방지 회피)
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36")
    options.add_argument("--headless")
    # 불필요한 로그 메시지 제거
    options.add_experimental_option("excludeSwitches", ["enable-logging"])
    
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        return driver
    except Exception as e:
        print(f"❌ 웹 드라이버 설정 중 오류 발생: {e}")
        return None

# --- 평점 크롤링 함수 ---
def get_place_rating(driver, place_url):
    """주어진 URL에서 평점과 리뷰 수를 크롤링합니다."""
    try:
        driver.get(place_url)
        
        wait = WebDriverWait(driver, 5)

        # ✅ 평점 찾기 (CSS 선택자)
        rating_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "span.num_star")))
        rating = float(rating_element.text)

        # ✅ 리뷰 수 (CSS 선택자)
        review_count = 0
        try:
            review_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "span.info_num")))
            review_count_text = ''.join(filter(str.isdigit, review_element.text))
            if review_count_text.isdigit():
                review_count = int(review_count_text)
        except TimeoutException:
            pass
            
        return rating, review_count

    except TimeoutException:
        return 0.0, 0
    except Exception as e:
        return 0.0, 0
    
# --- Flask 라우트 ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get-initial-data', methods=['POST'])
def get_initial_data():
    if not regression_model:
        return jsonify({"error": "서버 모델이 준비되지 않았습니다."}), 500
    
    req_data = request.json
    lat = float(req_data['lat'])
    lon = float(req_data['lon'])

    # 1. 날씨 정보 가져오기 (풍속, 강수량 추가)
    x, y = convert_grid(lat, lon)
    now = datetime.datetime.now()
    if now.minute < 40: now -= datetime.timedelta(hours=1)
    base_date = now.strftime('%Y%m%d')
    base_time = now.strftime('%H00')
    
    weather_info = {}
    try:
        # (기존 날씨 API 호출 로직)
        weather_url = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtNcst"
        params = {
            "serviceKey": WEATHER_API_KEY,
            "numOfRows": 10,
            "pageNo": 1,
            "dataType": "JSON",
            "base_date": base_date,
            "base_time": base_time,
            "nx": x,
            "ny": y
        }
        response = requests.get(weather_url,params=params,timeout=5)
        response.raise_for_status()
        items = response.json()['response']['body']['items']['item']
        print(items)
        weather_raw = {item['category']: item['obsrValue'] for item in items}
        
        rain_rate = weather_raw['RN1']
        rain_rate = rain_rate if '강수' in str(rain_rate) else float(rain_rate)
        print(f"강수량:{rain_rate}")
        
        weather_info = {
            "temp": float(weather_raw.get('T1H', 0)),
            "rain_type_code": weather_raw.get('PTY', '0'),
            "sky_code": weather_raw.get('SKY', '1'),
            "humidity": float(weather_raw.get('REH', 0)),
            "wind_speed": float(weather_raw.get('WSD', 1.0))
        }
    except Exception as e:
        rain_rate = 0
        weather_info = {"temp": 0, "rain_type_code": '0', "sky_code": '1', "humidity": 0, "wind_speed": 1.0, "error": "날씨 정보 조회 실패"}

    # 2. 카카오 API로 주소 정보 가져오기
    full_address, region_1d, region_2d = get_address_from_coords(KAKAO_API_KEY, lon, lat)
    
    # --- 3. 상태 변환 함수 및 모델 입력 데이터 생성 (새로운 로직) ---
    # 상태 변환 함수 정의
    def get_temp_state(t): return '매우 더움' if t >= 28 else '더움' if t >= 23 else '보통' if t >= 17 else '선선함' if t >= 12 else '쌀쌀함' if t >= 5 else '추움'
    def get_humidity_state(h): return '매우 습함' if h >= 80 else '습함' if h >= 60 else '보통' if h >= 40 else '건조'
    rain_type_map = {'0': '없음', '1': '비', '2': '비/눈', '3': '눈', '4': '소나기', '5': '빗방울', '6': '빗방울/눈날림', '7': '눈날림'}
    def get_wind_state(ws): return '매우 강' if ws >= 13.9 else '강' if ws >= 9 else '약간 강' if ws >= 4 else '보통' if ws >= 1.6 else '약'
    def get_season(m): return '겨울' if m in [12, 1, 2] else '봄' if m in [3, 4, 5] else '여름' if m in [6, 7, 8] else '가을'
    def get_rain_type(v): 
        if v < 0.1 : return "없음" 
        elif v < 3.0 : return "아주 약한 비"
        elif v < 10 : return "약한 비"
        elif v < 20 : return "보통 비"
        return "강한 비"
    
    # 기본 피처 딕셔너리 생성
    base_input = {
        '기온값': weather_info.get('temp'), '습도값': weather_info.get('humidity'),
        '강수량 값': 0.0 if weather_info.get('rain_type_code') == '0' else 1.0,
        '풍속값': weather_info.get('wind_speed'),
        '기온상태': get_temp_state(weather_info.get('temp')),
        '습도상태': get_humidity_state(weather_info.get('humidity')),
        '강수 유형명': get_rain_type(rain_rate),
        '바람강도 유형명': get_wind_state(weather_info.get('wind_speed')),
        '광역시도명': region_1d, '시군구명': region_2d,
        'weekday': now.weekday(), 'is_weekend': 1 if now.weekday() >= 5 else 0,
        'month': now.month, 'season': get_season(now.month)
    }
    
    today_temp = base_input['기온상태']
    today_humidity =  base_input['습도상태']
    today_rain = base_input['강수 유형명'] 
    today_wind = base_input['바람강도 유형명']
    
    print(f"today_temp={today_temp}")
    print(f"today_humidity={today_humidity}")
    print(f"today_rain={today_rain}")
    print(f"today_wind={today_wind}")
    
    gn.MakeImage(False,today_temp,today_humidity,today_rain)
    
    print("--------------------\n 오늘의날씨 ==> ",today_humidity,"기온",today_temp,"강수",today_rain,"바람",today_wind)
    print("make image end")
    final_scores = {}
    
    # --- 통계 피처 추가 및 반복 예측 로직 ---
   # 학습 때 사용했던 모든 음식 카테고리 목록을 직접 정의
    # --- 4. [핵심] 일괄 예측(Batch Prediction)을 위한 로직 변경 ---
    all_food_categories = [
        '치킨', '한식', '분식', '카페/디저트', '족발/보쌈', '패스트푸드', 
        '돈까스/일식', '피자', '찜탕', '중식', '아시안/양식', '회', '도시락'
    ]

    # 4-1. 모든 음식 카테고리에 대한 입력 데이터를 하나의 리스트로 준비합니다.
    model_inputs = []
    for food in all_food_categories:
        model_input = base_input.copy()
        model_input['배달상점 업종명'] = food
        model_inputs.append(model_input)
    
    # 4-2. 리스트를 하나의 DataFrame으로 변환합니다.
    input_df = pd.DataFrame(model_inputs)

    # 4-3. predict()를 단 한 번만 호출하여 모든 점수를 한꺼번에 예측합니다.
    predicted_scores = regression_model.predict(input_df)

    # 4-4. 음식 이름과 예측된 점수를 다시 딕셔너리로 매핑합니다.
    final_scores = dict(zip(all_food_categories, predicted_scores))
    print(final_scores)
    
    # 5. 예측된 점수를 기준으로 내림차순 정렬 및 결과 반환
    sorted_scores = sorted(final_scores.items(), key=lambda item: item[1], reverse=True)
    print("\n---------",sorted_scores)
    
    
    # 점수가 음수인 경우 0으로 처리하여 % 계산 오류 방지
    total_score = sum(max(0, score) for name, score in sorted_scores)
    
    # 이미지를 생성한다.
    
    recommendations = []
    if total_score > 0:
        recommendations = [
            {"name": name, "prob": f"{(max(0, score) / total_score) * 100:.2f}%"}
            for name, score in sorted_scores
        ]
    
    final_data = {
        "weather": weather_info,
        "location": {"name": full_address},
        "recommendations": recommendations,
        "image": "result.png"
    }
    return jsonify(final_data)

#  맛집 검색 및 크롤링 라우트
@app.route('/search-places', methods=['POST'])
def search_places_with_rating():
    data = request.json
    keyword = data.get('keyword')
    lat = data.get('lat')
    lon = data.get('lon')

    if not all([keyword, lat, lon]):
        return jsonify({"error": "필수 파라미터가 없습니다."}), 400

    # 1. 카카오 장소 검색 API 호출
    headers = {"Authorization": f"KakaoAK {KAKAO_API_KEY}"}
    url = f"https://dapi.kakao.com/v2/local/search/keyword.json?query={keyword}&y={lat}&x={lon}&radius=2000&sort=accuracy"
    
    try:
        response = requests.get(url, headers=headers, timeout=5)
        response.raise_for_status()
        places = response.json().get('documents', [])
    except Exception as e:
        print(f"❌ 카카오 장소 검색 API 오류: {e}")
        return jsonify({"error": "맛집 검색에 실패했습니다."}), 500

    # 2. Selenium으로 평점 크롤링
    driver = setup_driver()
    if not driver:
        return jsonify({"error": "크롤링 드라이버 설정에 실패했습니다."}), 500
        
    places_with_ratings = []
    for place in places:
        # 상세 페이지 URL이 없는 경우 건너뛰기
        place_url = place.get('place_url')
        if not place_url:
            continue

        rating, review_count = get_place_rating(driver, place_url)
        
        # 기존 place 딕셔너리에 평점 정보 추가
        place['rating'] = rating
        place['review_count'] = review_count
        places_with_ratings.append(place)

    driver.quit()

    return jsonify(places_with_ratings)


if __name__ == '__main__':
    app.run(host="0.0.0.0", port=8000, debug=False)
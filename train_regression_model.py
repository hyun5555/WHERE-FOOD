"""Fit a legacy aggregate-weather heuristic, not a future user-choice target.

The label is constructed from this dataset's aggregate ratios. A random CV score
on that label is not evidence of recommendation effectiveness or generalization.
"""
import argparse
from pathlib import Path
import pandas as pd
# ★★★ 회귀 모델 및 평가 지표로 변경 ★★★
from sklearn.ensemble import RandomForestRegressor
# ------------------------------------
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
import joblib

# --- 1. 데이터 로드 및 "점수(Y)"와 "피처(X)" 생성 함수 ---
def load_and_prepare_data_for_regression(filepath):
    """
    데이터를 로드하고, 회귀 모델 학습에 맞게 '점수(y)'와 '피처(X)'를 생성합니다.
    """
    df = pd.read_csv(filepath, encoding='utf-8')
    df.columns = df.columns.str.strip()

    # --- 기본 피처 생성 (EDA 코드와 동일) ---
    df['date'] = pd.to_datetime(df['년'].astype(str) + '-' + df['월'].astype(str) + '-' + df['일'].astype(str))
    df['weekday'] = df['date'].dt.weekday
    df['is_weekend'] = (df['weekday'] >= 5).astype(int)
    df['month'] = df['date'].dt.month
    def month_to_season(m):
        if m in [12, 1, 2]: return '겨울'
        if m in [3, 4, 5]: return '봄'
        if m in [6, 7, 8]: return '여름'
        return '가을'
    df['season'] = df['month'].apply(month_to_season)

    # --- ★★★ [핵심] Y값(정답)이 될 "추천 점수"를 새로 정의 ★★★ ---
    print("▶ 추천 점수(Y값) 생성을 시작합니다...")
    
    # 1. 날씨 상태별 "비율" 테이블 생성 (EDA 코드와 동일한 로직)
    # (주의: .div() 결과에 100을 곱하지 않아 0~1 사이의 비율 값으로 유지)
    temp_stats = df.groupby(["배달상점 업종명", "기온상태"])["주문 건수"].sum().unstack(fill_value=0)
    temp_stats_ratio = temp_stats.div(temp_stats.sum(axis=1), axis=0)
    
    hum_stats = df.groupby(["배달상점 업종명", "습도상태"])["주문 건수"].sum().unstack(fill_value=0)
    hum_stats_ratio = hum_stats.div(hum_stats.sum(axis=1), axis=0)

    # 강수 데이터는 '없음'을 제외하고 계산
    rain_df = df[df["강수 유형명"] != "없음"].copy()
    rain_stats = rain_df.groupby(["배달상점 업종명", "강수 유형명"])["주문 건수"].sum().unstack(fill_value=0)
    rain_stats_ratio = rain_stats.div(rain_stats.sum(axis=1), axis=0)

    # 2. 각 데이터 행(row)에 해당하는 '추천 점수'를 계산하여 새로운 'score' 컬럼 생성
    def calculate_score(row):
        score = 0
        food = row['배달상점 업종명']
        
        # 기온 점수 (해당 날씨 상태의 비율 값)
        temp_state = row['기온상태']
        if temp_state in temp_stats_ratio.columns and food in temp_stats_ratio.index:
            score += temp_stats_ratio.loc[food, temp_state]
        
        # 습도 점수
        hum_state = row['습도상태']
        if hum_state in hum_stats_ratio.columns and food in hum_stats_ratio.index:
            score += hum_stats_ratio.loc[food, hum_state]
            
        # 강수 점수 (비/눈 등이 올 때만 더함)
        rain_type = row['강수 유형명']
        if rain_type != '없음' and rain_type in rain_stats_ratio.columns and food in rain_stats_ratio.index:
            score += rain_stats_ratio.loc[food, rain_type]
            
        return score

    df['score'] = df.apply(calculate_score, axis=1)
    print("▶ 추천 점수(Y값) 생성 완료!")

    # --- 전처리기 생성 ---
    numeric_feats = ['기온값', '습도값', '강수량 값', '풍속값']
    
    # ★★★★★ '시군구명' 피처를 제외하여 차원 축소 ★★★★★
    cat_feats = [
        '기온상태', '습도상태', '강수 유형명', '바람강도 유형명', '광역시도명', 
        # '시군구명', # 피처 수 폭증의 주범이므로 제외
        'weekday', 'is_weekend', 'month', 'season',
        '배달상점 업종명' 
    ]
    
    # 데이터 타입 변환
    for col in numeric_feats:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    # 파이프라인 구성
    numeric_transformer = Pipeline([('imputer', SimpleImputer(strategy='mean')), ('scaler', StandardScaler())])
    categorical_transformer = Pipeline([('imputer', SimpleImputer(strategy='constant', fill_value='missing')), ('onehot', OneHotEncoder(handle_unknown='ignore'))])
    
    preprocessor = ColumnTransformer([
        ('num', numeric_transformer, numeric_feats),
        ('cat', categorical_transformer, cat_feats),
    ], remainder='passthrough') # 나머지 컬럼은 그대로 통과

    all_features = numeric_feats + cat_feats
    return df, preprocessor, all_features

# --- 2. 회귀 모델 학습 함수 ---
def train_regression_model(df, preprocessor, features):
    X = df[features]
    y = df['score'] # ★★★ 정답(y)은 'score' 컬럼 ★★★

    pipe = Pipeline([
        ('pre', preprocessor),
        ('reg', RandomForestRegressor(n_estimators=100, max_depth=10,
                                      min_samples_leaf=10, random_state=42, n_jobs=1))
    ])

    pipe.fit(X, y)
    print("▶ 집계 기반 날씨 참고 점수 학습 완료 (미래 선택/추천 성능 평가는 수행하지 않음)")
    return pipe

# --- 3. 실행부 ---
if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    cli = argparse.ArgumentParser(description="기존 날씨 참고 점수 모델 학습")
    cli.add_argument("--data", type=Path, default=root / "배달_음식추천용_최종데이터_가공05.csv")
    cli.add_argument("--output", type=Path, default=root / "model/weather_food_regression_model3.pkl")
    args = cli.parse_args()
    if not args.data.is_file():
        cli.error(f"학습 CSV를 찾을 수 없습니다: {args.data}")
    filepath = args.data

    df_full, preprocessor, all_features = load_and_prepare_data_for_regression(filepath)
    
    # 메모리 관리를 위해 10% 샘플링 (기존 학습 방식 유지)
    df_sampled = df_full.sample(frac=0.1, random_state=42)
    print(f"\n▶ 메모리 관리를 위해 전체 데이터의 {len(df_sampled)}개만 샘플링하여 사용합니다.")

    model = train_regression_model(df_sampled, preprocessor, all_features)
    
    # ★★★ 이제 LabelEncoder(le)는 필요 없으므로, 모델과 전처리기만 저장 ★★★
    # (주의: 모델 객체에 전처리 파이프라인이 포함되어 있으므로, 모델만 저장하면 됨)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, args.output)
    print(f"\n✅ 회귀 모델이 '{args.output}'에 저장되었습니다.")

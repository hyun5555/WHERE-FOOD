import argparse
from pathlib import Path
import pandas as pd
import numpy as np
import time
from datetime import datetime
from sklearn.model_selection import train_test_split, cross_val_score, GridSearchCV
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import OneHotEncoder, StandardScaler, LabelEncoder
from sklearn.impute import SimpleImputer
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.metrics import classification_report, accuracy_score
import joblib

# --- 1. 데이터 로드 및 "통계 피처" 생성 함수 ---
def load_and_create_stat_features(filepath):
    """
    데이터를 로드하고, 통계 기반의 새로운 피처를 생성하여 반환합니다.
    """
    df = pd.read_csv(filepath, index_col=0, encoding='utf-8')
    df.columns = df.columns.str.strip()

    for col in df.select_dtypes(include=['float64', 'int64']).columns:
        if '주문 건수' in col or 'is_weekend' in col: # 정수형으로 유지할 컬럼
            continue
        df[col] = df[col].astype('float32')

    
    # --- 기본 피처 생성 (기존과 동일) ---
    df['date'] = pd.to_datetime(
    df['년'].astype(float).astype(int).astype(str) + '-' +
    df['월'].astype(float).astype(int).astype(str) + '-' +
    df['일'].astype(float).astype(int).astype(str),
    format='%Y-%m-%d'
    )
    df['weekday'] = df['date'].dt.weekday
    df['is_weekend'] = (df['weekday'] >= 5).astype(int)
    df['month'] = df['date'].dt.month
    def month_to_season(m):
        if m in [12, 1, 2]: return '겨울'
        if m in [3, 4, 5]: return '봄'
        if m in [6, 7, 8]: return '여름'
        return '가을'
    df['season'] = df['month'].apply(month_to_season)
    df['sample_weight'] = pd.to_numeric(df['주문 건수'], errors='coerce').fillna(1)

    # --- ✅ 핵심: 통계 테이블 계산 ---
    print("▶ 통계 피처 생성을 시작합니다...")
    # 각 음식 카테고리별로, 특정 날씨 상태일 때의 주문 비율을 계산
    # 기온
    temp_stats = df.groupby(["배달상점 업종명", "기온상태"])["주문 건수"].sum().unstack(fill_value=0)
    temp_stats_ratio = (temp_stats.div(temp_stats.sum(axis=1), axis=0) * 100).add_prefix('비율_기온_')
    # 습도
    hum_stats = df.groupby(["배달상점 업종명", "습도상태"])["주문 건수"].sum().unstack(fill_value=0)
    hum_stats_ratio = (hum_stats.div(hum_stats.sum(axis=1), axis=0) * 100).add_prefix('비율_습도_')
    # 강수
    rain_stats = df.groupby(["배달상점 업종명", "강수 유형명"])["주문 건수"].sum().unstack(fill_value=0)
    rain_stats_ratio = (rain_stats.div(rain_stats.sum(axis=1), axis=0) * 100).add_prefix('비율_강수_')

    # --- ✅ 핵심: 통계 정보를 원본 데이터에 새로운 피처로 병합 ---
    df = pd.merge(df, temp_stats_ratio, on="배달상점 업종명", how="left")
    df = pd.merge(df, hum_stats_ratio, on="배달상점 업종명", how="left")
    df = pd.merge(df, rain_stats_ratio, on="배달상점 업종명", how="left")
    df.fillna(0, inplace=True) # 병합 후 생긴 NaN 값은 0으로 채움
    print("▶ 통계 피처 생성 및 병합 완료!")

    # --- 전처리기 및 레이블 인코더 생성 (기존과 동일) ---
    # ❗️ 중요: 새로운 통계 피처들을 numeric_feats 리스트에 추가해야 함
    numeric_feats = ['기온값', '습도값', '강수량 값', '풍속값'] + list(temp_stats_ratio.columns) + list(hum_stats_ratio.columns) + list(rain_stats_ratio.columns)
    cat_feats = [
        '기온상태', '습도상태', '강수 유형명', '바람강도 유형명',
        '광역시도명', '시군구명', 'weekday', 'is_weekend', 'month', 'season'
    ]

    for col in ['기온값', '습도값', '강수량 값', '풍속값']:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    numeric_transformer = Pipeline([('imputer', SimpleImputer(strategy='mean')), ('scaler', StandardScaler())])
    categorical_transformer = Pipeline([('imputer', SimpleImputer(strategy='constant', fill_value='Unknown')), ('onehot', OneHotEncoder(handle_unknown='ignore', sparse_output=False))])
    
    preprocessor = ColumnTransformer([
        ('num', numeric_transformer, numeric_feats),
        ('cat', categorical_transformer, cat_feats),
    ])

    le = LabelEncoder()
    df['y'] = le.fit_transform(df['배달상점 업종명'])
    
    
    all_features = numeric_feats + cat_feats
    return df, preprocessor, le, all_features

# --- 2. 학습 함수 (수정) ---
def train_model(df, preprocessor, features): # features 인자 추가
    X = df[features].copy()
    y = df['y']
     
    
    class_counts = df['배달상점 업종명'].value_counts().to_dict()
    
    total_samples = len(df)
    num_classes = len(class_counts)
    
    weights = df['배달상점 업종명'].apply(
        lambda x: total_samples / (num_classes * class_counts[x])
    )
    # ----------------------------------------------------

    pipe = Pipeline([
        ('pre', preprocessor),
        ('clf', RandomForestClassifier(random_state=42)) 
    ])

    param_grid = {
        'clf__n_estimators': [100], 
        'clf__max_depth': [15]
    }
    grid = GridSearchCV(
        pipe, 
        param_grid, 
        cv=2,
        scoring='f1_weighted', 
        n_jobs=1,
        verbose=2
    )

    print("▶ 모델 학습 시작 (샘플 가중치 적용)...")
    grid.fit(X, y, clf__sample_weight=weights)
    print("▶ 모델 학습 완료")
    
    best_model = grid.best_estimator_
    
    
    return best_model

# --- 3. 실행부 (수정) ---
if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    cli = argparse.ArgumentParser(description="기존 날씨 음식 분류 모델 학습")
    cli.add_argument("--data", type=Path, default=root / "배달_음식추천용_최종데이터_가공05.csv")
    cli.add_argument("--output", type=Path, default=root / "model/weather_food_final_model2.pkl")
    args = cli.parse_args()
    if not args.data.is_file():
        cli.error(f"학습 CSV를 찾을 수 없습니다: {args.data}")
    filepath = args.data

    # 1. 데이터 로드 및 피처 생성
    df_full, preprocessor, le, all_features = load_and_create_stat_features(filepath)

    # 2. 새로운 피처로 모델 학습
    df_chicken = df_full[df_full['배달상점 업종명'] == '치킨']
    df_others = df_full[df_full['배달상점 업종명'] != '치킨']
    df_chicken_sampled = df_chicken.sample(frac=0.7, random_state=42)
    df = pd.concat([df_chicken_sampled, df_others])
    df = df.sample(frac=1, random_state=42).reset_index(drop=True) # 데이터 섞기
    
    model = train_model(df, preprocessor, all_features)
    # 3. 저장
    final_classifier = model.named_steps['clf']
    final_preprocessor = model.named_steps['pre']
    
    args.output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump((final_classifier, final_preprocessor, le), args.output)
    
    print(f"\n✅ (분류기+통계피처, 전처리기, 인코더)가 '{args.output}'에 저장되었습니다.")

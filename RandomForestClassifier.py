"""Legacy category classifier, not the candidate-choice RF in scripts/.

Use observable weather/location/calendar inputs only. Target-derived category
statistics are deliberately excluded; existing binary artifacts are not migrated.
"""
import argparse
from pathlib import Path
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import OneHotEncoder, StandardScaler, LabelEncoder
from sklearn.impute import SimpleImputer
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
import joblib

# --- 1. 데이터 로드 및 관측 가능한 피처 생성 ---
def load_and_prepare_data(filepath):
    """
    추론 시에도 알 수 있는 날씨·위치·시간 피처만 반환합니다.
    """
    df = pd.read_csv(filepath, encoding='utf-8')
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
    # Joining statistics by the unknown target leaks its identity into X.
    numeric_feats = ['기온값', '습도값', '강수량 값', '풍속값']
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
def train_model(df, preprocessor, features):
    X = df[features].copy()
    y = df['y']
     
    
    pipe = Pipeline([
        ('pre', preprocessor),
        ('clf', RandomForestClassifier(n_estimators=100, max_depth=15,
                                       class_weight='balanced', random_state=42, n_jobs=1))
    ])
    pipe.fit(X, y)
    print("▶ 과거 카테고리 모델 학습 완료 (별도 평가 없음; 선택 예측 성능 아님)")
    return pipe

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

    # 1. 데이터 로드 및 정답 독립적인 피처 생성
    df_full, preprocessor, le, all_features = load_and_prepare_data(filepath)

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
    
    print(f"\n✅ (분류기, 전처리기, 인코더)가 '{args.output}'에 저장되었습니다. 별도 검증 전 성능을 주장하지 마세요.")

import pandas as pd
import matplotlib.pyplot as plt
from matplotlib import rc
import matplotlib.ticker as mticker
import seaborn as sns


# 한글 폰트 설정 (Windows 기준)
rc("font", family="gulim")

plt.figure(figsize=(10, 4), dpi=600)

# CSV 파일 불러오기
df = pd.read_csv("배달_음식추천용_최종데이터_가공05.csv", encoding='utf-8')
df.columns = df.columns.str.strip()

# 1. 음식 카테고리별로 주문 건수 합계 계산
category_total_orders = df.groupby("배달상점 업종명")["주문 건수"].sum()

# 2. 주문 건수가 많은 순서대로 정렬
category_total_orders_sorted = category_total_orders.sort_values(ascending=False)

print("✅ 음식 카테고리별 전체 주문 건수")
print(category_total_orders_sorted)
print("-" * 50)


# 3. 시각화
plt.figure(figsize=(14, 7))
category_total_orders_sorted.plot(kind='bar', colormap='viridis')

plt.title("음식 카테고리별 전체 주문 건수", fontsize=16)
plt.xlabel("음식 카테고리", fontsize=12)
plt.ylabel("총 주문 건수 (건)", fontsize=12)
plt.xticks(rotation=45, ha='right')

# Y축에 천 단위 콤마(,) 추가 (가독성 향상)
plt.gca().yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, p: format(int(x), ',')))

plt.tight_layout()
plt.show()


# ───────────────────────────────────────────────
# ✅ 기온 상태 비율 분석 (업종 기준 정규화)
# ───────────────────────────────────────────────

# 1. 업종 + 기온상태별 주문 건수
temp_category = df.groupby(["배달상점 업종명", "기온상태"])["주문 건수"].sum().reset_index()

# 2. 업종별 전체 주문 건수
total_orders_by_category = temp_category.groupby("배달상점 업종명")["주문 건수"].sum().reset_index()
total_orders_by_category = total_orders_by_category.rename(columns={"주문 건수": "전체 주문 건수"})

# 3. 병합 및 비율 계산
temp_category = temp_category.merge(total_orders_by_category, on="배달상점 업종명")
temp_category["비율(%)"] = (temp_category["주문 건수"] / temp_category["전체 주문 건수"]) * 100

# 4. 피벗 테이블 생성
pivot_temp_by_category = temp_category.pivot(index="배달상점 업종명", columns="기온상태", values="비율(%)").fillna(0)

print("✅ 음식 카테고리별 기온 상태 비율 (%)")
print(pivot_temp_by_category.round(2))

# 5. 시각화
plt.figure(figsize=(12, 10)) # 히트맵에 맞는 사이즈로 조정
sns.heatmap(
    pivot_temp_by_category, 
    annot=True,          # 각 셀에 숫자(비율) 표시
    fmt=".1f",           # 소수점 첫째 자리까지 표시
    cmap="YlOrRd",        # 색상 맵 지정 (파란색 계열)
    linewidths=.5        # 셀 사이의 간격
)
plt.title("음식 카테고리별 기온상태 비율 분석 (히트맵)", fontsize=16)
plt.xlabel("기온 상태", fontsize=12)
plt.ylabel("음식 카테고리", fontsize=12)
plt.show()


# ───────────────────────────────────────────────
# ✅ 습도 상태 비율 분석 (업종 기준 정규화)
# ───────────────────────────────────────────────

# 1. 업종 + 습도상태별 주문 건수
hum_category = df.groupby(["배달상점 업종명", "습도상태"])["주문 건수"].sum().reset_index()

# 2. 업종별 전체 주문 건수
total_orders_by_category_hum = hum_category.groupby("배달상점 업종명")["주문 건수"].sum().reset_index()
total_orders_by_category_hum = total_orders_by_category_hum.rename(columns={"주문 건수": "전체 주문 건수"})

# 3. 병합 및 비율 계산
hum_category = hum_category.merge(total_orders_by_category_hum, on="배달상점 업종명")
hum_category["비율(%)"] = (hum_category["주문 건수"] / hum_category["전체 주문 건수"]) * 100

# 4. 피벗 테이블 생성
pivot_hum_by_category = hum_category.pivot(index="배달상점 업종명", columns="습도상태", values="비율(%)").fillna(0)

print("\n✅ 음식 카테고리별 습도 상태 비율 (%)")
print(pivot_hum_by_category.round(2))

# 5. 시각화
plt.figure(figsize=(10, 10))  # 히트맵에 적합한 크기로 조정
sns.heatmap(
    pivot_hum_by_category,
    annot=True,           # 각 셀에 숫자 표시
    fmt=".1f",            # 소수점 첫째 자리까지
    cmap="Greens",        # 초록색 계열 색상 맵
    linewidths=.5         # 셀 사이 간격
)
plt.title("음식 카테고리별 습도상태 비율 분석 (히트맵)", fontsize=16)
plt.xlabel("습도 상태", fontsize=12)
plt.ylabel("음식 카테고리", fontsize=12)
plt.show()

# 기온 상태 컬럼 리스트
temp_columns = list(pivot_temp_by_category.columns)

# 각 기온 상태별로 상위 3개 음식 카테고리 출력
for temp in temp_columns:
    print(f"\n=== 기온 상태: {temp} ===")
    sorted_temp = pivot_temp_by_category[[temp]].sort_values(by=temp, ascending=False)
    print(sorted_temp.head(15).round(2))

# 습도 상태 컬럼 리스트
hum_columns = list(pivot_hum_by_category.columns)

# 각 습도 상태별로 상위 3개 음식 카테고리 출력
for hum in hum_columns:
    print(f"\n=== 습도 상태: {hum} ===")
    sorted_hum = pivot_hum_by_category[[hum]].sort_values(by=hum, ascending=False)
    print(sorted_hum.head(15).round(2))
    
# ───────────────────────────────────────────────
# ✅ 강수 유형 비율 분석 (업종 기준 정규화)
# ───────────────────────────────────────────────

# 1. '없음' 강수유형 데이터 제외
rain_category = df[df["강수 유형명"] != "없음"]

# 2. 강수유형 + 업종별 주문 건수 합계
rain_category_grouped = rain_category.groupby(["배달상점 업종명", "강수 유형명"])["주문 건수"].sum().reset_index()

# 3. 업종별 전체 주문 건수 (강수유형 제외 '없음'만)
total_orders_by_category_rain = rain_category_grouped.groupby("배달상점 업종명")["주문 건수"].sum().reset_index()
total_orders_by_category_rain = total_orders_by_category_rain.rename(columns={"주문 건수": "전체 주문 건수"})

# 4. 병합 및 비율 계산
rain_category_grouped = rain_category_grouped.merge(total_orders_by_category_rain, on="배달상점 업종명")
rain_category_grouped["비율(%)"] = (rain_category_grouped["주문 건수"] / rain_category_grouped["전체 주문 건수"]) * 100

# 5. 피벗 테이블 생성 (업종명 x 강수유형)
pivot_rain_by_category = rain_category_grouped.pivot(index="배달상점 업종명", columns="강수 유형명", values="비율(%)").fillna(0)

print("\n✅ 음식 카테고리별 강수 유형 비율 (%) (없음 제외)")
print(pivot_rain_by_category.round(2))

# 6. 시각화
plt.figure(figsize=(10, 10)) # 히트맵에 적합한 크기로 조정
sns.heatmap(
    pivot_rain_by_category,
    annot=True,           # 각 셀에 숫자 표시
    fmt=".1f",            # 소수점 첫째 자리까지
    cmap="Blues",        # 노란색-주황-빨강 계열 색상 맵
    linewidths=.5         # 셀 사이 간격
)
plt.title("음식 카테고리별 강수 유형 비율 분석 (히트맵, 없음 제외)", fontsize=16)
plt.xlabel("강수 유형명", fontsize=12)
plt.ylabel("음식 카테고리", fontsize=12)
plt.show()

# 7. 강수 유형별 상위 15개 음식 카테고리 출력
rain_types = pivot_rain_by_category.columns.tolist()

for rain in rain_types:
    print(f"\n=== 강수 유형명: {rain} ===")
    sorted_rain = pivot_rain_by_category[[rain]].sort_values(by=rain, ascending=False)
    print(sorted_rain.head(15).round(2))

import matplotlib
matplotlib.use("Agg")

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib as mpl
from matplotlib import rc
import matplotlib.ticker as mticker
import seaborn as sns


adf = None
df  = None

def MakeImage(isshow,today_temp,today_humidity,today_rain) :
    global adf
    global df
    
    # 한글 폰트 설정 (Windows 기준)
    rc("font", family="AppleGothic")
    mpl.rc('font', family='AppleGothic')
    

    if df is None :
        print("df 로딩....")
        df = pd.read_csv("배달_음식추천용_최종데이터_가공05.csv", encoding='utf-8')
        df.columns = df.columns.str.strip()
        
    # CSV 파일 불러오기
    if adf is None :
        print("adf 로딩....")
        today_weather_df = df[
            (df['습도상태'] == today_humidity) &
            (df['기온상태'] == today_temp) &
            (df['강수 유형명'] == today_rain)
        ].copy()
        print("오늘의 날씨 : ", today_weather_df)
        
        # 1. 음식 카테고리별로 주문 건수 합계 계산
        category_total_orders = today_weather_df.groupby("배달상점 업종명")["주문 건수"].sum()
        
        # 2. 주문 건수가 많은 순서대로 정렬
        category_total_orders_sorted = category_total_orders.sort_values(ascending=False)
        
        print("✅ 음식 카테고리별 전체 주문 건수")
        print(category_total_orders_sorted)
        print("-" * 50)
        
        
        #=======================================================================================
        print("--/"*30)
        print("@@@@@@@@@@@@@@@@")
        #adf = df.groupby(["배달상점 업종명", "습도상태", "기온상태", "강수 유형명", "바람 유형명"])["주문 건수"].sum().reset_index()
        #print(adf,"-"*30)
        #print(adf.columns,"-"*30)
        
    
    
    #======================================================================================
    import numpy as np
    import squarify  # <<< [변경] 트리맵 라이브러리 import
    
    print("matplotlib load")
    # -------------------------------------------
    # 한글 폰트 설정 (Windows 환경 기준)
    # -------------------------------------------
    mpl.rc('font', family='Malgun Gothic')
    mpl.rc('axes', unicode_minus=False)
    
    # --------------------------------------------------------------------------
    # 1. 오늘의 날씨 조건 정의 및 데이터 필터링/정렬

    
    # 만약 필터링된 데이터가 없다면 메시지를 출력하고 종료
    if category_total_orders_sorted.empty:
        print(f"'{today_humidity}', '{today_temp}', '{today_rain}' 조건에 맞는 데이터가 없습니다.")
    else:
      
        # ▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼ [수정된 부분] ▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼▼
        # 2. 트리맵 시각화
        plt.figure(figsize=(16, 9))
        
        # 데이터 준비
        sizes = category_total_orders_sorted.values
        total_orders = sum(sizes)
        labels = [
            f"{name}\n({count:,}건)\n({count/total_orders*100:.1f}%)"
            for name, count in zip(category_total_orders_sorted.index, sizes)
        ]
        
        # [수정] 따뜻한 색 계열의 컬러맵('Oranges')으로 변경
        # np.linspace의 범위를 0.2 ~ 0.8로 조정하여 너무 밝거나 어두운 색을 피해 시인성을 높입니다.
        cmap = plt.get_cmap('Oranges')
        colors = cmap(np.linspace(0.2, 0.8, len(sizes)))
        
        # 트리맵 생성
        squarify.plot(sizes=sizes,
                      label=labels,
                      color=colors,
                      alpha=0.8,
                      text_kwargs={'fontsize': 10})
        
        # 그래프 제목 설정
        if today_rain == "없음" : today_rain = "비 없음"
        title_text = f"오늘의 날씨({today_humidity}, 기온 {today_temp}, {today_rain}) 따른 음식 선호도"
        plt.title(title_text, fontsize=20, pad=20)
        
        # 축 정보 숨기기
        plt.axis('off')
        
        plt.savefig("./static/images/result.png")
        plt.close()
        
        if isshow:
            pass

        #if isshow == True :
        #    plt.show()

"""
today_temp="보통"
today_humidity="매우 습함"
today_rain="약한 비"
today_wind="보통"
MakeImage(True,today_temp,today_humidity,today_rain)
"""

import joblib

# 확인할 pkl 파일 경로
# 실제 파일 이름이 weather_food_final_model.pkl 이 맞는지 다시 한번 확인해주세요.
file_path = './model/weather_food_final_model.pkl'

print(f"--- '{file_path}' 파일 내용물 분석 시작 ---")

try:
    # 파일을 로드합니다.
    loaded_data = joblib.load(file_path)

    # 로드된 데이터의 타입을 확인합니다.
    print(f"\n1. 전체 데이터 타입: {type(loaded_data)}")

    # 로드된 데이터가 튜플이나 리스트인지 확인하고, 그 안의 객체 수를 확인합니다.
    if isinstance(loaded_data, (list, tuple)):
        print(f"2. 저장된 객체의 수: {len(loaded_data)}")
        
        # 각 객체의 타입을 순서대로 출력합니다.
        print("\n3. 각 객체의 타입 분석:")
        for i, item in enumerate(loaded_data):
            print(f"   - 객체 #{i+1}: {type(item)}")
            
            # 만약 객체가 scikit-learn 파이프라인이라면, 그 내부 구조도 보여줍니다.
            if hasattr(item, 'named_steps'):
                print(f"     -> 이 객체는 Pipeline이며, 내부 단계는 다음과 같습니다: {list(item.named_steps.keys())}")

    else:
        # 튜플이나 리스트가 아닌 단일 객체일 경우
        print("2. 저장된 객체의 수: 1개")
        print("\n3. 객체 타입 분석:")
        print(f"   - 단일 객체: {type(loaded_data)}")
        if hasattr(loaded_data, 'named_steps'):
            print(f"     -> 이 객체는 Pipeline이며, 내부 단계는 다음과 같습니다: {list(loaded_data.named_steps.keys())}")


except Exception as e:
    print(f"\n파일 로드 또는 분석 중 오류 발생: {e}")

print("\n--- 분석 완료 ---")
window.addEventListener('DOMContentLoaded', () => {
    if (typeof kakao !== 'undefined' && kakao.maps?.services) {
        initMap();
    } else {
        document.getElementById('map').textContent = '지도를 불러오지 못했습니다. 식당 목록과 상세 링크를 이용해주세요.';
    }
    if (!navigator.geolocation) {
        onError();
        return;
    }
    navigator.geolocation.getCurrentPosition(
        position => updateAllDataForLocation(position.coords.latitude, position.coords.longitude),
        onError, {enableHighAccuracy: false, timeout: 15000, maximumAge: 300000}
    );
});

function onError() {
    document.getElementById('loading').textContent = '현재 위치를 확인하지 못했습니다. 추천 문장에 “강남역에서”처럼 장소를 적어주세요.';
}

async function updateAllDataForLocation(lat, lon) {
    userPosition = {lat: Number(lat), lon: Number(lon)};
    const version = ++locationVersion;
    invalidateRecommendations();
    if (map) moveMainMarker(new kakao.maps.LatLng(userPosition.lat, userPosition.lon));
    const loading = document.getElementById('loading');
    document.getElementById('weather-info').hidden = true;
    document.getElementById('recommendation-section').hidden = true;
    loading.style.display = 'block';
    loading.textContent = '선택한 위치의 날씨를 확인하고 있어요…';
    try {
        const response = await fetch('/get-initial-data', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(userPosition)
        });
        const data = await response.json();
        if (version !== locationVersion) return;
        if (!response.ok) throw new Error(data.error || '날씨를 확인하지 못했습니다.');
        updateWeatherUI(data.weather, data.location);
        updateRecommendationUI(data.recommendations);
    } catch (error) {
        if (version === locationVersion) loading.textContent = error.message;
    }
}

function searchLocation() {
    const keyword = document.getElementById('location-search-input').value.trim();
    if (!keyword) return;
    if (!ps) {
        invalidateRecommendations({discardDraft: true});
        document.getElementById('meal-query').value = keyword + '에서 식당 추천해줘';
        document.getElementById('meal-query').focus();
        return;
    }
    ps.keywordSearch(keyword, (places, status) => {
        if (status !== kakao.maps.services.Status.OK) {
            document.getElementById('loading').textContent = '장소를 찾지 못했습니다. 더 구체적인 주소를 입력해주세요.';
            return;
        }
        if (places.length > 1) {
            const container = document.getElementById('location-options');
            container.replaceChildren();
            places.slice(0, 5).forEach(place => {
                const button = node('button', place.place_name + ' · ' + place.address_name, 'choice-button');
                button.type = 'button';
                button.addEventListener('click', () => updateAllDataForLocation(place.y, place.x));
                container.appendChild(button);
            });
            document.getElementById('recommendation-status').textContent = '검색 기준 장소를 선택해주세요.';
            return;
        }
        updateAllDataForLocation(places[0].y, places[0].x);
    });
}

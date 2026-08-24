//페이지 시작, 위치 조회, 전체 데이터 호출 담당

window.addEventListener('DOMContentLoaded', () => {
    if (typeof kakao === 'undefined') {
        document.getElementById('loading').innerHTML = '<p>지도 서비스를 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>';
        return;
    }

    const mapContainer = document.getElementById('map');
    const mapOption = { center: new kakao.maps.LatLng(37.566826, 126.9786567), level: 5 }; // 기본 위치: 서울시청
    
    map = new kakao.maps.Map(mapContainer, mapOption);
    ps = new kakao.maps.services.Places(); 
    
    navigator.geolocation.getCurrentPosition(
        onSuccess,
        onError,
        {
            enableHighAccuracy: false,   // Mac에서는 false가 더 안정적
            timeout: 15000,              // 15초 후 실패 처리
            maximumAge: 300000           // 5분 이내 캐시 위치 허용
        }
    );
});


async function onSuccess(position) {
    console.log("위치 조회 성공");
    console.log(position.coords);

    updateAllDataForLocation(
        position.coords.latitude,
        position.coords.longitude
    );
}


function onError(error) {
    console.error("===== 위치 오류 =====");
    console.error("code :", error.code);
    console.error("message :", error.message);
    console.error(error);

    let message = "위치 정보를 가져올 수 없습니다.";

    if (error.code === error.PERMISSION_DENIED) {

        message = "위치 권한이 거부되었습니다.";

    } else if (error.code === error.POSITION_UNAVAILABLE) {

        message = "현재 Wi-Fi에서 위치를 찾을 수 없습니다.";

    } else if (error.code === error.TIMEOUT) {

        message = "위치 조회 시간이 초과되었습니다.";

    }

    document.getElementById("loading").innerHTML = `
        <p class="text-danger">${message}</p>
        <button class="btn btn-light mt-2"
                onclick="location.reload()">
            다시 시도
        </button>
    `;
}


async function updateAllDataForLocation(lat, lon) {
    userPosition = new kakao.maps.LatLng(lat, lon);

    const loadingEl = document.getElementById('loading');
    document.getElementById('weather-info').hidden = true;
    loadingEl.style.display = 'block';
    loadingEl.innerHTML = `<div class="spinner-border text-primary" role="status"></div><p class="mt-2">새로운 위치의 정보를 가져오는 중...</p>`;
    
    moveMainMarker(userPosition);
    
    document.getElementById('map-and-list-section').hidden = true;
    removeMarkers();

    try {
        const response = await fetch('/get-initial-data', { 
            method: 'POST', 
            headers: { 'Content-Type': 'application/json' }, 
            body: JSON.stringify({ lat, lon }) 
        });
        if (!response.ok) throw new Error('서버에서 데이터를 가져오는 데 실패했습니다.');
        
        const data = await response.json();
        
        updateWeatherUI(data.weather, data.location);
        updateRecommendationUI(data.recommendations);

        //분석결과 이미지를 출력한다.
        rand=Math.random();
        document.getElementById("resultImage").innerHTML = "<img class='resultimg' src='/static/images/" + data.image + "?rand=" + rand + "'>";


    } catch (error) {
        loadingEl.innerHTML = `<p class="text-danger">${error.message}</p>`;
    }
}


function searchLocation() {
    const keyword = document.getElementById('location-search-input').value;
    if (!keyword.trim()) {
        alert("검색할 장소를 입력해주세요.");
        return;
    }
    ps.keywordSearch(keyword, (data, status) => {
        if (status === kakao.maps.services.Status.OK) {
            const place = data[0];
            const lat = place.y;
            const lon = place.x;
            updateAllDataForLocation(lat, lon); // ★ 핵심 함수 호출
        } else if (status === kakao.maps.services.Status.ZERO_RESULT) {
            alert('검색 결과가 존재하지 않습니다.');
        } else {
            alert('장소 검색 중 오류가 발생했습니다.');
        }
    });
}

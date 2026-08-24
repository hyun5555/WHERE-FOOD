//맛집 검색, 리스트 출력, 정렬 담당

// ❗️ 새로운 맛집 검색 및 표시 함수
async function searchAndDisplayPlaces(keyword) {
    // 1. 맛집 지도 및 리스트 섹션을 화면에 표시하고 UI를 초기 상태로 설정합니다.
    document.getElementById('map-and-list-section').hidden = false;
    document.getElementById('map-title').textContent = `주변 '${keyword}' 맛집 지도 🗺️`;
    document.getElementById('sort-buttons').hidden = false;
    setActiveSortButton('accuracy'); // 기본 정렬 버튼 활성화

    // 2. 검색 결과를 보여줄 리스트 영역에 로딩 스피너를 표시합니다.
    const resultsListEl = document.getElementById('search-results-list');
    resultsListEl.innerHTML = `
        <div class="d-flex justify-content-center mt-3">
            <div class="spinner-border text-primary" role="status"></div>
            <p class="ms-2 mb-0">맛집 정보 로딩 중...</p>
        </div>`;

    // 2. [핵심] 캐시 키에 '위치 정보'를 추가합니다.
    // 현재 사용자의 위도와 경도
    const currentLat = userPosition.getLat();
    const currentLon = userPosition.getLng();

    const locationKey = `${currentLat.toFixed(3)}_${currentLon.toFixed(3)}`;

    // 최종 캐시 키 = "places_음식카테고리_위치정보" (예: 'places_치킨_37.498_127.027')
    const cacheKey = `places_${keyword}_${locationKey}`;
    
    //고유한 캐시 키로 데이터확인
    const cachedData = sessionStorage.getItem(cacheKey);

    if (cachedData) {
        //캐시가 있는 경우 (Cache Hit)
        console.log(`[Cache Hit] '${cacheKey}'에 대한 캐시된 데이터를 사용합니다.`);
        
        const places = JSON.parse(cachedData);
        
        originalPlaces = [...places];
        currentPlaces = [...places];
        
        displayPlaces(currentPlaces);
        setTimeout(() => map.relayout(), 0);
        
        return; // API 호출 없이 함수 종료
    }

    // 캐시가 없는 경우 (Cache Miss)
    console.log(`[Cache Miss] '${cacheKey}'에 대한 데이터를 서버에서 가져옵니다.`);
    try {
        // API 호출 시에는 정확한 위도/경도를 사용합니다.
        const response = await fetch('/search-places', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                keyword: keyword,
                lat: currentLat, // 정확한 위도
                lon: currentLon  // 정확한 경도
            })
        });

        if (!response.ok) {
            throw new Error(`맛집 검색 서버 응답 오류: ${response.status}`);
        }
        
        const places = await response.json();

        //캐시 키로 저장
        sessionStorage.setItem(cacheKey, JSON.stringify(places));
        console.log(`'${cacheKey}'에 대한 데이터를 캐시에 저장했습니다.`);

        originalPlaces = [...places];
        currentPlaces = [...places];

        displayPlaces(currentPlaces);
        setTimeout(() => map.relayout(), 0);

    } catch (error) {
        console.error('맛집 검색 중 오류 발생:', error);
        resultsListEl.innerHTML = `<p class="text-danger text-center mt-3">${error.message}</p>`;
    }
}

//정렬 버튼 클릭 시 호출되는 함수
function resortPlaces(sortBy) {
    setActiveSortButton(sortBy);
        if (!originalPlaces || originalPlaces.length === 0) return;

        let sortedPlaces = [...originalPlaces]; 

        if (sortBy === 'distance') {
            // 거리 오름차순 (가까운 순)
            sortedPlaces.sort((a, b) => a.distance - b.distance);
        } else if (sortBy === 'rating') {
            // 평점 내림차순 (높은 순), 평점이 같으면 리뷰 수 많은 순
            sortedPlaces.sort((a, b) => {
                if (b.rating !== a.rating) return b.rating - a.rating;
                return b.review_count - a.review_count;
            });
        }
    
    currentPlaces = sortedPlaces;
    displayPlaces(sortedPlaces);
}


//지도와 리스트를 한 번에 표시하는 통합 함수
function displayPlaces(places) {
    displayPlacesOnMap(places);
    displayPlacesOnList(places);
}


 // 리스트에 맛집 정보 표시 (평점 표시 기능 추가)
function displayPlacesOnList(places) {
    const listEl = document.getElementById('search-results-list');
    listEl.innerHTML = '<ul class="list-group"></ul>';
    const ulEl = listEl.querySelector('ul');

    if (places.length === 0) {
        listEl.innerHTML = `<p class="text-muted text-center mt-3">검색 결과가 없습니다.</p>`;
        return;
    }

    places.slice(0, 5).forEach((place, i) => { // 최대 5개 표시
        const itemEl = document.createElement('li');
        itemEl.className = 'list-group-item';

        let ratingHtml = place.rating > 0 
            ? `<p class="mb-1"><span class="badge bg-warning text-dark">⭐ ${place.rating.toFixed(1)}</span> <span class="text-muted">리뷰 ${place.review_count}</span></p>`
            : '<p class="mb-1"><span class="text-muted">평점 정보 없음</span></p>';
        
        let distanceHtml = place.distance 
            ? `<p class="mb-1 text-primary"><small>현재 위치에서 ${place.distance}m</small></p>`
            : '';

        itemEl.innerHTML = `
            <h6 class="mb-1 fw-bold">${i + 1}. ${place.place_name}</h6>
            ${ratingHtml}
            <p class="mb-1"><small>${place.road_address_name || place.address_name}</small></p>
            ${distanceHtml}
            <a href="${place.place_url}" target="_blank" class="btn btn-sm btn-outline-primary" id="restaurant-info">상세보기</a>
            <a href="https://map.kakao.com/link/to/${place.id}" target="_blank" class="btn btn-sm btn-outline-primary">길찾기</a>
        `;
        ulEl.appendChild(itemEl);
    });
}


// 활성 버튼 스타일 변경
function setActiveSortButton(sortBy) {
    document.querySelectorAll('#sort-buttons button').forEach(btn => btn.classList.remove('active'));
    if (sortBy === 'distance') document.querySelector('#sort-buttons button:nth-child(2)').classList.add('active');
    else if (sortBy === 'rating') document.querySelector('#sort-buttons button:nth-child(3)').classList.add('active');
    else document.querySelector('#sort-buttons button:nth-child(1)').classList.add('active');
}


function showSinglePlaceOnList(place) {
    const listEl = document.getElementById('search-results-list');
    
    // 단일 항목을 표시할 HTML 생성
    let ratingHtml = place.rating > 0 ? `<p class="mb-1"><span class="badge bg-warning text-dark">⭐ ${place.rating.toFixed(1)}</span> <span class="text-muted">리뷰 ${place.review_count}</span></p>` : '<p class="mb-1"><span class="text-muted">평점 정보 없음</span></p>';
    let distanceHtml = place.distance ? `<p class="mb-1 text-primary"><small>현재 위치에서 ${place.distance}m</small></p>` : '';
    
    const singleItemHtml = `
        <ul class="list-group">
            <li class="list-group-item active"> <!-- active 클래스로 하이라이트 -->
                <h6 class="mb-1 fw-bold">${place.place_name}</h6>
                ${ratingHtml}
                <p class="mb-1"><small>${place.road_address_name || place.address_name}</small></p>
                ${distanceHtml}
                <a href="${place.place_url}" target="_blank" class="btn btn-sm btn-outline-secondary">상세보기</a>
                <a href="https://map.kakao.com/link/to/${place.id}" target="_blank" class="btn btn-sm btn-outline-primary">길찾기</a>
            </li>
        </ul>
    `;
    
    const backButtonHtml = `<div class="d-grid mt-2"><button class="btn btn-outline-primary" onclick="displayPlacesOnList(currentPlaces.slice(0, 5))">전체 목록으로 돌아가기</button></div>`;
    
    listEl.innerHTML = singleItemHtml + backButtonHtml;
}

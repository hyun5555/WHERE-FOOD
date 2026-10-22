//카카오 지도와 마커 관련 함수

function initMap(checkMap = false) {
    const mapContainer = document.getElementById('map');
    const mapOption = {
        center: new kakao.maps.LatLng(37.566826, 126.9786567),
        level: 5
    };

    map = new kakao.maps.Map(mapContainer, mapOption);
    ps = new kakao.maps.services.Places();
    if (checkMap) {
        mapContainer.setAttribute('data-map-state', 'waiting-for-tiles');
        kakao.maps.event.addListener(map, 'tilesloaded', () => {
            mapContainer.setAttribute('data-map-state', 'tiles-loaded');
            document.getElementById('map-check-status').textContent = '지도 SDK의 타일 로드 이벤트를 확인했습니다. 실제 지도 표시·확대·이동도 화면에서 확인해주세요.';
        });
        map.relayout();
    }
}


function moveMainMarker(position) {
    if (!mainMarker) { 
        mainMarker = new kakao.maps.Marker({
            position: position,
            draggable: true 
        });
        mainMarker.setMap(map);

        kakao.maps.event.addListener(mainMarker, 'dragend', function() {
            const newPosition = mainMarker.getPosition();
            updateAllDataForLocation(newPosition.getLat(), newPosition.getLng()); // ★ 핵심 함수 호출
        });
    }
    mainMarker.setPosition(position); 
    map.setCenter(position); 
}


function displayPlacesOnMap(places) {
    // 1. 이전 맛집 마커들을 제거합니다. (메인 마커는 남겨둠)
    removeMarkers(); 
    const bounds = new kakao.maps.LatLngBounds();
    
    bounds.extend(mainMarker.getPosition()); 
    
    places.forEach((place, i) => {
        addMarker(place, i);
        bounds.extend(new kakao.maps.LatLng(place.y, place.x));
    });
    
    if (places.length > 0) {
        map.setBounds(bounds);
    }
    
}

function addMarker(place, idx) {
    const placePosition = new kakao.maps.LatLng(place.y, place.x);
    
    const imageSrc = 'https://t1.daumcdn.net/localimg/localimages/07/mapapidoc/marker_number_blue.png';
    const imageSize = new kakao.maps.Size(36, 37);
    const imgOptions = {
        spriteSize: new kakao.maps.Size(36, 691),
        spriteOrigin: new kakao.maps.Point(0, (idx * 46) + 10),
        offset: new kakao.maps.Point(13, 37)
    };
    const markerImage = new kakao.maps.MarkerImage(imageSrc, imageSize, imgOptions);
    const marker = new kakao.maps.Marker({
        position: placePosition,
        image: markerImage,
        title: place.place_name 
    });
    
    kakao.maps.event.addListener(marker, 'click', function() {
        showSinglePlaceOnList(place);
    });
    
    marker.setMap(map);
    markers.push(marker);
    return marker;
}


function removeMarkers() {
    for (let i = 0; i < markers.length; i++) {
        markers[i].setMap(null);
    }   
    markers = [];
}

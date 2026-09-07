// All user/provider text is rendered as text nodes; URLs are restricted to HTTP(S).
function node(tag, text, className = '') {
    const element = document.createElement(tag);
    element.textContent = text;
    element.className = className;
    return element;
}

function externalLink(label, url) {
    const link = node('a', label);
    try {
        const parsed = new URL(url);
        if (!['https:', 'http:'].includes(parsed.protocol)) throw new Error();
        link.href = parsed.href;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
    } catch {
        link.removeAttribute('href');
    }
    return link;
}

const constraintLabels = {
    location_text: '장소', walking_minutes_max: '도보 상한(분)',
    max_distance_m: '직선거리 상한(m)', budget_krw: '1인 예산(원)',
    excluded_ingredients: '제외 재료', allergens: '알레르기',
    excluded_foods: '제외 음식·맛', dish_tags: '음식 선호', atmosphere_tags: '분위기 선호'
};

function renderDecisionResults(result) {
    document.getElementById('recommendation-status').textContent = result.message;
    const constraints = document.getElementById('parsed-constraints');
    Object.entries(constraintLabels).forEach(([key, label]) => {
        const value = result.constraints[key];
        if (value === null || value === undefined || (Array.isArray(value) && !value.length)) return;
        const required = result.constraints.hard_fields?.includes(key) ? ' · 필수' : '';
        constraints.appendChild(node('span', label + required + ': ' + (Array.isArray(value) ? value.join(', ') : value), 'constraint-chip'));
    });
    result.location_options.forEach(option => {
        const button = node('button', option.name + ' · ' + option.address, 'choice-button');
        button.type = 'button';
        button.addEventListener('click', () => submitRecommendation(option.id));
        document.getElementById('location-options').appendChild(button);
    });
    if (!result.recommendations.length) {
        const rejected = Object.entries(result.diagnostics?.rejected || {});
        if (rejected.length) {
            const list = document.createElement('ul');
            rejected.forEach(([reason, count]) => list.appendChild(node('li', reason + ' (' + count + '개 후보)')));
            document.getElementById('location-options').appendChild(list);
        }
        return;
    }
    document.getElementById('map-and-list-section').hidden = false;
    document.getElementById('map-title').textContent = result.origin.name + ' 주변 추천';
    document.getElementById('decision-notice').textContent = result.notice || '';
    displayPlacesOnList(result.recommendations);
    if (map && result.origin) {
        moveMainMarker(new kakao.maps.LatLng(result.origin.lat, result.origin.lon));
        map.relayout();
        displayPlacesOnMap(result.recommendations);
    }
}

function sourceNode(source) {
    const row = node('p', '', 'source-row');
    row.appendChild(externalLink(source.title, source.url));
    row.appendChild(node('small', ' · 근거 기준 ' + (source.observed_on || source.observed_at?.slice(0, 10) || '미확인')));
    if (source.excerpt) row.appendChild(node('span', ' — ' + source.excerpt));
    return row;
}

function displayPlacesOnList(places) {
    const list = document.getElementById('search-results-list');
    list.replaceChildren();
    const requestId = currentRequestId;
    const version = recommendationVersion;
    places.forEach(place => {
        const card = node('article', '', 'decision-card');
        card.id = 'place-' + place.id;
        card.appendChild(node('h3', place.rank + '위 · ' + place.place_name));
        card.appendChild(node('p', place.menu.name + ' · ' + place.menu.price_krw.toLocaleString('ko-KR') + '원', 'decision-menu'));
        card.appendChild(node('p', place.road_address_name || place.address_name));
        card.appendChild(node('p', place.route
            ? '경로 기준 예상 도보 ' + Math.ceil(place.route.seconds / 60) + '분 · ' + Math.round(place.route.distance_m) + 'm'
            : '직선거리 ' + Math.round(place.distance) + 'm · 도보 시간 미확인'));
        card.appendChild(sourceNode(place.menu.source));
        card.appendChild(sourceNode(place.place_source));
        if (place.route) card.appendChild(sourceNode({
            title: '카카오 도보 경로', url: place.route.source_url, observed_at: place.route.observed_at
        }));
        const matches = document.createElement('ul');
        place.matches.forEach(match => {
            const item = node('li', match.text);
            item.appendChild(sourceNode(match.source));
            matches.appendChild(item);
        });
        card.appendChild(matches);
        place.unknown.forEach(text => card.appendChild(node('p', text, 'text-muted')));
        const actions = node('div', '', 'decision-actions');
        const feedback = node('p', '', 'feedback-status');
        feedback.setAttribute('role', 'status');
        ['restaurant_selected', 'restaurant_rejected'].forEach(type => {
            const button = node('button', type === 'restaurant_selected' ? '이 식당 선택' : '추천 제외', 'choice-button');
            button.type = 'button';
            const eventId = crypto.randomUUID();
            button.addEventListener('click', async () => {
                button.disabled = true;
                try {
                    await sendEvent(type, place.id, requestId, eventId);
                    if (version !== recommendationVersion) return;
                    feedback.textContent = type === 'restaurant_selected' ? '선택을 저장했어요. 예약·주문은 별도로 진행해주세요.' : '제외 의견을 저장했어요.';
                } catch {
                    button.disabled = false;
                    feedback.textContent = '저장하지 못했습니다. 버튼을 다시 눌러주세요.';
                }
            });
            actions.appendChild(button);
        });
        [['상세보기', place.place_url, 'detail_clicked'],
         ['길찾기', place.route?.source_url || ('https://map.kakao.com/link/to/' + place.id), 'directions_clicked']]
            .forEach(([label, url, type]) => {
                const link = externalLink(label, url);
                link.addEventListener('click', () => sendEvent(type, place.id, requestId).catch(() => showEventError(version)));
                actions.appendChild(link);
            });
        card.appendChild(actions);
        card.appendChild(feedback);
        list.appendChild(card);
    });
}

function showSinglePlaceOnList(place) {
    document.getElementById('place-' + place.id)?.scrollIntoView({behavior: 'smooth', block: 'center'});
}

async function sendEvent(type, placeId = null, requestId = currentRequestId, eventId = crypto.randomUUID()) {
    const response = await fetch('/api/events', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, keepalive: true,
        body: JSON.stringify({id: eventId, request_id: requestId, event_type: type, place_id: placeId})
    });
    if (!response.ok) throw new Error('이벤트 저장 실패');
}

function showEventError(version) {
    if (version === recommendationVersion) document.getElementById('event-status').textContent = '일부 행동 기록을 저장하지 못했습니다.';
}

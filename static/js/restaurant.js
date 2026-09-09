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
    excluded_foods: '제외 음식·맛', dish_tags: '음식 선호', atmosphere_tags: '분위기 선호',
    dietary_requirements: '필수 식단', open_now: '현재 영업 필수'
};

function renderDecisionResults(result) {
    document.getElementById('recommendation-status').textContent = result.message;
    const constraints = document.getElementById('parsed-constraints');
    Object.entries(constraintLabels).forEach(([key, label]) => {
        const value = result.constraints[key];
        if (value === null || value === undefined || value === false || (Array.isArray(value) && !value.length)) return;
        const required = result.constraints.hard_fields?.includes(key) ? ' · 필수' : '';
        const diets = {vegan: '비건', vegetarian: '락토오보 채식(달걀·유제품 허용)', pescatarian: '페스코'};
        const shown = key === 'dietary_requirements' ? value.map(diet => diets[diet] || diet).join(', ')
            : key === 'open_now' ? '예' : Array.isArray(value) ? value.join(', ') : value;
        constraints.appendChild(node('span', label + required + ': ' + shown, 'constraint-chip'));
    });
    result.location_options.forEach(option => {
        const button = node('button', option.name + ' · ' + option.address, 'choice-button');
        button.type = 'button';
        button.addEventListener('click', () => submitRecommendation(option.id));
        document.getElementById('location-options').appendChild(button);
    });
    const details = result.diagnostics?.rejections;
    if (details?.length) {
        const container = document.getElementById('location-options');
        container.appendChild(node('h4', '추천에서 제외한 이유'));
        container.appendChild(node('p', '검사 사유 건수이며 식당 수가 아닙니다. 메뉴별 사유와 메뉴 자료가 없는 장소를 집계합니다. 한 메뉴에 여러 사유가 있을 수 있고, 앞 단계에서 제외되면 뒤 조건은 검사하지 않습니다.', 'text-muted'));
        const categories = {constraint_mismatch: '조건 불충족', missing_evidence: '근거 부족', expired_evidence: '자료 만료'};
        Object.entries(categories).forEach(([category, label]) => {
            const reasons = details.filter(reason => reason.category === category);
            if (!reasons.length) return;
            const section = node('details', '');
            section.appendChild(node('summary', label + ' · ' + reasons.length + '건'));
            const messages = new Map();
            reasons.forEach(reason => messages.set(reason.message, (messages.get(reason.message) || 0) + 1));
            const list = document.createElement('ul');
            messages.forEach((count, message) => list.appendChild(node('li', message + ' · ' + count + '건')));
            section.appendChild(list);
            container.appendChild(section);
        });
        container.appendChild(node('p', '근거 부족·자료 만료는 조건 불충족을 뜻하지 않습니다. 필수 조건은 자동 완화하지 않으며, 알레르기는 근거 없이 통과시키지 않습니다.', 'text-muted'));
    } else if (!result.recommendations.length) {
        const rejected = Object.entries(result.diagnostics?.rejected || {});
        if (rejected.length) {
            const list = document.createElement('ul');
            rejected.forEach(([reason, count]) => list.appendChild(node('li', reason + ' (' + count + '건 · 검사 사유)')));
            document.getElementById('location-options').appendChild(list);
        }
    }
    if (!result.recommendations.length) return;
    document.getElementById('map-and-list-section').hidden = false;
    document.getElementById('map-title').textContent = result.origin.name + ' 주변 추천';
    document.getElementById('decision-notice').textContent = result.notice || '';
    displayPlacesOnList(result.recommendations, result.weather_context);
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

function displayPlacesOnList(places, weatherContext) {
    const list = document.getElementById('search-results-list');
    list.replaceChildren();
    const requestId = currentRequestId;
    const version = recommendationVersion;
    places.forEach(place => {
        const card = node('article', '', 'decision-card');
        card.id = 'place-' + place.id;
        card.appendChild(node('h3', place.rank + '위 · ' + place.place_name));
        card.appendChild(node('p', place.menu.name + ' · ' + place.menu.price_krw.toLocaleString('ko-KR') + '원', 'decision-menu'));
        const explanation = place.explanation;
        if (explanation?.method === 'qwen_grounded') {
            card.appendChild(node('h4', 'Qwen 근거 요약'));
            explanation.sentences.forEach(sentence => {
                const source = explanation.sources.find(s => s.source_id === sentence.source_id);
                if (!source) return;
                card.appendChild(node('p', sentence.text));
                card.appendChild(sourceNode(source));
            });
        } else if (explanation?.method === 'template') {
            card.appendChild(node('p', 'AI 요약을 사용하지 못해 기존 근거 설명을 표시합니다.', 'text-muted'));
        }
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
        if (place.unknown.length) card.appendChild(node('h4', '선택적 선호 미확인 · 추천 제외 사유 아님'));
        place.unknown.forEach(text => card.appendChild(node('p', text, 'text-muted')));
        const opening = place.opening_status;
        card.appendChild(node('p', opening
            ? (opening.is_open ? '영업 중 확인' : '영업하지 않음 확인') + ' · 확인 ' + opening.observed_at + ' · 유효 ' + opening.valid_until
            : '현재 영업 여부 미확인', 'text-muted'));
        if (opening) card.appendChild(sourceNode(opening.evidence));
        const score = place.score_breakdown;
        if (score) {
            card.appendChild(node('p', '선호 일치 ' + score.soft_matches + '개 · 근거 항목 ' +
                Math.round(score.evidence_completeness * 100) + '% · 사용 근거 최대 경과 ' + score.evidence_age_days + '일', 'text-muted'));
            card.appendChild(node('p', score.weather_score == null ? '날씨 참고 점수 미확인 · 정렬 미적용'
                : '날씨 참고 점수 ' + score.weather_score + ' (선택 확률 아님) · ' + (score.weather_applied ? '동점 결정 적용' : '동점 결정 미적용'), 'text-muted'));
            if (score.weather_score != null && weatherContext?.source) {
                card.appendChild(sourceNode({...weatherContext.source, observed_at: weatherContext.observed_at}));
                card.appendChild(node('small', '날씨 관측 시각: ' + weatherContext.observed_at));
            }
        }
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

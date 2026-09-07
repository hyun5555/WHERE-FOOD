function invalidateRecommendations() {
    recommendationVersion += 1;
    recommendationController?.abort();
    recommendationController = null;
    currentRequestId = null;
    currentPlaces = [];
    document.getElementById('recommend-submit').disabled = false;
    document.getElementById('recommendation-form').setAttribute('aria-busy', 'false');
    document.getElementById('map-and-list-section').hidden = true;
    document.getElementById('search-results-list').replaceChildren();
    document.getElementById('parsed-constraints').replaceChildren();
    document.getElementById('location-options').replaceChildren();
    document.getElementById('recommendation-status').textContent = '';
    document.getElementById('event-status').textContent = '';
    removeMarkers();
}

async function submitRecommendation(originPlaceId = null) {
    const query = document.getElementById('meal-query').value.trim();
    if (!query) return;
    invalidateRecommendations();
    const version = recommendationVersion;
    const controller = new AbortController();
    recommendationController = controller;
    const status = document.getElementById('recommendation-status');
    const submit = document.getElementById('recommend-submit');
    submit.disabled = true;
    document.getElementById('recommendation-form').setAttribute('aria-busy', 'true');
    status.textContent = '로컬 Qwen3.5가 조건을 해석하고 있어요. 첫 실행은 모델 로딩으로 시간이 더 걸릴 수 있어요…';
    try {
        const response = await fetch('/api/recommend', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            signal: controller.signal,
            body: JSON.stringify({
                query, lat: userPosition?.lat ?? null, lon: userPosition?.lon ?? null,
                origin_place_id: originPlaceId
            })
        });
        const result = await response.json();
        if (version !== recommendationVersion) return;
        if (!response.ok) throw new Error(result.error || '추천에 실패했습니다.');
        currentRequestId = result.request_id;
        currentPlaces = result.recommendations;
        renderDecisionResults(result);
        if (result.recommendations.length) {
            // Record actual rendering, not merely successful HTTP delivery.
            sendEvent('recommendations_viewed', null, currentRequestId)
                .catch(() => showEventError(version));
        }
    } catch (error) {
        if (error.name !== 'AbortError' && version === recommendationVersion) {
            status.textContent = error.message || '연결을 확인하고 다시 시도해주세요.';
        }
    } finally {
        if (version === recommendationVersion) {
            submit.disabled = false;
            document.getElementById('recommendation-form').setAttribute('aria-busy', 'false');
            recommendationController = null;
        }
    }
}

document.getElementById('recommendation-form').addEventListener('submit', event => {
    event.preventDefault();
    submitRecommendation();
});
document.getElementById('meal-query').addEventListener('input', () => {
    selectedOriginPlaceId = null;
    invalidateRecommendations();
});

function updateRecommendationUI(recommendations) {
    const container = document.getElementById('weather-hints');
    container.replaceChildren();
    recommendations.forEach(food => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'choice-button';
        button.textContent = food.name;
        button.addEventListener('click', () => {
            invalidateRecommendations();
            document.getElementById('meal-query').value = food.name + ' 메뉴를 추천해줘';
            document.getElementById('meal-query').focus();
        });
        container.appendChild(button);
    });
    document.getElementById('recommendation-section').hidden = !recommendations.length;
}

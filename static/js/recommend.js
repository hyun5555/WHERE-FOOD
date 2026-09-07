const editableFields = [
    ['location_text', '장소 (빈칸이면 지도에서 선택한 위치)', 'text', 200],
    ['budget_krw', '1인 메뉴 예산 상한 (원)', 'number', 1000000],
    ['walking_minutes_max', '도보 시간 상한 (분)', 'number', 120],
    ['max_distance_m', '직선거리 상한 (m)', 'number', 20000],
    ['excluded_ingredients', '제외 재료 · 쉼표로 구분', 'list'],
    ['allergens', '알레르기 성분 · 쉼표로 구분', 'list'],
    ['excluded_foods', '제외 음식·맛 · 쉼표로 구분', 'list'],
    ['dish_tags', '음식 특성 · 쉼표로 구분', 'list'],
    ['atmosphere_tags', '분위기 · 쉼표로 구분', 'list']
];
const dietOptions = {vegan: '비건 (동물성 재료 제외)', vegetarian: '락토오보 채식 (달걀·유제품 허용)',
    pescatarian: '페스코 (육류 제외, 해산물·달걀·유제품 허용)'};

function invalidateRecommendations({discardDraft = false, requireReview = true} = {}) {
    recommendationVersion += 1;
    recommendationController?.abort();
    recommendationController = null;
    currentRequestId = null;
    currentPlaces = [];
    selectedOriginPlaceId = null;
    for (const id of ['recommend-submit', 'confirm-search']) document.getElementById(id).disabled = false;
    for (const id of ['recommendation-form', 'constraint-editor-form']) document.getElementById(id).setAttribute('aria-busy', 'false');
    document.getElementById('map-and-list-section').hidden = true;
    for (const id of ['search-results-list', 'parsed-constraints', 'location-options']) document.getElementById(id).replaceChildren();
    for (const id of ['recommendation-status', 'event-status', 'workflow-status']) document.getElementById(id).textContent = '';
    if (requireReview) document.getElementById('confirm-conditions').checked = false;
    if (discardDraft) {
        constraintDraft = null;
        document.getElementById('condition-review').hidden = true;
        document.getElementById('constraint-editor-fields').replaceChildren();
        document.getElementById('unknown-condition-options').replaceChildren();
    }
    removeMarkers();
}

function reviewCheckbox(id, text, checked, container) {
    const label = node('label', '', 'review-check');
    const input = document.createElement('input');
    input.type = 'checkbox'; input.id = id; input.checked = checked;
    label.appendChild(input);
    label.appendChild(node('span', text));
    container.appendChild(label);
}

function renderConstraintEditor(draft) {
    const container = document.getElementById('constraint-editor-fields');
    container.replaceChildren();
    editableFields.forEach(([key, title, type, limit]) => {
        const label = node('label', title);
        const input = document.createElement('input');
        input.id = 'edit-' + key;
        input.type = type === 'number' ? 'number' : 'text';
        if (type === 'number') { input.min = '1'; input.max = String(limit); input.step = '1'; }
        else input.maxLength = limit || 1000;
        const value = draft.constraints[key];
        input.value = Array.isArray(value) ? value.join(', ') : value ?? '';
        label.appendChild(input);
        container.appendChild(label);
    });
    const policies = document.createElement('fieldset');
    policies.appendChild(node('legend', '필수 조건 설정'));
    Object.entries(dietOptions).forEach(([key, title]) =>
        reviewCheckbox('diet-' + key, title, draft.constraints.dietary_requirements.includes(key), policies));
    reviewCheckbox('edit-open_now', '현재 영업 중 확인 필수', draft.constraints.open_now, policies);
    reviewCheckbox('hard-dish_tags', '입력한 음식 특성 모두 필수', draft.constraints.hard_fields.includes('dish_tags'), policies);
    reviewCheckbox('hard-atmosphere_tags', '입력한 분위기 모두 필수', draft.constraints.hard_fields.includes('atmosphere_tags'), policies);
    container.appendChild(policies);
    const unknown = document.getElementById('unknown-condition-options');
    unknown.replaceChildren();
    draft.unknown_terms.forEach((term, index) => reviewCheckbox('ignore-unknown-' + index,
        '이번 검색에서 제외: ' + term, false, unknown));
    document.getElementById('unknown-conditions').hidden = !draft.unknown_terms.length;
    document.getElementById('confirm-conditions').checked = false;
    document.getElementById('condition-review').hidden = false;
    document.getElementById('review-title').focus();
}

function readConfirmedConstraints() {
    const result = {};
    editableFields.forEach(([key, , type]) => {
        const value = document.getElementById('edit-' + key).value.trim();
        result[key] = type === 'number' ? (value ? Number(value) : null)
            : type === 'list' ? [...new Set(value.split(/[,，\n]/).map(v => v.trim()).filter(Boolean))] : value || null;
    });
    result.dietary_requirements = Object.keys(dietOptions).filter(key => document.getElementById('diet-' + key).checked);
    result.open_now = document.getElementById('edit-open_now').checked;
    result.hard_fields = ['dish_tags', 'atmosphere_tags'].filter(key => document.getElementById('hard-' + key).checked);
    return result;
}

async function parseRecommendation() {
    const query = document.getElementById('meal-query').value.trim();
    if (!query) return;
    invalidateRecommendations({discardDraft: true});
    const version = recommendationVersion;
    const controller = new AbortController();
    recommendationController = controller;
    const submit = document.getElementById('recommend-submit');
    const status = document.getElementById('recommendation-status');
    submit.disabled = true;
    document.getElementById('recommendation-form').setAttribute('aria-busy', 'true');
    status.textContent = '로컬 Qwen3.5가 조건을 해석하고 있어요. 아직 식당을 검색하지 않습니다…';
    try {
        const response = await fetch('/api/constraints', {method: 'POST', headers: {'Content-Type': 'application/json'},
            signal: controller.signal, body: JSON.stringify({query})});
        const draft = await response.json();
        if (version !== recommendationVersion) return;
        if (!response.ok) throw new Error(draft.error || '조건 해석에 실패했습니다.');
        constraintDraft = draft;
        renderConstraintEditor(draft);
        status.textContent = '해석한 조건을 확인·수정한 뒤 검색해주세요. AI가 놓친 조건이 없는지도 확인해주세요.';
    } catch (error) {
        if (error.name !== 'AbortError' && version === recommendationVersion) status.textContent = error.message;
    } finally {
        if (version === recommendationVersion) {
            submit.disabled = false;
            recommendationController = null;
            document.getElementById('recommendation-form').setAttribute('aria-busy', 'false');
        }
    }
}

async function submitRecommendation(originPlaceId = null) {
    const status = document.getElementById('recommendation-status');
    if (!constraintDraft) { status.textContent = '먼저 조건을 해석해주세요.'; return; }
    if (!document.getElementById('constraint-editor-form').reportValidity()) return;
    if (!document.getElementById('confirm-conditions').checked) { status.textContent = '검색할 조건을 확인해주세요.'; return; }
    const payload = {draft_token: constraintDraft.draft_token, confirmed: true, constraints: readConfirmedConstraints(),
        ignored_unknown_terms: constraintDraft.unknown_terms.filter((_, index) => document.getElementById('ignore-unknown-' + index).checked),
        lat: userPosition?.lat ?? null, lon: userPosition?.lon ?? null, origin_place_id: originPlaceId};
    invalidateRecommendations({requireReview: false});
    const version = recommendationVersion;
    const controller = new AbortController();
    recommendationController = controller;
    const submit = document.getElementById('confirm-search');
    submit.disabled = true;
    document.getElementById('constraint-editor-form').setAttribute('aria-busy', 'true');
    status.textContent = '확인한 조건을 검증하고 식당을 검색하고 있어요. 조건을 다시 추론하지 않습니다…';
    try {
        const response = await fetch('/api/recommend', {method: 'POST', headers: {'Content-Type': 'application/json'},
            signal: controller.signal, body: JSON.stringify(payload)});
        const result = await response.json();
        if (version !== recommendationVersion) return;
        if (!response.ok) {
            if (['draft_expired', 'invalid_draft'].includes(result.code)) invalidateRecommendations({discardDraft: true});
            status.textContent = result.error || '추천에 실패했습니다.';
            return;
        }
        currentRequestId = result.request_id;
        currentPlaces = result.recommendations;
        renderDecisionResults(result);
        document.getElementById('workflow-status').textContent = result.workflow ? '처리 경로: ' + result.workflow.steps.join(' → ') : '';
        if (result.recommendations.length) sendEvent('recommendations_viewed', null, currentRequestId).catch(() => showEventError(version));
    } catch (error) {
        if (error.name !== 'AbortError' && version === recommendationVersion) status.textContent = error.message;
    } finally {
        if (version === recommendationVersion) {
            submit.disabled = false;
            recommendationController = null;
            document.getElementById('constraint-editor-form').setAttribute('aria-busy', 'false');
        }
    }
}

document.getElementById('recommendation-form').addEventListener('submit', event => { event.preventDefault(); parseRecommendation(); });
document.getElementById('meal-query').addEventListener('input', () => invalidateRecommendations({discardDraft: true}));
document.getElementById('constraint-editor-form').addEventListener('submit', event => { event.preventDefault(); submitRecommendation(); });
document.getElementById('constraint-editor-form').addEventListener('input', event => {
    invalidateRecommendations({requireReview: event.target.id !== 'confirm-conditions'});
});

function updateRecommendationUI(recommendations) {
    const container = document.getElementById('weather-hints');
    container.replaceChildren();
    recommendations.forEach(food => {
        const button = node('button', food.name, 'choice-button');
        button.type = 'button';
        button.addEventListener('click', () => {
            invalidateRecommendations({discardDraft: true});
            document.getElementById('meal-query').value = food.name + ' 메뉴를 추천해줘';
            document.getElementById('meal-query').focus();
        });
        container.appendChild(button);
    });
    document.getElementById('recommendation-section').hidden = !recommendations.length;
}

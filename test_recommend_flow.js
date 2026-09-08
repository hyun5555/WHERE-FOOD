// Run: node test_recommend_flow.js. No browser dependency or external API calls.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {randomUUID} = require('node:crypto');

class Element {
    constructor(tag = 'div') {
        this.tagName = tag;
        this.children = [];
        this.textContent = '';
        this.value = '';
        this.hidden = false;
        this.disabled = false;
        this.checked = false;
        this.attributes = {};
        this.style = {};
        this.handlers = {};
    }
    appendChild(child) { this.children.push(child); return child; }
    replaceChildren(...children) { this.children = children; }
    addEventListener(type, fn) { this.handlers[type] = fn; }
    setAttribute(name, value) { this.attributes[name] = value; }
    removeAttribute(name) { delete this.attributes[name]; delete this[name]; }
    focus() {}
    scrollIntoView() {}
    reportValidity() { return true; } // Native validation is also checked in the real browser.
    set id(value) { this._id = value; elements.set(value, this); }
    get id() { return this._id; }
    set value(value) { this._value = String(value); }
    get value() { return this._value; }
}
const elements = new Map();
const get = id => {
    if (!elements.has(id)) elements.set(id, new Element());
    return elements.get(id);
};
const requests = [];
const pending = [];
const context = vm.createContext({
    document: {getElementById: get, createElement: tag => new Element(tag)},
    URL, AbortController, crypto: {randomUUID}, removeMarkers() {},
    fetch: (url, options) => {
        requests.push({url, ...options, json: JSON.parse(options.body)});
        if (url === '/api/events') return Promise.resolve({ok: true});
        return new Promise(resolve => pending.push(resolve));
    }
});
for (const file of ['state', 'weather', 'restaurant', 'recommend']) {
    vm.runInContext(fs.readFileSync('static/js/' + file + '.js', 'utf8'), context);
}
const run = code => vm.runInContext(code, context);
const descendants = e => [e, ...e.children.flatMap(descendants)];
const source = {title: 'TEST ONLY', url: 'https://example.com/menu', observed_on: '2026-09-07', excerpt: '검증 예시'};
const result = {
    request_id: randomUUID(), status: 'partial', message: '테스트 결과',
    constraints: {budget_krw: 15000, dietary_requirements: ['vegan'], open_now: true, hard_fields: []},
    location_options: [], origin: {name: '강남역'}, notice: '테스트',
    recommendations: [{
        id: '1', place_name: '<img src=x onerror=alert(1)>', rank: 1,
        address_name: '테스트 주소', distance: 300,
        menu: {name: '국밥', price_krw: 10000, source},
        route: null, matches: [{text: '예산 이내', source}], unknown: ['조용한지 미확인'],
        place_source: source, place_url: 'javascript:alert(1)',
        opening_status: null,
        score_breakdown: {soft_matches: 1, evidence_completeness: 0.5, evidence_age_days: 10, weather_score: null, weather_applied: false}
    }]
};
const draft = {draft_token: 'signed-test-token', expires_in: 1800, unknown_terms: ['내일 예약'], constraints: {
    location_text: '강남역', budget_krw: 15000, walking_minutes_max: null, max_distance_m: null,
    excluded_ingredients: ['땅콩'], allergens: [], dietary_requirements: [], open_now: false,
    excluded_foods: [], dish_tags: [], atmosphere_tags: ['조용한'], hard_fields: []
}};
const finish = async (promise, data, ok = true) => {
    pending.shift()({ok, json: async () => data});
    await promise;
};

(async () => {
    // NCST has PTY but no SKY: no precipitation is known, sunshine is not.
    for (const rainType of ['0', 0]) {
        for (const sky of [null, undefined, '', '99']) {
            context.weatherCase = {rainType, sky};
            assert.equal(run('getWeatherVisuals(weatherCase.rainType, weatherCase.sky).description'), '강수 없음');
        }
    }
    for (const rainType of [null, undefined, '', '99', false]) {
        context.rainCase = rainType;
        assert.equal(run('getWeatherVisuals(rainCase, null).description'), '날씨 상태 미확인');
    }
    for (const [code, text] of [['1','비'], ['2','비/눈'], ['3','눈'], ['4','소나기'],
                                ['5','빗방울'], ['6','빗방울/눈날림'], ['7','눈날림']]) {
        assert.equal(run(`getWeatherVisuals('${code}', '1').description`), text);
    }
    for (const [sky, text] of [['1','맑음'], ['3','구름많음'], ['4','흐림']]) {
        assert.equal(run(`getWeatherVisuals('0', '${sky}').description`), text);
    }
    run("updateWeatherUI({temp:24.5, humidity:71, wind_speed:1.3, rain_type_code:'0', sky_code:null}, {name:'테스트 위치'})");
    assert.equal(get('weather-description').textContent, '강수 없음');
    assert.equal(get('weather-icon').className, 'bi bi-thermometer-half weather-icon');
    assert.equal(get('temperature').textContent, '24.5°C');
    assert.equal(get('humidity').textContent, '71%');
    assert.equal(get('wind-speed').textContent, '1.3 m/s');
    assert.equal(get('weather-info').hidden, false);

    get('meal-query').value = '강남역에서 15000원 이하';
    const extraction = run('parseRecommendation()');
    assert.equal(requests[0].url, '/api/constraints');
    assert.equal(get('recommend-submit').disabled, true);
    await finish(extraction, draft);
    assert.equal(get('recommend-submit').disabled, false);
    assert.equal(get('condition-review').hidden, false);
    assert.equal(get('edit-budget_krw').value, '15000');
    assert.equal(get('confirm-conditions').checked, false);
    assert.equal(requests.length, 1, 'extraction must not search or record impressions');
    await run('submitRecommendation()');
    assert.equal(requests.length, 1, 'unchecked confirmation cannot search');
    get('edit-budget_krw').value = '12000';
    get('confirm-conditions').checked = true;
    get('ignore-unknown-0').checked = true;
    const first = run('submitRecommendation()');
    assert.equal(requests.at(-1).url, '/api/recommend');
    assert.equal(requests.at(-1).json.lat, null, 'textual location works without geolocation');
    assert.equal(requests.at(-1).json.constraints.budget_krw, 12000);
    assert.equal(requests.at(-1).json.draft_token, draft.draft_token);
    assert.deepEqual(requests.at(-1).json.ignored_unknown_terms, ['내일 예약']);
    assert(!('query' in requests.at(-1).json));
    await finish(first, result);
    assert.equal(get('map-and-list-section').hidden, false);
    assert.equal(get('search-results-list').children.length, 1);
    assert.equal(requests.filter(r => r.json.event_type === 'recommendations_viewed').length, 1);
    const nodes = descendants(get('search-results-list'));
    assert(nodes.some(n => n.textContent === '현재 영업 여부 미확인'));
    assert(nodes.some(n => n.textContent === '날씨 참고 점수 미확인 · 정렬 미적용'));
    assert(descendants(get('parsed-constraints')).some(n => n.textContent === '필수 식단: 비건'));
    assert(descendants(get('parsed-constraints')).some(n => n.textContent === '현재 영업 필수: 예'));
    assert(nodes.some(n => n.tagName === 'h3' && n.textContent.includes('<img')), 'provider HTML must remain text');
    assert(!nodes.some(n => n.tagName === 'img'));
    assert(!nodes.find(n => n.textContent === '상세보기').href, 'unsafe URL must be removed');
    const select = nodes.find(n => n.textContent === '이 식당 선택');
    await select.handlers.click();
    assert.equal(requests.at(-1).json.event_type, 'restaurant_selected');
    assert.equal(requests.at(-1).json.request_id, result.request_id);
    assert.equal(requests.at(-1).json.place_id, '1');

    // A location clarification reuses the reviewed draft, never the parser.
    const clarification = run('submitRecommendation()');
    await finish(clarification, {...result, recommendations: [], location_options: [{id: '2', name: '역', address: '주소'}]});
    const chooseLocation = get('location-options').children[0].handlers.click();
    assert.equal(requests.at(-1).json.origin_place_id, '2');
    await finish(chooseLocation, result);
    assert.equal(requests.filter(r => r.url === '/api/constraints').length, 1);

    // Edited conditions invalidate old results and require renewed consent.
    const slow = run('submitRecommendation()');
    get('constraint-editor-form').handlers.input({target: get('edit-budget_krw')});
    assert.equal(get('confirm-conditions').checked, false);
    assert.equal(get('map-and-list-section').hidden, true);
    get('confirm-conditions').checked = true;
    const fast = run('submitRecommendation()');
    const resolveSlow = pending.shift(), resolveFast = pending.shift();
    resolveFast({ok: true, json: async () => ({...result, request_id: 'new', message: '새 결과'})});
    await fast;
    resolveSlow({ok: true, json: async () => ({...result, request_id: 'old', message: '이전 결과'})});
    await slow;
    assert.equal(get('recommendation-status').textContent, '새 결과');
    assert.equal(run('currentRequestId'), 'new');

    // Query edits discard the draft; a late failure cannot overwrite the new state.
    const staleError = run('submitRecommendation()');
    get('meal-query').handlers.input();
    assert.equal(get('map-and-list-section').hidden, true);
    assert.equal(run('currentRequestId'), null);
    assert.equal(run('constraintDraft'), null);
    await finish(staleError, {error: '오래된 오류'}, false);
    assert.equal(get('recommendation-status').textContent, '');

    // Stale parser responses cannot restore an abandoned draft.
    const slowParse = run('parseRecommendation()');
    const fastParse = run('parseRecommendation()');
    const oldParse = pending.shift(), newParse = pending.shift();
    newParse({ok: true, json: async () => ({...draft, draft_token: 'new-draft'})});
    await fastParse;
    oldParse({ok: true, json: async () => draft});
    await slowParse;
    assert.equal(run('constraintDraft.draft_token'), 'new-draft');
    get('confirm-conditions').checked = true;
    await finish(run('submitRecommendation()'), {error: '초안 만료', code: 'draft_expired'}, false);
    assert.equal(get('recommendation-status').textContent, '초안 만료');
    assert.equal(run('constraintDraft'), null);
    assert.equal(get('condition-review').hidden, true);

    await finish(run('parseRecommendation()'), {error: 'API 키 미설정'}, false);
    assert.equal(get('recommendation-status').textContent, 'API 키 미설정');
    assert.equal(get('recommend-submit').disabled, false);
    const grounded = structuredClone(result);
    grounded.weather_context = {source: {title: '날씨 테스트 출처', url: 'https://example.com/weather'}, observed_at: '2026-09-07T13:00:00+09:00'};
    grounded.recommendations[0].score_breakdown.weather_score = 0.13;
    grounded.recommendations[0].score_breakdown.weather_applied = true;
    context.groundedResult = grounded;
    run('renderDecisionResults(groundedResult)');
    assert(descendants(get('search-results-list')).some(n => n.href === 'https://example.com/weather'));
    assert(descendants(get('search-results-list')).some(n => n.textContent.includes('선택 확률 아님')));
    console.log('PASS: weather observations, parse/review/search, explicit confirmation, location reuse, stale responses, expiry, feedback, XSS');
})().catch(error => { console.error(error); process.exitCode = 1; });

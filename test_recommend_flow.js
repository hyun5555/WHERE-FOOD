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
    getAttribute(name) { return this.attributes[name] ?? null; }
    removeAttribute(name) { delete this.attributes[name]; delete this[name]; }
    focus() {}
    scrollIntoView(options) { this.scrolled = options; }
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
const startup = {};
const context = vm.createContext({
    window: {addEventListener: (event, callback) => startup[event] = callback},
    navigator: {geolocation: {getCurrentPosition: (success, failure) => { startup.gps = success; startup.gpsError = failure; startup.gpsCalls = (startup.gpsCalls || 0) + 1; }}},
    document: {getElementById: get, createElement: tag => new Element(tag)},
    URL, AbortController, crypto: {randomUUID},
    fetch: (url, options) => {
        requests.push({url, ...options, json: JSON.parse(options.body)});
        if (url === '/api/events') return Promise.resolve({ok: true});
        return new Promise(resolve => pending.push(resolve));
    }
});
for (const file of ['state', 'map', 'weather', 'restaurant', 'recommend', 'app']) {
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
    grounded.recommendations[0].explanation = {
        method: 'qwen_grounded', sentences: [{text: '국밥 10,000원 · 예산 이내', source_id: 'p1-s0'},
            {text: '<img src=x onerror=alert(1)>', source_id: 'p1-s0'},
            {text: '출처가 없는 문장', source_id: 'missing'}],
        sources: [{...source, source_id: 'p1-s0'}]
    };
    run('renderDecisionResults(groundedResult)');
    let explanationNodes = descendants(get('search-results-list'));
    assert(explanationNodes.some(n => n.textContent === 'Qwen 근거 요약'));
    assert(explanationNodes.some(n => n.textContent === '국밥 10,000원 · 예산 이내'));
    assert(!explanationNodes.some(n => n.tagName === 'img'), 'explanation HTML must remain text');
    assert(!explanationNodes.some(n => n.textContent === '출처가 없는 문장'));
    assert(explanationNodes.some(n => n.href === source.url));
    grounded.recommendations[0].explanation = {method: 'template', sentences: [], sources: [], fallback_reason: 'ollama_timeout'};
    run('renderDecisionResults(groundedResult)');
    explanationNodes = descendants(get('search-results-list'));
    assert(explanationNodes.some(n => n.textContent === 'AI 요약을 사용하지 못해 기존 근거 설명을 표시합니다.'));
    assert(explanationNodes.some(n => n.textContent === '예산 이내'), 'existing matches survive fallback');
    assert(!explanationNodes.some(n => n.textContent === 'Qwen 근거 요약'), 'previous generated text is cleared');
    context.classified = {...result, diagnostics: {rejections: [
        {category: 'constraint_mismatch', code: 'budget_exceeded', message: '예산 초과'},
        {category: 'missing_evidence', code: 'allergy_evidence_missing', message: '땅콩 확인 근거 없음'},
        {category: 'missing_evidence', code: 'menu_invalid', message: '<img src=x onerror=alert(1)>'},
        {category: 'expired_evidence', code: 'menu_evidence_expired', message: '메뉴 자료 만료'}
    ]}};
    run('invalidateRecommendations(); renderDecisionResults(classified)');
    let reasons = descendants(get('location-options'));
    assert(reasons.some(n => n.textContent === '조건 불충족 · 1건'));
    assert(reasons.some(n => n.textContent === '근거 부족 · 2건'));
    assert(reasons.some(n => n.textContent === '자료 만료 · 1건'));
    assert(reasons.some(n => n.textContent.includes('식당 수가 아닙니다')));
    assert(!reasons.some(n => n.tagName === 'img'), 'diagnostics remain text');
    assert.equal(get('map-and-list-section').hidden, false, 'partial results also show diagnostics');
    assert(descendants(get('search-results-list')).some(n => n.textContent === '선택적 선호 미확인 · 추천 제외 사유 아님'));
    context.classified.recommendations = [];
    run('invalidateRecommendations(); renderDecisionResults(classified)');
    assert.equal(get('map-and-list-section').hidden, true);
    assert(descendants(get('location-options')).some(n => n.textContent.includes('알레르기는 근거 없이 통과시키지 않습니다')));
    run('invalidateRecommendations()');
    assert.equal(get('location-options').children.length, 0, 'old diagnostics clear on edit');
    // Real app.js callbacks: latest location intent beats old SDK results AND startup GPS.
    startup.DOMContentLoaded(); // Missing map SDK is allowed; captures the GPS callbacks.
    context.kakao = {maps: {services: {Status: {OK: 'OK'}}}};
    const locationCallbacks = [];
    context.locationCallbacks = locationCallbacks;
    run('ps = {keywordSearch: (query, callback) => locationCallbacks.push({query, callback})}');
    get('location-search-input').value = '이전 장소';
    run('searchLocation()');
    get('location-search-input').value = '최신 장소';
    run('searchLocation()');
    locationCallbacks[1].callback([{x: 127, y: 37.5}], 'OK');
    assert.equal(run('userPosition.lat'), 37.5);
    const countAfterLatest = requests.length;
    locationCallbacks[0].callback([{x: 126, y: 35}], 'OK');
    locationCallbacks[0].callback([], 'ERROR');
    startup.gps({coords: {latitude: 34, longitude: 125}});
    startup.gpsError();
    assert.equal(run('userPosition.lat'), 37.5);
    assert.equal(requests.length, countAfterLatest, 'stale SDK/GPS callbacks cannot start weather requests');
    assert(get('loading').textContent.includes('날씨를 확인하고'), 'late GPS error must not overwrite status');
    const oldWeather = pending.shift();
    get('location-search-input').value = '여러 장소';
    run('searchLocation()');
    locationCallbacks.at(-1).callback([{x: 128, y: 38, place_name: '후보 A', address_name: 'A'},
                                     {x: 129, y: 36, place_name: '후보 B', address_name: 'B'}], 'OK');
    const staleChoice = get('location-options').children[0];
    get('location-search-input').value = '다음 검색';
    run('searchLocation()');
    staleChoice.handlers.click();
    assert.equal(run('userPosition'), null, 'new location intent clears the old origin until selection');
    context.locationDraft = {...draft, unknown_terms: []};
    run('constraintDraft = locationDraft; renderConstraintEditor(constraintDraft)');
    get('edit-location_text').value = '';
    get('confirm-conditions').checked = true;
    const waitingForLocation = run('submitRecommendation()');
    assert.equal(requests.at(-1).json.lat, null, 'pending location search cannot send old latitude');
    assert.equal(requests.at(-1).json.lon, null, 'pending location search cannot send old longitude');
    await finish(waitingForLocation, {...result, status: 'clarification_required', recommendations: []});
    oldWeather({ok: true, json: async () => ({weather: {temp: -99}, location: {name: 'stale'}, recommendations: []})});
    await new Promise(resolve => setImmediate(resolve));
    assert.notEqual(get('temperature').textContent, '-99°C');
    run('ps = undefined');
    get('location-search-input').value = '강남역';
    run('searchLocation()');
    assert.equal(get('meal-query').value, '강남역에서 식당 추천해줘', 'SDK failure still supports textual location');
    // Real map.js with a controlled SDK: these checks do not prove live tiles/domain authorization.
    const mapCalls = [];
    class LatLng {
        constructor(lat, lon) { this.lat = Number(lat); this.lon = Number(lon); }
        getLat() { return this.lat; }
        getLng() { return this.lon; }
    }
    class MapStub {
        relayout() { mapCalls.push('relayout'); }
        setCenter(position) { this.center = position; }
        setBounds(bounds) { this.bounds = bounds; mapCalls.push('bounds'); }
    }
    class Marker {
        constructor(options) { this.options = options; this.position = options.position; }
        setMap(map) { this.map = map; }
        getPosition() { return this.position; }
        setPosition(position) { this.position = position; }
    }
    context.kakao = {maps: {Map: MapStub, LatLng, Marker, Size: class {}, Point: class {}, MarkerImage: class {},
        LatLngBounds: class { constructor() { this.positions = []; } extend(position) { this.positions.push(position); } },
        services: {Places: class {}, Status: {OK: 'OK'}},
        event: {addListener: (target, name, callback) => { (target.handlers ||= {})[name] = callback; }}}};
    get('map-and-list-section').setAttribute('data-map-check', 'true');
    const gpsCalls = startup.gpsCalls;
    startup.DOMContentLoaded();
    assert.equal(startup.gpsCalls, gpsCalls, 'map check does not request private GPS location');
    assert.equal(get('map').getAttribute('data-map-state'), 'waiting-for-tiles');
    run('map.handlers.tilesloaded()');
    assert.equal(get('map').getAttribute('data-map-state'), 'tiles-loaded');
    context.mapResult = {...result, origin: {name: '공개 테스트 장소', lat: 37.5, lon: 127},
        recommendations: result.recommendations.map(p => ({...p, x: '127.01', y: '37.51'}))};
    mapCalls.length = 0;
    run('invalidateRecommendations(); renderDecisionResults(mapResult)');
    assert.equal(get('map-and-list-section').hidden, false);
    assert.equal(run('markers.length'), 1);
    assert.deepEqual(mapCalls, ['relayout', 'bounds'], 'visible map relayout precedes recommendation bounds');
    const main = run('mainMarker');
    const previousRestaurantMarker = run('markers[0]');
    run('renderDecisionResults(mapResult)');
    assert.equal(run('mainMarker'), main, 'main marker is reused');
    assert.equal(previousRestaurantMarker.map, null, 'old restaurant markers are removed');
    assert.equal(run('markers.length'), 1, 'new results do not accumulate markers');
    run('markers[0].handlers.click()');
    assert.equal(get('place-1').scrolled.block, 'center', 'marker click targets the matching restaurant card');
    main.position = new LatLng(37.52, 127.02);
    main.handlers.dragend();
    assert.equal(requests.at(-1).json.lat, 37.52, 'dragging selects the new search origin');
    assert.equal(get('map-and-list-section').hidden, false, 'map check remains visible when results are invalidated');
    await finish(Promise.resolve(), {weather: {temp: 24, humidity: 50, wind_speed: 1}, location: {name: '테스트'}, recommendations: []});
    await new Promise(resolve => setImmediate(resolve));
    context.kakao.maps.Map = class { constructor() { throw new Error('SDK initialization failure'); } };
    startup.DOMContentLoaded();
    assert.equal(run('map'), undefined);
    assert.equal(run('ps'), undefined);
    assert.equal(get('map').getAttribute('data-map-state'), 'unavailable');
    assert(get('map-check-status').textContent.includes('SDK 도메인'));
    get('map-and-list-section').setAttribute('data-map-check', 'false');
    run('invalidateRecommendations()');
    assert.equal(get('map-and-list-section').hidden, true, 'normal mode still clears old results');
    console.log('PASS: weather observations, parse/review/search, map/marker callbacks, explicit confirmation, location/GPS ordering, stale responses, expiry, feedback, evidence diagnostics, XSS');
})().catch(error => { console.error(error); process.exitCode = 1; });

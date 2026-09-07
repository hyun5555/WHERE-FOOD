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
        this.attributes = {};
        this.handlers = {};
    }
    appendChild(child) { this.children.push(child); return child; }
    replaceChildren(...children) { this.children = children; }
    addEventListener(type, fn) { this.handlers[type] = fn; }
    setAttribute(name, value) { this.attributes[name] = value; }
    removeAttribute(name) { delete this.attributes[name]; delete this[name]; }
    focus() {}
    scrollIntoView() {}
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
for (const file of ['state', 'restaurant', 'recommend']) {
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

(async () => {
    get('meal-query').value = '강남역에서 15000원 이하';
    const first = run('submitRecommendation()');
    assert.equal(requests[0].json.lat, null, 'textual location works without geolocation');
    assert.equal(get('recommend-submit').disabled, true);
    pending.shift()({ok: true, json: async () => result});
    await first;
    assert.equal(get('recommend-submit').disabled, false);
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

    // Older network response cannot overwrite a newly submitted query.
    get('meal-query').value = '이전 요청';
    const slow = run('submitRecommendation()');
    get('meal-query').value = '새 요청';
    const fast = run('submitRecommendation()');
    const resolveSlow = pending.shift(), resolveFast = pending.shift();
    resolveFast({ok: true, json: async () => ({...result, request_id: 'new', message: '새 결과'})});
    await fast;
    resolveSlow({ok: true, json: async () => ({...result, request_id: 'old', message: '이전 결과'})});
    await slow;
    assert.equal(get('recommendation-status').textContent, '새 결과');
    assert.equal(run('currentRequestId'), 'new');

    // Editing the query removes old recommendation actions and aborts pending work.
    get('meal-query').handlers.input();
    assert.equal(get('map-and-list-section').hidden, true);
    assert.equal(run('currentRequestId'), null);

    const failed = run('submitRecommendation()');
    pending.shift()({ok: false, json: async () => ({error: 'API 키 미설정'})});
    await failed;
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
    console.log('PASS: render, no-location request, feedback, XSS, stale response, edit reset, error recovery');
})().catch(error => { console.error(error); process.exitCode = 1; });

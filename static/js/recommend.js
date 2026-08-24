// 오늘의 추천 메뉴와 AI 취향 입력 UI

function updateRecommendationUI(recommendations) {
    const carouselInner = document.getElementById('recommendation-carousel-inner');
    const foodImageMap = {
        '치킨': '/static/images/치킨.png', '한식': '/static/images/한식.png', '족발/보쌈': '/static/images/족발.png',
        '중식': '/static/images/중식.png', '돈까스/일식': '/static/images/일식.png', '아시안/양식': '/static/images/양식.png',
        '피자': '/static/images/피자.png', '분식': '/static/images/분식.png', '회': '/static/images/회.png',
        '패스트푸드': '/static/images/패스트푸드.png', '찜탕': '/static/images/찜탕.png', '카페/디저트': '/static/images/카페.png',
        '도시락': '/static/images/도시락.png', 'default': '/static/images/한식.png'
    };

    carouselInner.innerHTML = recommendations.reduce((html, food, index) => {
        if (index % 3 === 0) html += `${index ? '</div></div>' : ''}<div class="carousel-item ${index ? '' : 'active'}"><div class="row row-cols-1 row-cols-md-3 g-3">`;
        const imageUrl = foodImageMap[food.name] || foodImageMap.default;
        return html + `
            <div class="col">
                <button type="button" class="card h-100 food-card w-100" onclick="searchAndDisplayPlaces('${food.name}')" aria-label="${food.name} 주변 맛집 보기">
                    <span class="food-rank">${index + 1}위</span>
                    <img src="${imageUrl}" class="card-img-top" alt="">
                    <span class="card-body text-center">
                        <strong class="card-title d-block">${food.name}</strong>
                        <small class="card-text text-muted">추천 지수 ${food.prob}</small>
                    </span>
                </button>
            </div>`;
    }, '') + (recommendations.length ? '</div></div>' : '');

    document.getElementById('recommendation-section').hidden = false;
}

const heatmapToggle = document.getElementById('toggleLink');
const heatmapContent = document.getElementById('toggleContent');

heatmapToggle.addEventListener('click', () => {
    const willOpen = heatmapContent.hidden;
    heatmapContent.hidden = !willOpen;
    heatmapToggle.setAttribute('aria-expanded', willOpen);
    heatmapToggle.innerHTML = `<i class="bi bi-bar-chart"></i> 분석 결과 ${willOpen ? '닫기' : '보기'}`;
});

const preferenceSection = document.getElementById('ai-preference-section');
const preferenceInput = document.getElementById('food-preference');
const yesButton = document.getElementById('ai-yes-btn');
const noButton = document.getElementById('ai-no-btn');

function setPreferenceVisible(visible) {
    preferenceSection.hidden = !visible;
    yesButton.classList.toggle('active', visible);
    noButton.classList.toggle('active', !visible);
    yesButton.setAttribute('aria-expanded', visible);
    noButton.setAttribute('aria-expanded', false);
    if (visible) preferenceInput.focus();
}

yesButton.addEventListener('click', () => setPreferenceVisible(true));
noButton.addEventListener('click', () => setPreferenceVisible(false));

document.getElementById('ai-preference-form').addEventListener('submit', event => {
    event.preventDefault();
    const preference = preferenceInput.value.trim();
    if (!preference) return;
    if (!userPosition) {
        alert('먼저 위치를 검색하거나 위치 권한을 허용해주세요.');
        return;
    }
    searchAndDisplayPlaces(preference);
    document.getElementById('map-and-list-section').scrollIntoView({ behavior: 'smooth' });
});

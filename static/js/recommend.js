//오늘의 추천 메뉴 TOP3 화면 담당, AI 추천 요청

function updateRecommendationUI(all_recommendations) {
    const carouselInner = document.getElementById('recommendation-carousel-inner');
        carouselInner.innerHTML = '';

        const foodImageMap = {
            '치킨': '/static/images/치킨.png', '한식': '/static/images/한식.png', '족발/보쌈': '/static/images/족발.png',
            '중식': '/static/images/중식.png', '돈까스/일식': '/static/images/일식.png', '아시안/양식': '/static/images/양식.png',
            '피자': '/static/images/피자.png', '분식': '/static/images/분식.png', '회': '/static/images/회.png',
            '패스트푸드': '/static/images/패스트푸드.png', '찜탕': '/static/images/찜탕.png','카페/디저트': '/static/images/카페.png',
            '도시락': '/static/images/도시락.png',
            'default': '/static/images/한식.png'
        };
        
        const allCarouselFoods = all_recommendations;

        let carouselHtml = '';
        for (let i = 0; i < allCarouselFoods.length; i++) {
            if (i % 3 === 0) {
                if (i > 0) carouselHtml += `</div></div>`;
                const activeClass = (i === 0) ? 'active' : '';
                carouselHtml += `<div class="carousel-item ${activeClass}"><div class="row row-cols-1 row-cols-md-3 g-4">`;
            }

            const food = allCarouselFoods[i];
            const imageUrl = foodImageMap[food.name] || foodImageMap['default'];
            
            // food.prob에는 이제 항상 계산된 퍼센트 값이 들어있습니다. onclick="handleFoodClick('${food.name}
            carouselHtml += `
            <div class="col">
                <div class="card h-100 food-card" onclick="searchAndDisplayPlaces('${food.name}')">
                    <img src="${imageUrl}" class="card-img-top" alt="${food.name}">
                    <div class="card-body text-center">
                        <h5 class="card-title fw-bold">${food.name}</h5>
                        <p class="card-text"><small class="text-muted">${food.prob}</small></p>
                    </div>
                </div>
            </div>`;
        }

        if (allCarouselFoods.length > 0) carouselHtml += `</div></div>`;
        carouselInner.innerHTML = carouselHtml;
        document.getElementById('recommendation-section').style.display = 'block';
}



 // 추천 이유 토글 
document.getElementById('toggleLink').addEventListener('click', function(event) {
    event.preventDefault(); // 기본 동작 (페이지 이동) 방지
    var content = document.getElementById('toggleContent');
    if (content.style.display === 'none') {
        content.style.display = 'block';
    } else {
        content.style.display = 'none';
    }
});




function handleFoodClick(foodName) {
    selectedFood = foodName;

    document.getElementById('ai-choice-section').style.display = 'block';
    document.getElementById('preference-input-section').style.display = 'none';
    document.getElementById('ai-result-section').style.display = 'none';

    document.getElementById('selected-food-name').textContent = foodName;
}

function handleAiNo() {
    searchAndDisplayPlaces(selectedFood);
}

function handleAiYes() {
    document.getElementById('preference-input-section').style.display = 'block';
}
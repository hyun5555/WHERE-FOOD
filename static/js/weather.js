//날씨 UI 함수, 현재 위치 기반 날씨 조회

function updateWeatherUI(weather, location) {
    if (weather.error) {
        document.getElementById('loading').textContent = weather.error;
        return;
    }
    document.getElementById('location-name').textContent = location.name;
    const { icon, description } = getWeatherVisuals(weather.rain_type_code, weather.sky_code);
    document.getElementById('weather-icon').className = `bi ${icon} weather-icon`;
    document.getElementById('weather-description').textContent = description;
    document.getElementById('temperature').textContent = `${weather.temp.toFixed(1)}°C`;
    document.getElementById('humidity').textContent = `${weather.humidity.toFixed(0)}%`;
    document.getElementById('wind-speed').textContent = `${weather.wind_speed.toFixed(1)} m/s`;
    document.getElementById('loading').style.display = 'none';
    document.getElementById('weather-info').hidden = false;
}

function getWeatherVisuals(rainType, sky) {
    // Missing observations are not the same as PTY=0 (no precipitation).
    const safeRainType = String(rainType ?? '').trim();
    const safeSky = String(sky ?? '').trim();

    // 1. 먼저 강수 형태(PTY)를 확인하여 비나 눈이 오는지 판단합니다.
    switch (safeRainType) {
        case '1': return { icon: 'bi-cloud-rain-fill', description: '비' };
        case '2': return { icon: 'bi-cloud-sleet-fill', description: '비/눈' };
        case '3': return { icon: 'bi-snow', description: '눈' };
        case '4': return { icon: 'bi-cloud-lightning-rain-fill', description: '소나기' };
        case '5': return { icon: 'bi-cloud-drizzle-fill', description: '빗방울' };
        case '6': return { icon: 'bi-cloud-sleet-fill', description: '빗방울/눈날림' };
        case '7': return { icon: 'bi-snow2', description: '눈날림' };
        // case '0' (강수 없음)은 아래에서 처리
    }

    // 2. 강수 형태가 '없음'일 경우, 하늘 상태(SKY)로 날씨를 판단합니다.
    switch (safeSky) {
        case '1': return { icon: 'bi-sun-fill', description: '맑음' };
        case '3': return { icon: 'bi-cloud-sun-fill', description: '구름많음' };
        case '4': return { icon: 'bi-clouds-fill', description: '흐림' };
        default:
            // getUltraSrtNcst supplies PTY but not SKY. No rain does not mean sunny.
            return safeRainType === '0'
                ? { icon: 'bi-thermometer-half', description: '강수 없음' }
                : { icon: 'bi-question-circle', description: '날씨 상태 미확인' };
    }
}

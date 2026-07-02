// 여러 함수에서 공유해서 사용할 전역 변수
let map, mainMarker, ps;
let userPosition;
let markers = [];
let currentPlaces = []; // 현재 표시 중인 맛집 데이터 저장
let originalPlaces = [];
let currentWeather = null;
let selectedFood = null;
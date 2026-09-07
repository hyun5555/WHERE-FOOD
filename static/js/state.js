// One location and one visible recommendation request at a time.
let map, mainMarker, ps;
let userPosition = null; // {lat, lon}, usable even if the map SDK fails.
let markers = [];
let currentPlaces = [];
let currentRequestId = null;
let recommendationController = null;
let recommendationVersion = 0;
let locationVersion = 0;
let selectedOriginPlaceId = null;

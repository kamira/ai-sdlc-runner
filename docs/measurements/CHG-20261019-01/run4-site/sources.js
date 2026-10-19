/* sources.js — 來源設定：兩個來源的名稱、網址與查詢參數，以及依有無金鑰選用哪一個。
   這個檔案不含任何金鑰；金鑰只由使用者輸入，存在 localStorage。 */
(function (global) {
  'use strict';

  var LATITUDE = '25.0330';
  var LONGITUDE = '121.5654';
  var TIMEZONE = 'Asia/Taipei';
  var TIMEOUT_MS = 15000;

  // localStorage 裡存放使用者金鑰的欄位名稱（只是名稱，不是金鑰）
  var KEY_STORAGE_NAME = 'cwa-authorization';

  var OPEN_METEO = {
    id: 'openmeteo',
    name: 'Open-Meteo',
    host: 'api.open-meteo.com',
    url: 'https://api.open-meteo.com/v1/forecast',
    params: {
      latitude: LATITUDE,
      longitude: LONGITUDE,
      current: 'temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m',
      hourly: 'temperature_2m',
      daily: 'weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max',
      timezone: TIMEZONE,
      forecast_days: '7'
    }
  };

  var CWA = {
    id: 'cwa',
    name: '中央氣象署 (CWA)',
    host: 'opendata.cwa.gov.tw',
    // 臺北市未來一週預報
    forecastUrl: 'https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-D0047-063',
    // 現在觀測
    observationUrl: 'https://opendata.cwa.gov.tw/api/v1/rest/datastore/O-A0003-001',
    stationId: '466920',
    // 金鑰放在這個查詢參數；值由 cwa.js 在請求時填入
    keyParam: 'Authorization'
  };

  function readKey() {
    try {
      var v = global.localStorage.getItem(KEY_STORAGE_NAME);
      return v ? v.trim() : '';
    } catch (e) {
      return '';
    }
  }

  function saveKey(value) {
    var v = (value || '').trim();
    if (!v) { return false; }
    try {
      global.localStorage.setItem(KEY_STORAGE_NAME, v);
      return true;
    } catch (e) {
      return false;
    }
  }

  function clearKey() {
    try { global.localStorage.removeItem(KEY_STORAGE_NAME); } catch (e) { /* 忽略 */ }
  }

  // 有金鑰用 CWA，沒有就用 Open-Meteo
  function chooseSource() {
    return readKey() ? CWA : OPEN_METEO;
  }

  global.Sources = {
    LATITUDE: LATITUDE,
    LONGITUDE: LONGITUDE,
    TIMEZONE: TIMEZONE,
    TIMEOUT_MS: TIMEOUT_MS,
    OPEN_METEO: OPEN_METEO,
    CWA: CWA,
    readKey: readKey,
    saveKey: saveKey,
    clearKey: clearKey,
    chooseSource: chooseSource
  };
})(window);

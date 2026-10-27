/* cwa.js — 中央氣象署 (CWA) 開放資料 API 的請求，回傳它原本的回應（不改內容）。
   金鑰在請求時才從 localStorage 讀（Sources.readKey），不寫在任何檔案裡。
   失敗時丟出 Error，並帶 source 欄位指出是哪個來源；錯誤訊息不含網址，因此不會洩漏金鑰。 */
(function (global) {
  'use strict';

  function fail(message, cause) {
    var err = new Error(message);
    err.source = global.Sources.CWA.name;
    if (cause) { err.cause = cause; }
    return err;
  }

  function buildUrl(base, params, key) {
    var all = {};
    Object.keys(params).forEach(function (k) { all[k] = params[k]; });
    all[global.Sources.CWA.keyParam] = key;
    var query = Object.keys(all).map(function (k) {
      return encodeURIComponent(k) + '=' + encodeURIComponent(all[k]);
    }).join('&');
    return base + '?' + query;
  }

  // 取一個 CWA 資料集，resolve 為原本的 JSON；任何失敗都丟出帶 source 的 Error
  function getDataset(base, params, key, label, check) {
    var controller = new AbortController();
    var timer = setTimeout(function () { controller.abort(); }, global.Sources.TIMEOUT_MS);

    return fetch(buildUrl(base, params, key), { signal: controller.signal })
      .then(function (res) {
        if (!res.ok) { throw fail(label + '：回應狀態 ' + res.status); }
        return res.json().catch(function (e) { throw fail(label + '：回應不是有效的 JSON', e); });
      })
      .then(function (data) {
        if (!data || typeof data !== 'object' || !check(data)) {
          throw fail(label + '：回應格式不符');
        }
        return data;
      })
      .catch(function (e) {
        if (e && e.source) { throw e; }
        if (e && e.name === 'AbortError') { throw fail(label + '：請求逾時'); }
        throw fail(label + '：網路錯誤', e);
      })
      .then(function (data) { clearTimeout(timer); return data; },
            function (e) { clearTimeout(timer); throw e; });
  }

  function hasForecast(d) {
    return !!(d.records && Array.isArray(d.records.Locations) && d.records.Locations.length);
  }

  function hasObservation(d) {
    return !!(d.records && Array.isArray(d.records.Station));
  }

  // 回傳 Promise，resolve 為 { forecast, observation }，兩者都是 CWA 原本的 JSON
  function fetchCwa() {
    var cwa = global.Sources.CWA;
    var key = global.Sources.readKey();
    if (!key) {
      return Promise.reject(fail('尚未輸入金鑰'));
    }
    return Promise.all([
      getDataset(cwa.forecastUrl, { format: 'JSON' }, key, '未來一週預報', hasForecast),
      getDataset(cwa.observationUrl, { format: 'JSON', StationId: cwa.stationId }, key, '現在觀測', hasObservation)
    ]).then(function (parts) {
      return { forecast: parts[0], observation: parts[1] };
    });
  }

  global.Cwa = { fetch: fetchCwa };
})(window);

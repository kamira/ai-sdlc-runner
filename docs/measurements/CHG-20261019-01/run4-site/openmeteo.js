/* openmeteo.js — Open-Meteo 的請求，回傳它原本的回應（不改內容）。
   失敗時丟出 Error，並帶 source 欄位指出是哪個來源；不回傳任何備用數字。 */
(function (global) {
  'use strict';

  function fail(message, cause) {
    var err = new Error(message);
    err.source = global.Sources.OPEN_METEO.name;
    if (cause) { err.cause = cause; }
    return err;
  }

  function buildUrl() {
    var src = global.Sources.OPEN_METEO;
    var query = Object.keys(src.params).map(function (k) {
      return encodeURIComponent(k) + '=' + encodeURIComponent(src.params[k]);
    }).join('&');
    return src.url + '?' + query;
  }

  // 回傳 Promise，resolve 為 Open-Meteo 原本的 JSON
  function fetchOpenMeteo() {
    var controller = new AbortController();
    var timer = setTimeout(function () { controller.abort(); }, global.Sources.TIMEOUT_MS);

    return fetch(buildUrl(), { signal: controller.signal })
      .then(function (res) {
        if (!res.ok) { throw fail('回應狀態 ' + res.status); }
        return res.json().catch(function (e) { throw fail('回應不是有效的 JSON', e); });
      })
      .then(function (data) {
        if (!data || typeof data !== 'object' || !data.current || !data.hourly || !data.daily) {
          throw fail('回應格式不符');
        }
        return data;
      })
      .catch(function (e) {
        if (e && e.source) { throw e; }
        if (e && e.name === 'AbortError') { throw fail('請求逾時'); }
        throw fail('網路錯誤', e);
      })
      .then(function (data) { clearTimeout(timer); return data; },
            function (e) { clearTimeout(timer); throw e; });
  }

  global.OpenMeteo = { fetch: fetchOpenMeteo };
})(window);

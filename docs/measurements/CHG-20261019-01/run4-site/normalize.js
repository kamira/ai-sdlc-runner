/* normalize.js — 把兩個來源的回應整理成同一種格式，並負責數字與時間的顯示格式。
   統一格式：
   {
     source:  '來源名稱',
     fetchedAt: Date,
     current: { time: 'YYYY-MM-DDTHH:mm' | null, temperature: 數字|null, humidity: 數字|null,
                weatherCode: 數字|null, windSpeed: 數字|null },
     daily:   [ { date: 'YYYY-MM-DD', max: 數字|null, min: 數字|null, rain: 數字|null } ],
     hourly:  [ { time: 'YYYY-MM-DDTHH:mm', temperature: 數字 } ]   // 只含今天；來源沒有就是空陣列
   }
   缺值一律是 null（顯示成「—」），不補、不猜、不用備用數字。
   格式不符時丟出帶 source 的 Error。 */
(function (global) {
  'use strict';

  var MISSING = '—';
  var WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六'];
  // CWA 用 -99 等負的極端值代表缺測
  var CWA_MISSING_BELOW = -90;
  // 以座標所在的信義區作為 CWA 預報的行政區
  var CWA_DISTRICT = '信義區';

  function fail(sourceName, message) {
    var err = new Error(message);
    err.source = sourceName;
    return err;
  }

  // 轉成有限數字，否則 null
  function toNumber(v) {
    if (v === null || v === undefined || v === '' || typeof v === 'boolean') { return null; }
    var n = typeof v === 'number' ? v : Number(String(v).trim());
    return isFinite(n) ? n : null;
  }

  function cwaNumber(v) {
    var n = toNumber(v);
    return (n === null || n <= CWA_MISSING_BELOW) ? null : n;
  }

  function dateOf(timeStr) {
    return typeof timeStr === 'string' && /^\d{4}-\d{2}-\d{2}/.test(timeStr) ? timeStr.slice(0, 10) : null;
  }

  function hhmmOf(timeStr) {
    var m = /T(\d{2}:\d{2})/.exec(timeStr || '');
    return m ? m[1] : null;
  }

  /* ---------- Open-Meteo ---------- */

  function fromOpenMeteo(raw, fetchedAt) {
    var name = global.Sources.OPEN_METEO.name;
    var cur = raw && raw.current, d = raw && raw.daily, h = raw && raw.hourly;
    if (!cur || !d || !h || !Array.isArray(d.time) || !Array.isArray(h.time) || !Array.isArray(h.temperature_2m)) {
      throw fail(name, '回應格式不符');
    }
    ['temperature_2m_max', 'temperature_2m_min', 'precipitation_probability_max'].forEach(function (k) {
      if (!Array.isArray(d[k]) || d[k].length !== d.time.length) { throw fail(name, '回應格式不符'); }
    });
    if (h.temperature_2m.length !== h.time.length) { throw fail(name, '回應格式不符'); }

    var today = dateOf(cur.time);
    if (!today) { throw fail(name, '回應格式不符'); }

    var daily = d.time.map(function (date, i) {
      return {
        date: date,
        max: toNumber(d.temperature_2m_max[i]),
        min: toNumber(d.temperature_2m_min[i]),
        rain: toNumber(d.precipitation_probability_max[i])
      };
    });

    var hourly = [];
    h.time.forEach(function (t, i) {
      var temp = toNumber(h.temperature_2m[i]);
      if (dateOf(t) === today && temp !== null) { hourly.push({ time: t, temperature: temp }); }
    });

    return {
      source: name,
      fetchedAt: fetchedAt,
      current: {
        time: cur.time,
        temperature: toNumber(cur.temperature_2m),
        humidity: toNumber(cur.relative_humidity_2m),
        weatherCode: toNumber(cur.weather_code),
        windSpeed: toNumber(cur.wind_speed_10m)
      },
      daily: daily,
      hourly: hourly
    };
  }

  /* ---------- CWA ---------- */

  // 取出元素 ElementValue[0] 中第一個可轉成數字的值
  function firstValue(slot) {
    var ev = slot && slot.ElementValue;
    var obj = Array.isArray(ev) ? ev[0] : ev;
    if (!obj || typeof obj !== 'object') { return null; }
    var keys = Object.keys(obj);
    for (var i = 0; i < keys.length; i++) {
      var n = cwaNumber(obj[keys[i]]);
      if (n !== null) { return n; }
    }
    return null;
  }

  function findElement(elements, names) {
    for (var i = 0; i < elements.length; i++) {
      if (names.indexOf(elements[i].ElementName) !== -1) { return elements[i]; }
    }
    return null;
  }

  // 把某元素各時段的值依日期彙整（pick: Math.max / Math.min）
  function byDate(element, pick) {
    var out = {};
    if (!element || !Array.isArray(element.Time)) { return out; }
    element.Time.forEach(function (slot) {
      var date = dateOf(slot.StartTime || slot.DataTime);
      var v = firstValue(slot);
      if (!date || v === null) { return; }
      out[date] = (out[date] === undefined) ? v : pick(out[date], v);
    });
    return out;
  }

  function fromCwa(raw, fetchedAt) {
    var name = global.Sources.CWA.name;
    var locations = raw && raw.forecast && raw.forecast.records && raw.forecast.records.Locations;
    var stations = raw && raw.observation && raw.observation.records && raw.observation.records.Station;
    if (!Array.isArray(locations) || !locations[0] || !Array.isArray(locations[0].Location) || !Array.isArray(stations)) {
      throw fail(name, '回應格式不符');
    }

    var place = null;
    locations[0].Location.forEach(function (l) { if (l.LocationName === CWA_DISTRICT) { place = l; } });
    if (!place || !Array.isArray(place.WeatherElement)) { throw fail(name, '預報中找不到' + CWA_DISTRICT); }

    var els = place.WeatherElement;
    var maxEl = findElement(els, ['最高溫度', 'MaxT']);
    var minEl = findElement(els, ['最低溫度', 'MinT']);
    var popEl = findElement(els, ['12小時降雨機率', '3小時降雨機率', 'PoP12h', 'PoP6h']);
    if (!maxEl || !minEl) { throw fail(name, '預報缺少最高或最低溫'); }

    var maxBy = byDate(maxEl, Math.max);
    var minBy = byDate(minEl, Math.min);
    var popBy = byDate(popEl, Math.max);

    var dates = Object.keys(maxBy).concat(Object.keys(minBy), Object.keys(popBy))
      .filter(function (x, i, a) { return a.indexOf(x) === i; }).sort();
    if (!dates.length) { throw fail(name, '預報沒有任何日期資料'); }

    var daily = dates.slice(0, 7).map(function (date) {
      return {
        date: date,
        max: maxBy[date] === undefined ? null : maxBy[date],
        min: minBy[date] === undefined ? null : minBy[date],
        rain: popBy[date] === undefined ? null : popBy[date]
      };
    });

    var station = null;
    stations.forEach(function (s) { if (s.StationId === global.Sources.CWA.stationId) { station = s; } });
    if (!station || !station.WeatherElement) { throw fail(name, '觀測中找不到測站 ' + global.Sources.CWA.stationId); }
    var we = station.WeatherElement;
    var obsTime = station.ObsTime && station.ObsTime.DateTime;

    return {
      source: name,
      fetchedAt: fetchedAt,
      current: {
        time: typeof obsTime === 'string' ? obsTime : null,
        temperature: cwaNumber(we.AirTemperature),
        humidity: cwaNumber(we.RelativeHumidity),
        weatherCode: null,
        windSpeed: cwaNumber(we.WindSpeed)
      },
      daily: daily,
      // CWA 一週預報沒有逐時氣溫；不拼湊，留空讓曲線顯示「此來源沒有逐時資料」
      hourly: []
    };
  }

  // source: Sources.OPEN_METEO 或 Sources.CWA；raw 是對應 fetch 模組的回傳
  function normalize(source, raw, fetchedAt) {
    var when = fetchedAt || new Date();
    return source.id === global.Sources.CWA.id ? fromCwa(raw, when) : fromOpenMeteo(raw, when);
  }

  /* ---------- 顯示格式 ---------- */

  function pad(n) { return (n < 10 ? '0' : '') + n; }

  function formatTemp(v) {
    return v === null || v === undefined ? MISSING : (Math.round(v * 10) / 10).toFixed(1) + '°C';
  }

  function formatPercent(v) {
    return v === null || v === undefined ? MISSING : Math.round(v) + '%';
  }

  // 'YYYY-MM-DD' → 'MM/DD（週X）'，不經過本機時區
  function formatDay(dateStr) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateStr || '');
    if (!m) { return MISSING; }
    var wd = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])).getUTCDay();
    return m[2] + '/' + m[3] + '（週' + WEEKDAYS[wd] + '）';
  }

  // 'YYYY-MM-DDTHH:mm' → 'HH:mm'
  function formatHour(timeStr) {
    return hhmmOf(timeStr) || MISSING;
  }

  // Date → 'YYYY-MM-DD HH:mm:ss'（使用者本機時間）
  function formatFetchedAt(date) {
    if (!(date instanceof Date) || isNaN(date.getTime())) { return MISSING; }
    return date.getFullYear() + '-' + pad(date.getMonth() + 1) + '-' + pad(date.getDate()) + ' ' +
      pad(date.getHours()) + ':' + pad(date.getMinutes()) + ':' + pad(date.getSeconds());
  }

  global.Normalize = {
    MISSING: MISSING,
    normalize: normalize,
    formatTemp: formatTemp,
    formatPercent: formatPercent,
    formatDay: formatDay,
    formatHour: formatHour,
    formatFetchedAt: formatFetchedAt
  };
})(window);

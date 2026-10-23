/* now.js — 中間的「現在」區塊：氣溫與濕度。
   Now.render(data)  data 是 Normalize.normalize 的結果；缺值顯示「—」。
   Now.clear()       清空區塊（錯誤或載入時由 app.js 呼叫）。 */
(function (global) {
  'use strict';

  function el(tag, className, text) {
    var node = document.createElement(tag);
    node.className = className;
    node.textContent = text;
    return node;
  }

  function section() {
    return document.getElementById('now');
  }

  function clear() {
    var box = section();
    if (box) { box.textContent = ''; }
  }

  function render(data) {
    var box = section();
    if (!box) { return; }
    var N = global.Normalize;
    var cur = data.current;

    box.textContent = '';
    box.appendChild(el('div', 'now-temp', N.formatTemp(cur.temperature)));
    box.appendChild(el('div', 'now-humidity', '濕度 ' + N.formatPercent(cur.humidity)));

    var time = cur.time ? (N.formatDay(cur.time.slice(0, 10)) + ' ' + N.formatHour(cur.time)) : N.MISSING;
    box.appendChild(el('div', 'now-extra', '觀測時間 ' + time));
  }

  global.Now = { render: render, clear: clear };
})(window);

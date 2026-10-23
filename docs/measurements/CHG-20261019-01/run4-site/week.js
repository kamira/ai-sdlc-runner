/* week.js — 七天清單：每天的最高溫、最低溫和降雨機率。
   Week.render(data)  data 是 Normalize.normalize 的結果；缺值顯示「—」。
   Week.clear()       清空區塊（錯誤或載入時由 app.js 呼叫）。 */
(function (global) {
  'use strict';

  function el(tag, className, text) {
    var node = document.createElement(tag);
    node.className = className;
    node.textContent = text;
    return node;
  }

  function section() {
    return document.getElementById('week');
  }

  function clear() {
    var box = section();
    if (box) { box.textContent = ''; }
  }

  function render(data) {
    var box = section();
    if (!box) { return; }
    var N = global.Normalize;

    box.textContent = '';
    var title = document.createElement('h2');
    title.textContent = '七天預報';
    box.appendChild(title);

    var list = document.createElement('ul');
    data.daily.forEach(function (day) {
      var li = document.createElement('li');
      li.appendChild(el('span', 'day-name', N.formatDay(day.date)));
      li.appendChild(el('span', 'day-high', '高 ' + N.formatTemp(day.max)));
      li.appendChild(el('span', 'day-low', '低 ' + N.formatTemp(day.min)));
      li.appendChild(el('span', 'day-rain', '降雨 ' + N.formatPercent(day.rain)));
      list.appendChild(li);
    });
    box.appendChild(list);
  }

  global.Week = { render: render, clear: clear };
})(window);

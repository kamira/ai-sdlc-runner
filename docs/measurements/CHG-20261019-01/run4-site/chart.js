/* chart.js — 今天每小時氣溫的曲線（SVG，不用外部函式庫）。
   Chart.render(data)  data 是 Normalize.normalize 的結果；只畫 data.hourly 的真實點。
                       沒有逐時資料時顯示說明文字，不畫任何線。
   Chart.clear()       清空區塊（錯誤或載入時由 app.js 呼叫）。 */
(function (global) {
  'use strict';

  var SVG_NS = 'http://www.w3.org/2000/svg';
  var W = 640, H = 240;
  var PAD = { left: 48, right: 16, top: 16, bottom: 28 };

  function svgEl(tag, attrs) {
    var node = document.createElementNS(SVG_NS, tag);
    Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    return node;
  }

  function section() {
    return document.getElementById('chart');
  }

  function clear() {
    var box = section();
    if (box) { box.textContent = ''; }
  }

  function minutesOf(timeStr) {
    var m = /T(\d{2}):(\d{2})/.exec(timeStr || '');
    return m ? (+m[1]) * 60 + (+m[2]) : null;
  }

  function text(x, y, anchor, str) {
    var t = svgEl('text', { x: x, y: y, 'text-anchor': anchor });
    t.textContent = str;
    return t;
  }

  function render(data) {
    var box = section();
    if (!box) { return; }
    var N = global.Normalize;

    box.textContent = '';
    var title = document.createElement('h2');
    title.textContent = '今天每小時氣溫';
    box.appendChild(title);

    var points = [];
    (data.hourly || []).forEach(function (p) {
      var x = minutesOf(p.time);
      if (x !== null && typeof p.temperature === 'number' && isFinite(p.temperature)) {
        points.push({ minutes: x, time: p.time, temperature: p.temperature });
      }
    });

    if (!points.length) {
      var none = document.createElement('p');
      none.className = 'chart-empty';
      none.textContent = '此來源（' + data.source + '）沒有逐時氣溫資料。';
      box.appendChild(none);
      return;
    }

    var lo = Math.min.apply(null, points.map(function (p) { return p.temperature; }));
    var hi = Math.max.apply(null, points.map(function (p) { return p.temperature; }));
    lo = Math.floor(lo); hi = Math.ceil(hi);
    if (hi === lo) { hi += 1; }

    var plotW = W - PAD.left - PAD.right, plotH = H - PAD.top - PAD.bottom;
    function px(minutes) { return PAD.left + (minutes / (24 * 60 - 60)) * plotW; }
    function py(t) { return PAD.top + (1 - (t - lo) / (hi - lo)) * plotH; }

    var svg = svgEl('svg', { viewBox: '0 0 ' + W + ' ' + H, role: 'img', 'aria-label': '今天每小時氣溫曲線' });

    // 橫向刻度：最低、中間、最高
    [lo, (lo + hi) / 2, hi].forEach(function (t) {
      var y = py(t);
      svg.appendChild(svgEl('line', { class: 'tick', x1: PAD.left, x2: W - PAD.right, y1: y, y2: y }));
      svg.appendChild(text(PAD.left - 6, y + 4, 'end', N.formatTemp(t)));
    });
    svg.appendChild(svgEl('line', { class: 'axis', x1: PAD.left, x2: W - PAD.right, y1: H - PAD.bottom, y2: H - PAD.bottom }));

    // 時間刻度：每 6 小時
    [0, 6, 12, 18, 23].forEach(function (h) {
      var x = px(h * 60);
      svg.appendChild(svgEl('line', { class: 'tick', x1: x, x2: x, y1: H - PAD.bottom, y2: H - PAD.bottom + 4 }));
      svg.appendChild(text(x, H - 8, 'middle', (h < 10 ? '0' : '') + h + ':00'));
    });

    var d = points.map(function (p, i) {
      return (i ? 'L' : 'M') + px(p.minutes).toFixed(1) + ' ' + py(p.temperature).toFixed(1);
    }).join(' ');
    svg.appendChild(svgEl('path', { class: 'line', d: d }));

    // 每個點附上提示（時間與氣溫）
    points.forEach(function (p) {
      var dot = svgEl('circle', { class: 'dot', cx: px(p.minutes), cy: py(p.temperature), r: 3, fill: 'var(--accent)' });
      var tip = svgEl('title', {});
      tip.textContent = N.formatHour(p.time) + '  ' + N.formatTemp(p.temperature);
      dot.appendChild(tip);
      svg.appendChild(dot);
    });

    box.appendChild(svg);
  }

  global.Chart = { render: render, clear: clear };
})(window);

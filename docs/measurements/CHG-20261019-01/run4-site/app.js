/* app.js — 進入點：串起以上模組，處理載入中與錯誤狀態。
   依 Sources.chooseSource() 選來源 → 請求 → Normalize.normalize → 畫三個區塊。
   任何失敗都只顯示錯誤與失敗的來源，不顯示任何數字，也不換用備用資料。 */
(function (global) {
  'use strict';

  var loadSeq = 0;

  function byId(id) { return document.getElementById(id); }

  function clearBlocks() {
    global.Now.clear();
    global.Week.clear();
    global.Chart.clear();
  }

  function setText(id, value) {
    var node = byId(id);
    if (node) { node.textContent = value; }
  }

  function showLoading() {
    byId('status-error').hidden = true;
    byId('status-loading').hidden = false;
    clearBlocks();
    setText('source-name', global.Normalize.MISSING);
    setText('fetched-at', global.Normalize.MISSING);
  }

  function showError(sourceName, message) {
    var box = byId('status-error');
    byId('status-loading').hidden = true;
    clearBlocks();
    box.textContent = '無法取得資料。來源：' + sourceName + '；原因：' + message;
    box.hidden = false;
    setText('source-name', sourceName + '（失敗）');
    setText('fetched-at', global.Normalize.MISSING);
  }

  function fetchRaw(source) {
    return source.id === global.Sources.CWA.id ? global.Cwa.fetch() : global.OpenMeteo.fetch();
  }

  function load() {
    var seq = ++loadSeq;
    var source = global.Sources.chooseSource();
    showLoading();

    fetchRaw(source)
      .then(function (raw) {
        return global.Normalize.normalize(source, raw, new Date());
      })
      .then(function (data) {
        if (seq !== loadSeq) { return; }
        byId('status-loading').hidden = true;
        byId('status-error').hidden = true;
        global.Now.render(data);
        global.Chart.render(data);
        global.Week.render(data);
        setText('source-name', data.source);
        setText('fetched-at', global.Normalize.formatFetchedAt(data.fetchedAt));
      })
      .catch(function (e) {
        if (seq !== loadSeq) { return; }
        showError((e && e.source) || source.name, (e && e.message) || '未知錯誤');
      });
  }

  function bindKeyControls() {
    var input = byId('cwa-key');
    var save = byId('cwa-save');
    var clear = byId('cwa-clear');

    if (save) {
      save.addEventListener('click', function () {
        // 輸入框的值只交給 Sources.saveKey，不顯示、不回填
        var ok = global.Sources.saveKey(input ? input.value : '');
        if (input) { input.value = ''; }
        if (ok) { load(); }
      });
    }
    if (clear) {
      clear.addEventListener('click', function () {
        global.Sources.clearKey();
        if (input) { input.value = ''; }
        load();
      });
    }
  }

  function start() {
    bindKeyControls();
    load();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})(window);

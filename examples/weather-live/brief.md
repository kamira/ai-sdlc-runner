做一個台北的一週氣象單頁網站，座標 25.0330°N 121.5654°E。畫面中間顯示現在的氣溫和濕度；七天預報要有每天的最高溫、最低溫和降雨機率；另外把今天每小時的氣溫畫成一條曲線。

## 資料：頁面在瀏覽器裡、執行時向外取得真實資料

- 預設來源是 Open-Meteo，不需要金鑰：
  `https://api.open-meteo.com/v1/forecast`，查詢參數為
  `latitude=25.0330`、`longitude=121.5654`、
  `current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m`、
  `hourly=temperature_2m`、
  `daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max`、
  `timezone=Asia/Taipei`、`forecast_days=7`。
- 選用來源是中央氣象署（CWA）開放資料 API，只用 API，不爬網頁、不下載檔案：
  `https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-D0047-063`（臺北市未來一週預報）和
  `https://opendata.cwa.gov.tw/api/v1/rest/datastore/O-A0003-001`（現在觀測，測站 `466920`），
  金鑰放在 `Authorization` 查詢參數。只有在使用者於頁面的密碼欄位輸入金鑰時才使用；
  金鑰只存在這個瀏覽器的 localStorage。沒有金鑰就用 Open-Meteo。
- **任何檔案裡都不可以出現金鑰**：不寫進程式、設定、範例或說明，也不印在畫面或網址顯示上。
- 頁面要標明「資料來源」是哪一個，以及「取得時間」。
- 請求失敗（網路、逾時、非 2xx、格式不對）時，畫面要有看得見的錯誤狀態，並指出是哪個來源失敗；
  **絕對不可以顯示編造的數字或備用數字**。

## 模組：十個檔案，各自獨立，一次建一個，都放在 `site/` 底下

1. `index.html` — 頁面骨架：版面區塊、載入各模組的 script，以及標明來源與取得時間的位置
2. `styles.css` — 版面與樣式，包含載入中與錯誤狀態的樣子
3. `sources.js` — 來源設定：兩個來源的名稱、網址與查詢參數，以及依有無金鑰選用哪一個
4. `openmeteo.js` — Open-Meteo 的請求，回傳它原本的回應
5. `cwa.js` — CWA 的請求（金鑰從 localStorage 讀），回傳它原本的回應
6. `normalize.js` — 把兩個來源的回應整理成同一種格式，並負責數字與時間的顯示格式
7. `now.js` — 中間的「現在」區塊：氣溫與濕度
8. `week.js` — 七天清單：每天的最高溫、最低溫和降雨機率
9. `chart.js` — 今天每小時氣溫的曲線
10. `app.js` — 進入點：串起以上模組，處理載入中與錯誤狀態

## 限制

- 沒有建置步驟，不用任何外部函式庫，全部是瀏覽器直接打開的純檔案（用 `<script src>` 依序載入，
  不要用需要伺服器的 ES module）。
- 一次只做一個模組，每個模組自己能被讀懂；後面的模組可以呼叫前面模組已經有的東西。
- 除了上面兩個 API 之外，頁面不得向任何其他網址發出請求。

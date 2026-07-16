# Issue: gpss_web_search 的 patDB 國別限縮未生效

- **日期**: 2026-07-16
- **狀態**: observing（次要精度問題，不阻塞核心功能）
- **來源**: plan `patentmcp_gpss-web-boolean-search` 實作 t6 端到端驗證

## 症狀

`gpss_web_search(expr="(heartbeat)@TI", databases=["USA"], ...)` 指定單一國別 `USA`，
但 `ttsserv_watch` 回應仍含全部 24 個資料庫分項（本國/美國/日本/歐洲/韓國/大陸/WIPO/東南亞/其他），
`grand_total: 252488`。代表 POST 的 `patDB=USA` 參數**未真正限縮**檢索範圍到單一國別。

## 初步假設

1. gpss3 網頁路徑的國別選取不走 `patDB` POST 欄位，而是另一組欄位（如各庫的 checkbox `_DB_xxx`）。
2. 抓圖 code（`_gpss_download_representative_figure_impl`）不帶國別限縮，所以既有基礎設施沒有此欄位的先例可複用。
3. 網頁路徑的國別限縮可能需先在 session 設定「檢索資料庫範圍」state，再 POST。

## 影響

- **不影響**：核心檢索計數、布林式承載、日期限縮、各庫命中數解析（都已驗證真實生效）。
- **影響**：使用者若想只看單一國別母數，目前回全部 24 庫（但各庫命中數是分開的，使用者仍可自行讀取目標國別欄位）。

## 待探

- dump gpss3 布林檢索頁的資料庫選取表單元素，確認網頁路徑的國別限縮真實欄位名/機制。
- 對照官方「限縮檢索」功能的 POST payload。

## 治理狀態（2026-07-16 更新）

- **RCA 定案（Playwright 鐵證）**：gpss3 布林檢索表單**無任何選庫 checkbox、無 patDB 欄位**；`patDB` POST 是從 REST API 錯誤移植的幽靈參數，網頁直接忽略——所以 `patDB=USA` 限縮不生效、回全 24 庫。庫範圍實由**登入 session 的庫勾選 state** 決定。
- **已開 plan 統一治理**：`plans/patentmcp_gpss-web-login-db-scope`（designed）—— 核心根因（agent BR `BR_20260716_gpss4_adv_search_missing_peruser_database_scope_config` 正確定位）：gpss4/web 庫範圍是**帳號層級 per-user server-side config**（切設定頁勾庫存檔），非 query 參數也非 patDB。plan 補 `set_search_databases` + tool `databases` 參數。本 issue 的 gpss3 限縮不生效屬同源（`databases` 雙向映射）一併治理。

## workaround（現況可用）

回應的 `totals` 已把各庫命中數分開列出（`{美國公開: 7870, 美國公告: 10537, ...}`），
呼叫端可自行加總目標國別欄位，不需依賴 patDB 限縮。

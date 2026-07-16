# Proposal: patentmcp_gpss-web-login-db-scope

## Why

- **BR_20260716**: `gpss_web_search`(gpss3) 與 `gpss4_advanced_search` 兩條零 API 額度的 web 檢索路徑，對大陸公開/公告（CNA/CNB）一律回 0——但同軸檢索式在 REST 端 `patent_bulk(source=gpss, databases=["CNA","CNB"])` 撈到 455 筆 CN 實體書目，人類手動登入 TIPO GPSS 網頁查同式子亦有大量命中。
- **根因（Playwright 鐵證定案）**: gpss 網頁的檢索庫範圍由**登入 session 的預設/設定庫勾選 state** 決定；code 送的 `patDB` POST 欄位在網頁布林檢索表單**根本不存在**（幽靈參數，被伺服器忽略）。code 走的**無密碼匿名 handshake session** 的預設庫集**不含大陸公開/公告** → CN 回 0。
- **契約破裂**: 現行 code 的 DD-2「country via patDB param」是把 REST API 的 `patDB` 語義**錯誤移植**到 web 路徑的未驗證假設。此假設必須被 supersede。
- **價值**: web 路徑的核心價值是「零 API 額度做 CN-heavy landscape 的檢索計數/harvest」；此缺陷使 CN 池在 REST 時段額度耗盡後**無零額度 fallback**，只能枯等額度重置。

## Original Requirement Wording (Baseline)

- "處理BR。人類登入模式爬不到CN專利？這絕對是bug"
- "所以reporter agent他用錯工具了，採匿名登入就抓不到CN？"

## Requirement Revision History

- 2026-07-16: initial draft created via plan-init.ts
- 2026-07-16: RCA 定案（Playwright 帶帳號登入取證）——匿名 handshake session 預設庫集不含 CN，`patDB` 對網頁無效，登入 member 頁才有「檢索及顯示設定」選庫入口。

## Effective Requirement Description

1. web 路徑（gpss3 `_gpss_web_search_impl` 與 gpss4 `_submit_query`）必須能對大陸公開/公告（CNA/CNB）取得與 REST 端 `databases=["CNA","CNB"]` 一致的命中覆蓋。
2. web 路徑改走**登入 session**（GPSS4 member 帳號），並在檢索前設定 session 的庫範圍 state 使其納入 CN（含使用者指定的 `databases`）。
3. 移除/廢棄無效的 `patDB` POST 欄位假設（supersede DD-2）；改用網頁真實的庫範圍設定機制。
4. `databases` 參數在 web 路徑必須真實映射到網頁 session 庫範圍（既能納入 CN，也能正確限縮——連帶治理姊妹 issue `patdb_country_narrowing`）。

## Scope

### IN
- gpss3 `_gpss_web_search_impl`（`patents.py:2909-3063`）的庫範圍機制重構：改走登入 session + 檢索前設庫範圍 state。
- gpss4 `gpss4_advanced_search` / `adv_search.py harvest` 的庫範圍納入：確保登入帳號 session 預設或設定含 CN。
- supersede DD-2（`patDB` for web）；記錄真實庫範圍設定的 POST 欄位/機制。
- `databases` 參數在兩條 web 路徑的正確映射（納入 + 限縮雙向）。

### OUT
- REST 端 `patent_bulk` / `GPSSClient._build_query` 的 patDB 邏輯（REST 端 patDB 有效，不動）。
- gpss 圖式/PDF 抓取路徑（`_gpss_download_representative_figure_impl` 等，與檢索庫範圍無關）。
- totals 主計數行解析（姊妹 issue `totals_missing_main_count_line`，正交缺陷，另案）。

## Non-Goals

- 不改 REST API 檢索行為。
- 不新增任何 silent fallback（使用者天條）：登入失敗 / 庫範圍設定失敗一律 fail-fast 顯式報錯，不靜默降級到匿名 session 或 REST。

## Constraints

- 登入憑證來自 `GPSS4_USERNAME` / `GPSS4_PASSWORD`（env/.env），複用既有 `GPSS4Session` 登入 state machine（md5-captcha），不重造。
- GPSS4 session state 綁在 URL slot-key token（短命，member 頁 render 當下有效），非純 cookie——庫範圍設定 POST 必須在同一 authed session 內、slot-key 有效期間完成。
- 遵守既有 `SoftScrapePolicy`（per-host serialize + pacing），登入 + 設庫範圍 + 檢索的多次 request 都在 `_GPSS_POLICY.guard()` 內。
- scratch 落 XDG（資安天條），不落 /tmp。

## What Changes

- gpss3 web 檢索：匿名 handshake → 登入 session；`data["patDB"]` 幽靈欄位 → 檢索前設 session 庫範圍 state 的真實機制。
- gpss4 web 檢索：確認/設定登入帳號 session 庫範圍含 CN。
- DD-2 標記 SUPERSEDED；新增 DD 記錄真實庫範圍設定機制。

## Capabilities

### New Capabilities
- web 路徑登入 session 庫範圍設定：檢索前把 session 檢索庫範圍設為含 CN（及使用者指定 databases）。

### Modified Capabilities
- `gpss_web_search`: 匿名 → 登入；`databases` 真實生效（納入 CN）。
- `gpss4_advanced_search`: 庫範圍納入 CN（登入帳號 session 預設/設定）。

## Impact

- 影響 code: `src/patent_mcp_server/patents.py`（`_gpss_web_search_impl`、`gpss_web_search`、`gpss4_advanced_search` 相關 impl）；`src/patent_mcp_server/gpss4/adv_search.py`（`_submit_query` / login flow 複用）；`src/patent_mcp_server/gpss4/session.py`（登入 session 複用）。
- 影響 issue: 治理 BR_20260716（本案）+ `patdb_country_narrowing`（observing）+ 部分關聯 `totals_missing_main_count_line`。
- 影響 KB: supersede DD-2；相關 spec `patentmcp_gpss-web-boolean-search` 的庫範圍設計需同步。

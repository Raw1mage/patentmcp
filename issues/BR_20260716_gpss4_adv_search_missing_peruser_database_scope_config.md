# BR: gpss4_advanced_search 無法鎖國別/庫別 — 缺「切設定頁改 per-user 檢索範圍→存檔→跳回」能力

- **日期**: 2026-07-16
- **狀態**: **fixed（庫範圍核心已 live 驗證）** — plan `plans/patentmcp_gpss-web-login-db-scope`（implementing）；`set_search_databases` + `gpss4_advanced_search databases 參數` + 獨立 `gpss4_set_search_scope` tool 已實作，`dbscope_verify.html` 證實帳號檢索庫精確鎖成 `_20_1_S_CA`+`_20_1_S_CB`。剩 CN 結果頁 pat_no parser 正交缺陷 → `issue_20260716_gpss4_adv_cn_result_page_patno_in_ajax`（observing）
- **嚴重度**: high（阻擋以 gpss4 零額度路徑建「單一國別同源池」——目前只能撈帳號當前預設範圍的跨國混合池）
- **元件**: `src/patent_mcp_server/gpss4/adv_search.py`、`src/patent_mcp_server/gpss4/session.py`、MCP tool `gpss4_advanced_search`
- **提報脈絡**: 異常偵測前案檢索案（`research_anomaly-noncontact-priorart`）CN 池以 gpss4 web 零額度路徑續撈時發現

---

## 症狀

`gpss4_advanced_search` 撈回的結果**混含多國**（TW/JP/WO/CN…），無法限定只查某一國別/庫別。實測：

- `query=(激光雷达 or 摄像 or 图像)@TI,AB and (老人 or 跌倒 or 生命体征)@TI,AB and AD=2024:2024`
  → total=9，結果同時含 TW/JP/WO 與含 CN 語彙摘要案。
- 嘗試在 query 內用 `PD=CN` 限國 → **total=0**（非法語法，gpss4 進階檢索 query 無此欄位碼）。

對「分國同源池」（本案 DD-44 同源鐵律：CN 統計池成員須全部源自 CN 庫）造成阻擋——目前只能撈回跨國混合池，再靠離線層按 `pat_no` 國別前綴分流（本案 DD-64 的離線 workaround），但這無法在**檢索端**確保母體邊界，且混合撈浪費頁數/harvest 成本。

## Root Cause（已從 code + 使用者領域知識定位）

1. **gpss4 進階檢索 query 語法層無國別/庫別限定碼**。合法欄位碼僅 `@TI`/`@AB`/`@CL`（標題/摘要/請求項）、`CS=`（分類）、`AD=`（申請年區間）——見 `adv_search.py:41-43` 官方 field-code 表註解。`PD=`、`databases=` 均不存在，`PD=CN` 被引擎當非法 → 回 0。

2. **國別/庫別是 GPSS4 的 server-side per-user config，不是 query 參數**（使用者領域知識指出）。GPSS4 網頁的檢索資料庫範圍是**帳號層級設定**：使用者需切到「進階檢索設定 / 環境設定頁」→ 勾選要納入的庫（如大陸公開 CNA / 大陸公告 CNB）→ **存檔** → 跳回進階檢索頁，之後該帳號的檢索才會涵蓋所勾的庫。

3. **現有工具未實作這個設定頁環節**。`GPSS4Session`（session.py）只實作 login（md5 CAPTCHA + SSO refresh chain）；`adv_search.py` 的流程是 `login → 讀 member.html 的「進階檢索」tab anchor → GET adv form → POST query → poll job → paginate`（adv_search.py:23-39），**全程不碰任何檢索範圍設定頁**。因此工具永遠用**帳號當前的預設範圍**——使用者若沒在網頁手動勾大陸庫並存檔，工具就查不到 CN（先前誤判為 web 路徑不含 CN 的 bug，已在 `closed/BR_20260716_gpss_web_paths_cn_database_zero_coverage.md` 撤回，真因即此設定範圍問題）。

## 既有機制證據（供實作復用，避免重造輪子）

- `adv_search.py:18-21` docstring 已記載存在「右側 **進階檢索設定** block，落到 `_20_*` 環境頁」——這正是設定頁入口線索（工具目前故意繞開它，只讀左側進階檢索 tab）。
- `GPSS4Session`（session.py）已有完整的 authed httpx client + slot-key 頁面流程能力：`_refresh_chain`（member.html 在此）、`get()`（authed GET + 自動 re-login）、`_dump` pattern。設定頁流程可**直接掛在同一個 authed session** 上，不需新 login。
- slot-key 頁面流程 idiom 已被 adv_search 驗證：每頁 URL 帶短命 slot key（`gpsskm?.<hex>`），從當前頁 HTML extract 再帶到下一 request（adv_search.py:10-16）。設定頁的「改範圍→存檔」POST 應是同一套：GET 設定頁 → parse 表單的 hidden fields（ID/SECU/INFO 類）+ 庫別 checkbox name → POST 勾選 + 存檔按鈕 → 跳回。

## 待逆工的接縫（實作時需實際 GET 設定頁 HTML 才能定案）

以下需 patentmcp 開發時實際登入 + GET `_20_*` 環境頁 dump HTML 才能填實（本案提報者無法自寫爬蟲繞道逆工——零臨時腳本繞道鐵律）：

1. **設定頁 URL / anchor**：從 member.html（`_refresh_chain`）或進階檢索頁，找「進階檢索設定 / 環境設定」的 slot-key anchor（`_20_*`）。
2. **庫別 checkbox 的 form field name**：大陸公開（CNA）/ 大陸公告（CNB）等各庫在設定表單裡的 input name 與 value。
3. **存檔 POST 契約**：action URL、hidden fields（ID/SECU/INFO/TPHC 類）、存檔按鈕的 submit name。
4. **設定是否持久**：存檔後是否寫入帳號、跨 session 保留（若持久，只需設定一次；若 session-scoped，每次 harvest 前須先設定）。

## 治理 plan（2026-07-16）

`plans/patentmcp_gpss-web-login-db-scope`（designed）已把本 BR 的修法設計成 spec：
- **DD-3**: web 庫範圍是帳號層級 per-user server-side config，非 query 參數；補「切設定頁→勾庫→存檔→跳回」環節（對齊本 BR 根因）。
- **DD-6**: `gpss4_advanced_search` 加 `databases: list[str]|None` 參數 + 可選 `gpss4_set_search_scope` tool（對齊本 BR 建議修法）。
- **tasks §1**: live 逆工 `_20_*` 設定頁（checkbox 欄位名 / 存檔 POST 契約 / 持久性），implementing 前置、不可離線推演。
- **tasks §2**: 實作 `set_search_databases(session, dbs)` + tool 參數。
- fail-fast 無 fallback（使用者天條）。

## 建議修法

在 `adv_search.py` / `session.py` 補一個 `set_search_databases(session, dbs: list[str])` 方法（掛在既有 authed `GPSS4Session` 上），實作「GET 設定頁 → 勾選指定庫 → 存檔 POST → 驗證跳回」。並在 `gpss4_advanced_search` tool 加一個 `databases: list[str] | None` 參數：

- `databases=None`（預設）→ 沿用帳號當前範圍（現行行為，back-compat）。
- `databases=["CNA","CNB"]` → harvest 前先呼叫 `set_search_databases` 鎖定，再送 query，實現檢索端分國同源池。

若設定為帳號持久（非 session-scoped），可另加一個獨立 tool `gpss4_set_search_scope(databases)` 讓使用者一次設定、後續 harvest 沿用。

## 與既有 issue 的關係（正交，不重複）

- `closed/BR_20260716_gpss_web_paths_cn_database_zero_coverage.md`（已撤回）：那份誤判 gpss4 對 CN 有 bug，真因就是本 BR 的設定範圍問題——本 BR 是它的正確版根因 + 修法。
- `issue_20260716_gpss_web_patdb_country_narrowing.md`（observing）、`issue_20260716_gpss_web_search_totals_missing_main_count_line.md`（open）：那兩個是 `gpss_web_search`(gpss3) 路徑的限縮/解析問題，與本 BR（gpss4 進階檢索的 per-user 庫範圍設定）正交。

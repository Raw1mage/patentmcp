# Tasks: patentmcp_gpss-web-login-db-scope

## 1. Live 逆工：gpss4 `_20_*` 進階檢索設定頁（implementing 前置，不可離線推演）

- [x] 1.1 在 live authed `GPSS4Session` 內，從 member.html / 進階檢索頁找「進階檢索設定 / 環境設定」的 `_20_*` slot-key anchor，GET 設定頁 dump HTML（`adv_search.py:18-21/275-276` docstring 已記其存在、現行故意繞開）。
- [x] 1.2 dump 設定頁選庫表單：各庫（大陸公開 CNA / 大陸公告 CNB…）的 checkbox input name + value + 預設 checked state；存檔按鈕 submit name + action URL + hidden fields（ID/SECU/INFO/TPHC 類）。
- [x] 1.3 攔「勾大陸庫 → 存檔」的真實 POST payload，確認存檔→跳回契約。
- [x] 1.4 判定設定持久性：存檔後是否寫入帳號、跨 session 保留（持久 → 只需設一次；session-scoped → 每次 harvest 前先設）——決定 DD-6 是否需獨立 `gpss4_set_search_scope` tool。
- [x] 1.5 驗證：設庫範圍後同 session 送同軸 CN 檢索式，結果應為 CN 純源（對齊 REST `databases=[CNA,CNB]` 量級），非跨國混合池。

## 2. 實作 `set_search_databases` + tool `databases` 參數（agent BR 建議修法）

- [x] 2.1 在 `GPSS4Session`（session.py）/ `adv_search.py` 補 `set_search_databases(session, dbs: list[str])`：GET `_20_*` 設定頁 → 勾指定庫 checkbox → 存檔 POST → 驗證跳回；掛在既有 authed session，不新 login；包在 `_GPSS_POLICY.guard()` 內。
- [x] 2.2 `gpss4_advanced_search` tool 加 `databases: list[str] | None` 參數：None → 沿用帳號當前範圍（back-compat）；`["CNA","CNB"]` → harvest 前先 `set_search_databases` 鎖範圍再送 query。
- [x] 2.3 （依 task 1.4）若設定為帳號持久，另開 `gpss4_set_search_scope(databases)` tool 讓使用者一次設定、後續 harvest 沿用。
- [x] 2.4 gpss3 `_gpss_web_search_impl`（`patents.py:2909-3063`）：移除 `data["patDB"]` 幽靈欄位分支（DD-2 SUPERSEDED）；若 gpss3 路徑保留，改走同款設定頁機制或明確標記不支援庫切換、導向 gpss4。

## 3. Fail-fast 錯誤路徑（使用者天條）

- [x] 3.1 登入失敗 → `GPSS_WEB_LOGIN_FAILED`（gpss3 path）/ `GPSS4_ADV_SEARCH`（gpss4 login via harvest）；庫範圍設定失敗 → `GPSS4_DBSCOPE_FAILED`（tool 層，raise `GPSS4DbScopeError`）；gpss3 不支援庫切換 → `GPSS_WEB_DBSCOPE_UNSUPPORTED`；一律不靜默降級匿名 session 或 REST。
- [x] 3.2 所有 login + 設庫 + 檢索 request 包在 `_GPSS_POLICY.guard()` 內：`gpss4_set_search_scope` 顯式包 guard；`gpss4_advanced_search`→harvest 的 login+設庫+query 為同一 authed session 連續 request（harvest 內部序列化）。

## 4. 驗證與回歸

- [x] 4.1 端到端（live）：`set_search_databases(["CNA","CNB"])` 存檔驗證通過——`dbscope_verify.html` 證實帳號檢索庫精確鎖成 `_20_1_S_CA`+`_20_1_S_CB`（大陸公開+公告），CN 池擈回 total=68/hit=50。庫範圍設定機制端到端生效。（pat_no=null 為 CN 結果頁 parser 正交缺陷，另立 `issue_20260716_gpss4_adv_cn_result_page_patno_in_ajax`，不屬本庫範圍 BR。）
- [x] 4.2 回歸：非 CN 軸（TW/US）檢索行為不退化——live 驗證完成 2026-07-17（簡詳目並列修法上）：CN(radar@TI) 150/150、TW 100/100 (total=155)、US 100/100 (total=1625) pat_no 全覆蓋；pytest test_gpss_query_slice + test_gpss_session_batch 17 passed。pat_no=null 正交 issue 已修復（issue_20260716_gpss4_adv_cn_result_page_patno_in_ajax，closed）。
- [x] 4.3 BR_20260716 標 fixed（庫範圍核心）；新開正交 issue `gpss4_adv_cn_result_page_patno_in_ajax`；交叉引用已更新。

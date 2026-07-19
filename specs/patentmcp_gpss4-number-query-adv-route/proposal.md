# Proposal: patentmcp_gpss4-number-query-adv-route

## Why

GPSS4 登入模式的號碼查詢（`gpss4_resolve_appnos` / `gpss4_folder_search` /
`gpss4_folder_mark`，全走 `folder.py` 的 member-area 標記清單路徑）對「已命中」
的申請號**抽不到公開/公告號**：`search_number` 回 `count=1` 命中，但
`_extract_rows` 得 0 rows、結果頁 HTML 內連一個 `TW\d{6,}` 都沒有。本案 TW 99 筆
硬骨頭 appno 因此 resolved=0，資料呈系統性假陰。

BR_20260719（本 BR）原診斷此為「查詢帳號的搜尋 DB scope + 結果頁輸出欄位未在設定頁
預先啟動」，要求硬化成 tool 內建的 `_ensure_query_ready` 前置 routine。

**但 2026-07-19 live recon 推翻了此 root-cause 假設**（見 design.md DD-1）：
輸出欄位（`_20_20_S_P1` 公開/公告號）本來就已勾選；設了 DB scope（TWA+TWB）後重查
known-item `TW202223848` 仍 `_extract_rows=0`。真因是 **folder 標記清單路徑本身不
render 專利號**——GPSS4 只在「進階檢索 + 簡詳目並列檢視」才 render 專利號欄位，而
`adv_search.harvest()`（BR_20260716 已修好）正是走這條路徑並含 `_enter_dual_view`。

## Original Requirement Wording (Baseline)

- BR §4：「這個前置動作必須硬化成查詢 tool 裏的固定 routine……tool 進入點自動、
  無條件、不可繞過地執行的內建前置閘。」
- BR §4A：「登入模式不准並發、不准雙登入。這也要硬化。用 in-memory status gate
  來保護。」
- 使用者 2026-07-19（scope 粒度澄清）：「當然不必每查一件就重設一次。以每一個 live
  tcp session 為單位。」

## Requirement Revision History

- 2026-07-19: initial draft created via plan-init.ts
- 2026-07-19: live recon 推翻 BR §4 「scope+欄位」root cause；使用者拍板 §4 改架構
  ——number-query 解析改走 adv_search 路徑（能 render 專利號 + 已有 scope routine）。
- 2026-07-19: 使用者澄清 scope 重設粒度 = per-login-session（非每查重設、非每查驗證）。

## Effective Requirement Description

1. **§4（重定向）**：所有登入模式 number-query 進入點（`gpss4_resolve_appnos` /
   `gpss4_folder_search` / `gpss4_folder_mark`）的**號碼→專利號解析改走 adv_search
   路徑**（`_submit_query` + `_enter_dual_view` + parse），該路徑會 render 專利號；
   folder 標記清單路徑退役為 fallback 或移除。
2. **§4 scope routine（per-session 粒度）**：adv 路徑查詢前，於**每個 login session
   設一次** DB scope（依國別/軸推導 DB codes：TW appno→TWA+TWB；CN→CNA+CNB；
   US→USA+USB），複用既有 `set_search_databases`。同 session 內復用，不每查重設。
   fail-fast 不 silent fallback（設定失敗即中止查詢，不用可能錯的現有 scope 續查）。
3. **§4A login gate**：patentmcp server process 內維護一個全局 in-memory login gate；
   任何會觸發 web 登入的登入模式入口進場前必須先拿到 gate；拿不到即 fail-fast raise
   （帶現持有者資訊），**不排隊、不重試、不開第二條 session**。gate 只管登入模式，
   GPSS REST API（配額制、不碰登入面）不受限。
4. **可觀測**：查詢回傳/log 標明本次生效的 DB scope；gate 狀態（持有者/空閒/上次釋放）
   可查。

## Scope

### IN

- number-query 解析路徑重定向到 adv_search（`gpss4_resolve_appnos` 主要受益）。
- per-session scope 設定 routine（`_ensure_query_ready`）。
- §4A in-memory login gate（process 內互斥鎖 + 持有者識別 + fail-fast）。
- 跨國通用（TW/CN/US 至少各驗一筆）。

### OUT

- adv_search boolean/classification 檢索本身的行為變更（已由 BR_20260716 spec 擁有）。
- GPSS REST API 路徑（config、額度、claim/biblio 取文）——不碰。
- cross-DB 號碼格式 converter（BR_20260719 前案已落地，本案復用不重做）。

## Non-Goals

- 不修 folder 標記清單路徑「為何不 render 專利號」的 TIPO server 端行為（不可控；
  改走 adv 路徑繞過即可）。
- 不引入 scope 快取/latch 去「猜」config 現態（並發已被 §4A gate 物理消除，per-session
  設一次即正確）。

## Constraints

- **單線天條**：登入爬蟲單線序列，禁並發、禁雙登入（§4A 硬化此約束）。
- **節流風險**：TIPO 帳號對高頻/密集請求會鎖定；scope per-session 設一次（非每查）
  正是為降低請求量。
- **fail-fast 天條**：scope 設定失敗、gate 拿不到 → 明確 raise，絕不 silent fallback。
- **無新 MCP tool**：內部路徑重構 + gate，工具清單不變。

## What Changes

- `patents.py` 的 number-query 進入點解析邏輯改呼叫 adv_search 路徑。
- 新增 `_ensure_query_ready(country, axis)` per-session scope routine（單一入口）。
- 新增 in-memory login gate（`gpss4/login_gate.py` 或 session.py 內）。
- adv_search 抽出可單筆號碼查詢的 helper（`harvest` 目前是整軸 harvest，需能單號查詢）。

## Capabilities

### New Capabilities

- `_ensure_query_ready`: per-login-session 的 DB scope 前置閘，號碼查詢前自動設一次。
- login gate: process 內登入模式互斥，fail-fast 防並發/雙登入/節流鎖定。

### Modified Capabilities

- `gpss4_resolve_appnos`: 解析路徑從 folder 標記清單改走 adv_search（能 render 專利號），
  resolved 率預期從 0 顯著回升。
- `gpss4_folder_search` / `gpss4_folder_mark`: 同步改走 adv 路徑或標註 fallback。

## Impact

- 受影響 code：`src/patent_mcp_server/patents.py`（number-query tools）、
  `src/patent_mcp_server/gpss4/adv_search.py`（抽單號查詢 helper）、
  `src/patent_mcp_server/gpss4/folder.py`（退役/fallback）、
  `src/patent_mcp_server/gpss4/session.py`（gate 整合）。
- 受影響資料：本案 TW 99 未解 appno 可回收一批；TW235 recheck 的 86 error 部分待重驗。
- owning specs：`specs/patentmcp_gpss-web-login-db-scope`（BR_20260716，scope）、
  `plans/patentmcp_gpss4-folder-tools`（folder 路徑）。
- 無新 MCP tool；container 需重啟載入新 code。

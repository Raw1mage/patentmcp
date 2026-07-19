# Design: patentmcp_gpss4-number-query-adv-route

## Context

GPSS4 登入模式 number-query（`gpss4_resolve_appnos` / `gpss4_folder_search` /
`gpss4_folder_mark`）走 `folder.py` member-area 標記清單路徑，對已命中的申請號抽不到
公開/公告號（`search_number` count=1 命中但 `_extract_rows=0`、結果頁無 `TW\d{6,}`）。
本案 TW 99 筆 appno resolved=0。

同 repo 已有一條**能正確 render 專利號**的路徑：`adv_search.harvest()`（BR_20260716
修好），流程 login → `set_search_databases`(scope) → `_submit_query` → 家族收合 →
**`_enter_dual_view`（簡詳目並列，唯一 render 專利號的檢視）** → paginate → parse。
folder 路徑缺 dual-view 這步，是它抽不到號的結構性原因。

## Architecture (IDEF0-derived)

本設計掛在 idef0.json 的功能骨架上（IDEF0-first，SKILL.md §19）：

- **A1 取得登入互斥 gate** — DD-5 的 in-memory login gate；number-query 進入的第一關。
- **A2 確保 login session + per-session DB scope** — `ensure_logged_in` +
  `_ensure_query_ready`（DD-4 per-session scope）；復用 `set_search_databases`（DD-2）。
- **A3 adv_search 單號解析 (resolve_one)** — DD-3 的輕量 helper，走
  `_submit_query`+`_enter_dual_view`（唯一 render 專利號檢視）。
- **A4 釋放 gate + 輸出結果** — DD-7 gate release（finally + 真進程校驗）+ 可觀測輸出。

GRAFCET（grafcet.json）描述 A1→A4 的執行狀態機：gate acquire 分岐（busy→fail-fast）、
scope 分岐（已設→復用 / 未設→設定）、batch loop（同 session 復用 scope）、finally release。

## Goals / Non-Goals

**Goals**

- number-query 的號碼→專利號解析改走 adv_search 路徑（能 render 專利號）。
- per-login-session 粒度的 DB scope 前置 routine（`_ensure_query_ready`）。
- in-memory login gate：process 內登入模式互斥，fail-fast 防並發/雙登入/節流鎖定。
- 跨國通用（TW/CN/US）。

**Non-Goals**

- 不修 folder 標記清單路徑「為何 TIPO 不 render 專利號」的 server 端行為（改走 adv 繞過）。
- 不碰 GPSS REST API 路徑（配額制、不碰登入面）。
- 不引入 scope 快取 latch 去猜 config（並發已被 login gate 物理消除）。

## Decisions

- **DD-1（root-cause 推翻，2026-07-19 live recon）**：BR §4 原診斷「DB scope + 輸出
  欄位未啟動」**證偽**。實測：設定頁 `_20_20_S_P1`（公開/公告號輸出欄位）本來就已勾
  [x]；設 DB scope TWA+TWB 成功後重查 known-item `TW202223848` 仍 `_extract_rows=0`、
  html 24470 無任何 `TW\d{6,}`。→ 真因是 folder 標記清單路徑本身不 render 專利號，
  與設定頁 scope/欄位無關。同構 `event_2026-07-16 gpss4-pat-no-null`（結果頁狀態機
  問題：需進階檢索+切表格檢視才 render）。

- **DD-2（架構：改走 adv 路徑，使用者拍板）**：number-query 解析改用 adv_search 路徑。
  理由：adv 路徑已證能 render 專利號（`_enter_dual_view`）、已有 scope routine
  （`set_search_databases`）、已被 BR_20260716 驗證。folder 標記清單路徑退役為 fallback
  或移除。**替代方案否決**：(a) 逆向 folder 路徑讓 TIPO render 專利號——TIPO server
  端行為不可控，且 dual-view 只存在於進階檢索；(b) 照 BR 原方向硬化 scope+欄位
  routine——recon 已證不會修好，是打症狀。

- **DD-3（單號查詢 helper）**：`adv_search.harvest()` 目前是整軸 harvest（paginate 全部
  結果頁）。number-query 是「單一 appno → 該筆專利號」，需抽出輕量 helper
  `resolve_one(s, number, axis)`：submit `(<no>)@AN` query → dual-view → parse 第一
  筆匹配 row 的 pub_no，不做全軸分頁。復用 `_submit_query` / `_enter_dual_view` /
  parse primitives，不重寫狀態機。

- **DD-4（scope 粒度 = per-login-session，使用者拍板 2026-07-19）**：DB scope 於**每個
  login session 設一次**，非每查重設、非每查驗證。理由：§4A login gate 保證單線無並發
  → 同 session 內 config 不可能被他人改 → session-scoped 設一次即安全。這**不是** BR
  §4.2 反對的「latch 猜 config」——並發被 gate 物理消除後，per-session 設一次是確定性
  正確，而非猜測。每查重設（BR §4.2 字面）會對 99 筆 batch 多發 ~300 requests，反而
  升高 TIPO 節流鎖定風險，傷害它想保護的正確性。實作：session 上掛 `_scope_set: set`
  記已設 DB codes，`_ensure_query_ready` 檢查該 session 是否已設所需 scope，未設才設。

- **DD-5（§4A in-memory login gate）**：patentmcp server process 內維護一個 module-level
  gate（`asyncio.Lock` + `_holder` 識別 dict）。任何會觸發 web 登入的登入模式入口
  （`GPSS4Session.login` / `ensure_logged_in` 首次登入 / 所有 number-query + adv harvest
  進入點）進場前 `acquire`；拿不到即 raise `GPSS4LoginBusyError`（帶現持有者 tool 名 +
  取得時間），**不排隊、不重試、不開第二 session**（BR §4A 天條，TIPO 鎖定血淚）。
  release 在 session `close()` / finally。gate 只管登入模式；GPSS REST API 不 acquire。

- **DD-6（fail-fast 天條）**：scope 設定失敗（`GPSS4DbScopeError`）→ 查詢中止，不用
  可能錯的現有 scope 續查。gate 拿不到 → 立即 raise，不 silent 開第二 session。無任何
  silent fallback。

- **DD-7（gate 與 OS 進程一致）**：release 用真進程識別（`readlink /proc/<pid>/exe`
  類，非 grep cmdline 避免 shell 自匹配假影）作一致性校驗依據。gate 狀態可查
  （持有者/空閒/上次釋放時間）。

- **DD-8（BR_20260719 追加 §缺陷A：號碼形態 fail-fast 分流，2026-07-20）**：`gpss4_resolve_appnos`
  入口對每筆做號碼形態判別（SSOT `pubno_convert.tw_number_kind`）。已公開/公告識別號
  （西元年公開號 `TW(19|20)\d{7}`、憑證號 `TW[IMD]\d+`、帶 kind 尾碼號）= `identifier`
  → passthrough 標 `already_identifier`，**不投 adv 查詢、不計 consecutive error**。杜絕
  「乾淨民國年 appno 輸入被誤入的公開號拖垮整批 CONSECUTIVE_ERRORS」。判別邏輯收斂進
  `pubno_convert.py`（純函式 SSOT，DD-1/DD-2 沿用），非散在 caller。
- **DD-9（BR_20260719 追加 §缺陷B：hits>0-no-render 降級為 recoverable，2026-07-20）**：
  `_submit_query` 遇 search-form watcher shell + DB_OK + total>0（引擎 async race「前次
  檢索還沒好」，非 zero-hit、非硬 error）→ 改 raise `GPSS4AdvRenderPending`（subclass
  `GPSS4AdvSearchError`，攜 counts + shell HTML）。caller `gpss4_resolve_appnos` 捕捉它標
  `render_pending`、**不計 CONSECUTIVE_ERRORS**、續跑整批。把「搜到了卻抽不到號」從
  批次殺手降為單筆可回收（BR §缺陷B 核心訴求）。
  誠實邊界（code-thinker）：完整 shell→result-list re-navigation（讓 render_pending 當批
  解出號）需要可必現的 hits>0-no-render 窗口，當前資料狀態不提供（live recon 2026-07-20：
  @PN 直 render、@AN 為真 zero-hit）。故本次僅降級不中斷，不憑猜測寫未驗證的 render-retry；
  絕不捏造號碼。

## Risks / Trade-offs

- **adv 單號查詢比 folder 慢**（多 dual-view + 家族收合步驟）— mitigation: `resolve_one`
  跳過不必要的全軸分頁，單筆只走到第一頁 dual-view 即 parse；per-session scope 設一次
  攤銷成本。
- **改路徑可能引入新 parse 差異**（adv row schema vs MarkList row）— mitigation:
  test-vectors 對 known-item 驗 pub_no 正確；保留 folder 為 fallback 一段觀察期。
- **login gate 誤鎖**（gate 說忙但實際無登入）— mitigation: DD-7 真進程校驗 + gate
  狀態可查 + release 在 finally 保證釋放。
- **TIPO 節流**（本案根本痛點）— mitigation: §4A gate 消除並發/雙登入；DD-4 per-session
  scope 消除每查重設的請求洪峰。

## Critical Files

- `src/patent_mcp_server/patents.py` — number-query MCP 進入點（`gpss4_resolve_appnos`
  5645 / `gpss4_folder_search` 5622 / `gpss4_folder_mark` 5601），解析路徑改走 adv。
- `src/patent_mcp_server/gpss4/adv_search.py` — `harvest`(830) / `_submit_query`(580) /
  `_enter_dual_view` / `set_search_databases`(413)；新增 `resolve_one` helper + `_ensure_query_ready`。
- `src/patent_mcp_server/gpss4/session.py` — `GPSS4Session`；login gate 整合點
  （`login` 287 / `ensure_logged_in` 368 / `close` 387）。
- `src/patent_mcp_server/gpss4/login_gate.py` — 新增：module-level in-memory login gate。
- `src/patent_mcp_server/gpss4/folder.py` — 標記清單路徑退役為 fallback。

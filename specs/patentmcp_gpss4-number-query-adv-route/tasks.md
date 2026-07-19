# Tasks: patentmcp_gpss4-number-query-adv-route

## 1. adv_search 單號解析 helper

- [x] 1.1 `adv_search.resolve_one(s, number, axis)`：submit `(<no>)@AN/@PN` → 家族收合 → `_enter_dual_view` → parse 第一筆匹配 row 的 pub_no，復用既有 primitives，不做全軸分頁。
- [~] 1.2 軸別由呼叫端 axis 參數推斷（TW\d{9}→apply）；gpss4_resolve_appnos 固定 @AN，folder 工具保留 axis 參數。resolve_one 內建 apply|pub 兩軸。

## 2. per-session scope 前置 routine

- [x] 2.1 `GPSS4Session` 加 `_scope_set: set` 記錄本 session 已設 DB codes（login 重置）。
- [x] 2.2 `_ensure_query_ready(s, country)`：依國別推導 DB codes（TW→TWA+TWB / CN→CNA+CNB / US→USA+USB / JP / KR / EP），檢查 `_scope_set`，未含所需即 `set_search_databases` 並記入；失敗 raise `GPSS4DbScopeError`（fail-fast 無 silent fallback）。
- [x] 2.3 number-query batch 進入點（gpss4_resolve_appnos）per-session 呼叫一次 `_ensure_query_ready`（非每查）。

## 3. §4A in-memory login gate

- [x] 3.1 新增 `gpss4/login_gate.py`：module-level `_LoginGate` 單例 + `_holder`（tool 名）+ 取得時間 + `GPSS4LoginBusyError`。（用純旗標 fail-fast 而非 asyncio.Lock await-blocking，符合「拿不到即退」契約）
- [x] 3.2 所有觸發 web 登入的登入模式入口（gpss4_resolve_appnos + folder_list/mark/search）進場 `acquire`，拿不到即 raise（帶持有者資訊），不排隊/不重試/不開第二 session。
- [x] 3.3 release 在 `async with` 離場（finally），用真進程識別（`readlink /proc/<pid>/exe`）作一致性校驗；GPSS REST API 路徑不 acquire（不同認證面）。
- [x] 3.4 gate 狀態可查（`gate_status()`：持有者/空閒/上次釋放時間）。

## 4. number-query 進入點改走 adv 路徑

- [x] 4.1 `patents.py::gpss4_resolve_appnos`：解析改呼叫 `resolve_one`（adv 路徑），folder mark-list 路徑完全移除（recon 坐實其不 render 專利號）。
- [x] 4.2 `gpss4_folder_search` / `gpss4_folder_mark` / `gpss4_folder_list`：套 login gate（§4A 互斥）；folder 工具本身保留（標記清單實作需求）但受 gate 保護。
- [x] 4.3 gpss4_resolve_appnos 回傳 `effective_scope`（本次生效 DB scope，可觀測）。

## 5. 測試與驗證

- [x] 5.1 單元測試：`_ensure_query_ready` scope 推導 + per-session 復用（mock session，不 live）。`tests/test_br20260719_adv_route.py`
- [x] 5.2 單元測試：login gate 互斥（第二 acquire fail-fast）+ finally release + 例外路徑 release。共 10 全綠。
- [~] 5.3 **live roundtrip（2026-07-19 部分達成）**：TW 已坐實——`TW109112770`(@AN)→`TW202138759A`（與 converter ground truth 一致）。⚠️ 原驗證輸入 `TW202223848` 是**公開號**（西元年制 2022+023848）非申請號，用 @AN 查必 NOT_FOUND，非 bug——真實生產輸入是民國年 appno（109112770 / 112107009…）。CN/US 跨國尚未 live 驗（deferred 待額度窗口）。
- [x] 5.4 **live batch（2026-07-19 達成）**：`gpss4_resolve_appnos` 對全 appno 6 筆切片 **resolved 6/6**（前為 0）；揭出並修復 3 真 bug（設定頁 read-modify-write / apply_no parse / slot harvest-timing + connection-refused transient retry）。

**Validation evidence**: 單元測試 `tests/test_br20260719_adv_route.py` **10 pass / 0 fail**（全套 gpss4 27 pass / 0 fail 零回歸）；live batch `gpss4_resolve_appnos` pending_tw_99 切片 **6/6 resolved**（前為 0）；live roundtrip TW109112770@AN→TW202138759A 對齊 converter ground truth。container restart smoke 綠。CN/US 跨國 live deferred（純函式已 pytest 全覆蓋）。

## 6. 收尾

- [x] 6.1 container 重啟載入新 code + smoke（`docker compose restart patentmcp`→healthy；uv-venv smoke 綠：login_gate._LoginGate / GPSS4LoginBusyError / adv_search.resolve_one / _ensure_query_ready 皆存在，GPSS4Session import OK，log 無 error）。
- [x] 6.2 event_record 收尾（`event_2026-07-19_gpss4-number-query-adv-route...`）+ BR_20260719 §4/§4A 標 resolved（BR 文首狀態 + §5 live 驗證 + §4/§4A→實作對照表已落地）。
- [x] 6.3 architecture.md sync（specs/architecture.md L89–98：number-query adv 路徑 + resolve_one + per-session scope + login gate + session-keepalive + 4 進入點改接 + 測試/live 驗證，已同步）。

## 7. BR_20260719 追加 §缺陷A/B（amend，2026-07-20）

> 前身 BR closed 後消費端實測仍卡 CONSECUTIVE_ERRORS：8 件 `TW20xx` 公開號被誤入 @AN 軸拖垮整批（缺陷A）；且 hits>0 卻 result-list 不 render 時直接記硬 error（缺陷B）。DD-8/DD-9。

- [x] 7.1 缺陷A — `pubno_convert.tw_number_kind(raw)` SSOT 純函式：`TW(19|20)\d{7}` / `TW[IMD]\d+` / 帶 kind 尾碼 → `identifier`；民國年 `TW\d{9}`（百位<千位）→ `apply`；非 TW/位數不符 → `unknown`（不猜號，DD-2）。
- [x] 7.2 缺陷A — `gpss4_resolve_appnos` 入口對每筆判別：`identifier` → passthrough 標 `already_identifier`，不投 adv、不計 consecutive error，續跑整批。stats 加 `already_identifier`。
- [x] 7.3 缺陷B — 新增 `GPSS4AdvRenderPending(GPSS4AdvSearchError)`（携 counts+shell HTML）；`_submit_query` 於 hits>0-no-render（search-form watcher shell async race）改 raise 它，取代誤導的 `"retry the query"` 硬 error。
- [x] 7.4 缺陷B — `gpss4_resolve_appnos` 捕捉 `GPSS4AdvRenderPending` → 標 `render_pending`、不計 CONSECUTIVE_ERRORS、續跑整批。stats 加 `render_pending`。
- [x] 7.5 offline 單元測試：`tw_number_kind` 判別（公開號/民國年/憑證號/unknown/分隔符）；resolve_appnos 分流（identifier passthrough 不進 adv、混合 batch render_pending 不中斷、硬 error 仍中斷）。**test_pubno_convert 27 pass + test_br20260719_adv_route 13 pass = 40 pass / 0 fail 零回歸**。
- [~] 7.6 **缺陷B 完整 shell→result-list re-navigation deferred**：live recon 2026-07-20（@PN 直 render、@AN 為真 zero-hit）無法必現 hits>0-no-render 窗口；憑猜測寫未驗證 render-retry 違反 code-thinker §5。本次僅降級為 recoverable render_pending 不中斷；完整 in-batch 解號待可必現場景（缺陷A 分流後公開號不再誤入 @AN 軸，BR 生產故障已根除，此為 latent 硬化）。

**Validation evidence (§7)**: `tests/test_pubno_convert.py` 27 pass（含 tw_number_kind 5 類 + vendor-drift guard 未回歸）；`tests/test_br20260719_adv_route.py` 13 pass（原 10 + 缺陷A/B dispatch 3）；合計 **40 pass / 0 fail**。Live recon（`scripts/diag_br20260719b_render.py`，XDG scratch 已清）坐實 @PN 直 render / @AN 真 zero-hit，佐證缺陷A 分流即根除生產故障、缺陷B 為 latent race。

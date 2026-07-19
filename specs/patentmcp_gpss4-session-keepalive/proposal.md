# Proposal: patentmcp_gpss4-session-keepalive

## Why

- GPSS4 登入模式每個 MCP 呼叫各開一個 `GPSS4Session()`、登入一次、`finally` 關掉
  (`gpss4_resolve_appnos` patents.py:5710/5757;`gpss4_folder_*` 同型)。單一呼叫內
  session 已 keep-alive(6/6 batch 只登一次),但**跨呼叫**每次重登。
- TIPO 帳號對登入頻率**節流鎖定**(本專案曾因短時多次登入把帳號打進鎖定,§4A 天條起源)。
  每呼叫重登 = 每次都燒登入額度 = 帳號鎖定風險。
- session 本身實測存活 ~5400s(90min,`session.py` docstring),遠長於一次批次;壽命不是
  瓶頸,**缺的是跨呼叫復用同一 authed session 的機制**。

## Original Requirement Wording (Baseline)

- "登入一次的 session 有沒有辦法 keep alive" → "開 plan 做 session keep-alive"
- 決策拍板(2026-07-19,MCP question):
  - "mcp 自己要有 in memory session control,對所有 client 統一 ssot"
  - "顯式 close tool + idle TTL 雙保險"
  - "TTL < 90min 保守自動回收 + 健康檢查"

## Requirement Revision History

- 2026-07-19: initial draft created via plan-init.ts
- 2026-07-19: 三項架構決策經 MCP question 拍板(見 Baseline)

## Effective Requirement Description

1. patentmcp server process 內維護一個 **module-level in-memory SessionManager**,作為
   所有 client / 所有登入模式進入點的**單一真實來源(SSOT)**:同一時間至多一個 live
   authed GPSS4 session,跨 MCP 呼叫復用。
2. 登入模式進入點改為向 SessionManager **借用**共享 session(reuse-or-mint),呼叫結束
   **不關**(release-keep-alive),而非每次 `GPSS4Session()` + `close()`。
3. session 生命週期由 SessionManager 治理:**顯式 close tool**(`gpss4_session_close`)
   讓 client/orchestrator 主動歸還;**idle TTL 背景兜底**(閒置逾時自動回收),雙保險。
4. session 壽命上限**保守設在 90min 內**(如 absolute 60min / idle 5-10min);每次復用前
   做**輕量健康檢查**(member 頁可達),失效即乾淨重建,避免 raw POST 撞上過期 slot 中途掛。
5. **§4A 禁並發/禁雙登入天條不破**:SessionManager 內建「同時只一個 live session + 同時
   只一個 caller 在用」的互斥(fail-fast on busy),取代/吸收現有 per-call login gate。

## Scope

### IN
- 新增 `gpss4/session_manager.py`:module-level singleton,治理單一共享 session 的
  acquire(reuse-or-mint)/ release(keep-alive)/ close / reap(idle+absolute TTL)/
  health-check / 可觀測 status。
- 4 個登入模式進入點(`gpss4_resolve_appnos` / `gpss4_folder_list` / `gpss4_folder_mark`
  / `gpss4_folder_search`)改為經 SessionManager 借還,不再自建自關 session。
- 新增 MCP tool `gpss4_session_close`(顯式歸還)+ `gpss4_session_status`(可觀測)。
- login gate(`login_gate.py`)與 SessionManager 的關係整併:互斥語義收斂到單一 SSOT,
  保留 DD-7 真進程一致性校驗與 fail-fast-on-busy 契約。
- 背景 idle TTL reaper(async task 或 lazy-on-acquire 檢查)。

### OUT
- GPSS REST API 路徑(官方金鑰、配額制、不碰登入面)——不進 SessionManager,維持並行。
- 跨 process / 跨機器的 session 共享(本 plan 限單一 patentmcp process 內 SSOT)。
- session 內部登入流程本身(CAPTCHA / SSO chain,`session.py` 已穩定,不動)。
- 多帳號並行 live session(天條:同時只一個 live session;帳號輪替仍是登入失敗才換)。

## Non-Goals

- 不做 session pool(多 live session)——與禁雙登入天條衝突。
- 不做排隊等待(fail-fast 契約不變:busy 即拒,不排隊不重試)。
- 不追求 raw POST 全面自動重登(健康檢查 + TTL<90min 已避開過期 slot 場景)。

## Constraints

- **§4A 天條(最高)**:登入模式禁並發、禁雙登入;拿不到即 fail-fast,不排隊不重試不開第二 session。
- session 壽命上限 < TIPO 實測 ~90min slot 失效窗口。
- raw `s.client.post`(submit/dual/collapse)無自動重登;健康檢查須在**復用前**攔截過期。
- XDG 天條:任何 scratch/log 落 XDG 非 /tmp。
- 無 fallback 天條:session 失效 → 顯式重建或 fail-fast,不靜默續用可能失效的 session。

## What Changes

- number-query / folder 進入點從「每呼叫一 session」→「向 SSOT 借共享 session」。
- login gate 從獨立 per-call 互斥 → 併入 SessionManager 的 acquire 契約。
- 新增 session 生命週期可觀測面(status tool)+ 顯式 close tool。

## Capabilities

### New Capabilities
- `SessionManager`(SSOT):跨呼叫復用單一 authed GPSS4 session,含 TTL/health/reap 治理。
- `gpss4_session_close`:顯式歸還/關閉共享 session。
- `gpss4_session_status`:查共享 session 狀態(live/idle/age/holder)。

### Modified Capabilities
- `gpss4_resolve_appnos` / `gpss4_folder_*`:改經 SessionManager 借還,跨呼叫不重登。
- `login_gate`:互斥語義併入 SessionManager;對外契約(fail-fast on busy)保留。

## Impact

- `src/patent_mcp_server/gpss4/session_manager.py`(NEW)
- `src/patent_mcp_server/gpss4/login_gate.py`(整併/改造)
- `src/patent_mcp_server/gpss4/session.py`(可能加 health-check helper)
- `src/patent_mcp_server/patents.py`(4 進入點 + 2 新 tool)
- `tests/`(新增 session_manager 生命週期單元測試)
- `specs/architecture.md`(adv-route / login gate 段同步)

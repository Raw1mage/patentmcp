# Design: patentmcp_gpss4-session-keepalive

## Context

GPSS4 登入模式目前每個 MCP 呼叫自建 `GPSS4Session()` → `ensure_logged_in()` →
`finally: close()`(`patents.py:5710/5757` `gpss4_resolve_appnos`;`gpss4_folder_*`
同型)。單一呼叫內 session 已 keep-alive(BR_20260719 §5 live batch 6/6 只登一次
坐實),但**跨呼叫**每次重登。TIPO 對登入頻率節流鎖定(§4A 天條起源:曾因短時多登
把帳號打鎖),故每呼叫重登 = 每次燒登入額度 = 鎖定風險。session 實測活 ~90min
(`session.py` docstring),壽命非瓶頸——缺的是**跨呼叫復用同一 authed session 的
process 內 SSOT**。使用者拍板:MCP 自己要有 in-memory session control,對所有 client
統一 SSOT;顯式 close + idle TTL 雙保險;TTL<90min 保守回收 + 健康檢查。

## Goals / Non-Goals

**Goals**

- process 內單一 `SessionManager`(module-level singleton)治理**至多一個** live authed
  GPSS4 session,跨 MCP 呼叫復用(reuse-or-mint / release-keep-alive)。
- 生命週期雙保險:顯式 `gpss4_session_close` + idle/absolute TTL 背景回收。
- 每次復用前輕量健康檢查;失效乾淨重建(無 fallback 續用可能失效 session)。
- §4A 天條不破:同時只一個 live session + 同時只一個 caller 在用,busy 即 fail-fast。
- 可觀測:`gpss4_session_status` 查 live/idle/age/holder。

**Non-Goals**

- session pool(多 live session)、排隊等待、跨 process 共享、raw POST 全面自動重登。
- 動 session.py 內部登入流程(CAPTCHA/SSO 已穩定)。

## Architecture (IDEF0-derived)

A0「治理跨呼叫共享 GPSS4 登入 session」分解:

- **A1 借用 session(acquire / reuse-or-mint)** — DD-1/DD-2。登入模式進入點的第一關:
  向 SessionManager 借共享 session。有 live+健康 session → 復用(不重登);無/過期/不健康
  → mint 新 session(登入一次)。同時已有 caller 持用 → fail-fast `GPSS4LoginBusyError`
  (§4A,DD-3)。**control**:§4A 禁並發天條、TTL 上限、健康檢查結果。
- **A2 使用 session 做登入模式工作** — caller(resolve_one 迴圈 / folder 操作)在借到的
  session 上跑,SessionManager 記 in-use + 更新 last-used 時戳。
- **A3 歸還 session(release, keep-alive)** — DD-4。工作結束**不 close**,標回 idle、
  留在 SSOT 供下次復用。顯式 `gpss4_session_close` 才真 close;或 A4 背景回收。
- **A4 回收 session(reap:idle+absolute TTL / health-fail)** — DD-5。背景/lazy 檢查:
  idle 逾時、absolute 壽命逾時(<90min)、或健康檢查失敗 → `close()` 清出 SSOT。

## Goals / Non-Goals（見上）

## Decisions

- **DD-1（SSOT = module-level SessionManager,使用者拍板 2026-07-19）**:patentmcp process
  內維護單一 module-level `SessionManager`,持有至多一個共享 `GPSS4Session`。所有登入模式
  進入點(4 個)+ 所有 client 都經它借還,不再各自 `GPSS4Session()`+`close()`。理由:
  「對所有 client 統一 SSOT」是使用者明示需求;分散自建 session 正是跨呼叫重登的根因。
  Rejected:(a) 每 call 自建(現況,跨呼叫重登);(b) session pool(違禁雙登入天條)。

- **DD-2（acquire = reuse-or-mint + 復用前健康檢查,DD-5 天條)**:`acquire(holder)` 邏輯:
  若有 live session 且 `_healthy()` 且未逾 absolute TTL → 復用(reset in-use);否則
  乾淨 `close()` 舊的、mint 新 session 登入一次。健康檢查=輕量 member 頁可達性(復用前攔
  過期 slot,避免 raw POST 中途撞 login redirect;無 fallback 天條:不健康即重建不續用)。

- **DD-3（§4A 天條併入 SessionManager,吸收 login_gate）**:同時只一個 caller 能持用共享
  session。`acquire` 時若已有 in-use holder → 立即 raise `GPSS4LoginBusyError`(帶現持有者
  +held_for+exe),不排隊/不重試/不開第二 session。保留 login_gate DD-7 真進程一致性校驗
  (`readlink /proc/<pid>/exe`)。login_gate.py 的互斥語義收斂進 SessionManager,對外
  `GPSS4LoginBusyError` 契約與 `GPSS4_LOGIN_BUSY` typed error 不變(4 進入點行為相容)。
  **關鍵區分**:舊 gate「持有期=一次呼叫」;新模型「in-use 期=一次呼叫(仍互斥)」但
  「session 存活期=跨呼叫(keep-alive)」——兩個生命週期解耦是本 plan 的核心。

- **DD-4（release = keep-alive,非 close;顯式 close 雙保險,使用者拍板）**:呼叫結束
  `release(holder)` 只標 idle + 更新 last-used,**不 close** session(下次復用免登入)。真
  close 只由:(a) 顯式 `gpss4_session_close` tool;(b) A4 reaper。理由:release 即 close
  等於退回現況;keep-alive 才是本 plan 目的。雙保險避免「忘記 close → session 懸掛/gate
  卡死」——顯式歸還快、TTL 兜底穩。

- **DD-5（TTL<90min 保守回收 + absolute+idle 雙 TTL,使用者拍板）**:session 壽命上限保守
  設在 TIPO 實測 ~90min slot 失效窗口內。兩個 TTL:**idle TTL**(如 5-10min 無活動即回收,
  釋放閒置登入)+ **absolute TTL**(如 60min 自 mint 起強制回收,不論是否活躍,避開 90min
  slot 死線)。reaper 實作優先 **lazy-on-acquire 檢查**(acquire 時查 TTL/health,逾時即
  重建)為主、可選背景 async task 為輔——避免長駐 task 的 event-loop 生命週期複雜度。

- **DD-6（fail-fast / 無 fallback 天條）**:session 失效(健康檢查失敗 / redirect-to-login
  / TTL 逾時)→ 顯式重建或 fail-fast,**絕不**靜默續用可能失效的 session 回假結果。承接
  BR_20260719 DD-6 精神。

- **DD-7（邊界:REST 不入 SessionManager）**:GPSS REST API(官方金鑰、配額制、不碰登入面、
  不同認證平面)不經 SessionManager,維持可並行。只有 4 個登入模式進入點借還共享 session。

## Risks / Trade-offs

- **忘記 release/close → session/gate 懸掛** — mitigation: DD-4 雙保險(idle TTL 背景兜底)
  + `release` 保證在 `finally`(含例外路徑,承接 login_gate 現有契約)。
- **健康檢查本身燒一次請求** — mitigation: 用最輕量 member 頁 GET(非登入),遠低於重登成本;
  且只在 acquire 時做一次,不是每查。
- **absolute TTL 誤砍活躍長批次** — mitigation: TTL 設 60min,單批次(99筆×3s≈5min)遠內;
  真超長批次應分批(caller 責任),而非放寬 TTL 撞 90min slot 死線。
- **並發競態(兩 caller 同時 acquire)** — mitigation: SessionManager acquire 為同步臨界區
  (純旗標即時檢查,非 await-blocking,承接 login_gate 設計);登入爬蟲本單線序列,無跨
  event-loop 並發需求。
- **§4A 天條退化風險(keep-alive 讓 session 更久 = 更難保證單一)** — mitigation: DD-3
  in-use 互斥仍 per-call;live session 恆為 0 或 1(mint 前必 close 舊的),天條由「至多一
  live + 至多一 in-use」雙不變式守住。

## Critical Files

- `src/patent_mcp_server/gpss4/session_manager.py`(NEW)— SSOT singleton,本 plan 主體。
- `src/patent_mcp_server/gpss4/login_gate.py`— 互斥語義併入 SessionManager;DD-7 校驗保留。
- `src/patent_mcp_server/gpss4/session.py`— 加 `_healthy()` / health-check helper(DD-2)。
- `src/patent_mcp_server/patents.py`— 4 進入點改借還;新增 `gpss4_session_close` /
  `gpss4_session_status` 2 tool。
- `tests/test_gpss4_session_keepalive.py`(NEW)— 生命週期單元測試(reuse/mint/busy/TTL/
  health-fail/release-keep-alive/close)。
- `specs/architecture.md`— adv-route / login gate 段同步。

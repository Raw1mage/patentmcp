# Tasks: patentmcp_gpss4-session-keepalive

## 1. SessionManager 核心 (SSOT)

- [x] 1.1 新增 `gpss4/session_manager.py`:module-level singleton + 狀態欄位
      (`_session` / `_in_use_holder` / `_holder_exe` / `_minted_at` / `_last_used_at`
      + `idle_ttl_sec` / `absolute_ttl_sec`)。
- [x] 1.2 `acquire(holder)`:reuse-or-mint 邏輯(DD-1/DD-2)——in-use → fail-fast
      `GPSS4LoginBusyError`(DD-3);live+健康+未逾 TTL → 復用;否則 close 舊 + mint 新登入一次。
- [x] 1.3 `release(holder)`:keep-alive(DD-4)——清 in-use holder、更 last-used、**不 close**;
      DD-7 真進程一致性校驗(承接 login_gate)。
- [x] 1.4 TTL 檢查:idle + absolute 雙 TTL(DD-5),lazy-on-acquire 為主(`_absolute_expired`/
      `_idle_expired` + acquire 時檢查回收)。
- [x] 1.5 `close()`(顯式回收)+ `status()`(可觀測);observability 計數(login/reuse/
      busy_refused)+ logger 事件(mint/reuse/reap/health_fail)。

## 2. session 健康檢查 (DD-2 / DD-6)

- [x] 2.1 健康檢查內建於 SessionManager `_healthy()`:輕量 authed member 頁可達性(走
      `session.get`,本身帶 redirect-to-login 偵測);任何例外/非 authed → False(無 fallback)。
- [x] 2.2 acquire 復用前呼叫 `_healthy()`;失敗 → `_close_session("health_fail")` + mint。

## 3. login_gate 整併 (DD-3)

- [x] 3.1 login_gate 互斥語義併入 SessionManager;對外 `GPSS4LoginBusyError` /
      `GPSS4_LOGIN_BUSY` typed error 契約保留(全套 27 測試 + 15 subtest 零回歸)。
- [x] 3.2 login_gate.py 標 deprecated shim(頂部 `.. deprecated::` 註記);無 caller 殘留,
      保留避免破壞可能外部 import。

## 4. 進入點改接 + 新 tool

- [x] 4.1 `gpss4_resolve_appnos` 改經 `shared_session` 借還(移除自建 `GPSS4Session()`+
      `finally: close()`;release keep-alive 保證在 context manager `__aexit__` 含例外路徑)。
- [x] 4.2 `gpss4_folder_list` / `gpss4_folder_mark` / `gpss4_folder_search` 同改接
      (注入共享 session 給 `GPSS4Folder(session=s)`,**不呼叫 f.close()** 避免誤關共享 session)。
- [x] 4.3 新增 MCP tool `gpss4_session_close`(顯式歸還)+ `gpss4_session_status`(可觀測)。
- [x] 4.4 GPSS REST 路徑不經 SessionManager(邊界 DD-7 不變;只改 4 個登入模式進入點)。

## 5. 驗證

- [x] 5.1 單元測試 `tests/test_gpss4_session_keepalive.py`:覆蓋 TV-1..TV-10
      (reuse 不重登 / mint / 並發 fail-fast / release keep-alive / idle TTL / absolute TTL /
      health-fail 重建 / 顯式 close / close-while-busy / finally 例外歸還 / release mismatch)。
      mock login 計數 + mock 時鐘推進。**11 passed**。
- [x] 5.2 container 重啟載入新 code + import smoke(session_manager + 2 tool + login_gate shim
      全 OK);全套 gpss4 測試 **27 passed + 15 subtest 零回歸**。
- [x] 5.3 **live 驗證(2026-07-19 額度窗口)**:坐實 keep-alive —— 3 次登入模式呼叫
      (mint + CN advanced_search + US advanced_search) → `login_count=1, reuse_count=2`。
      **順帶抛出並修一個真 bug**:`_healthy()` 誤用 KM 首頁會員標記計數 → 恆判不健康
      → health_fail→mint 每呼叫重登。改用最終 URL 否被踢回 PAGE=login 判斷(RCA 詳
      event log)。CN/US 跨國併 BR_20260719 §5:CN110234567 / US10000000 dual-view 都
      render 出 pat_no + apply_no(順帶推翻 issue_20260716「CN pat_no 只在 AJAX」舊限制)。

## 6. 收尾同步

- [x] 6.1 `specs/architecture.md` line 93-94 (GPSS4 會員區 login gate 段) 已改述為
      SessionManager keep-alive SSOT + 4 進入點改接 + 2 tool 子項。
- [x] 6.2 event_record 收尾已寫(implementing 狀態,含 DD 落地/Issues/Verification/
      Architecture Sync/Remaining)。BR_20260719 §5 CN/US 併入 task 5.3 live 窗口。

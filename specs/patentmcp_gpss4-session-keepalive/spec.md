# Spec: patentmcp_gpss4-session-keepalive

## Purpose

保證 patentmcp process 內存在單一 in-memory SSOT (`SessionManager`) 治理**至多一個** live
authed GPSS4 登入 session,跨 MCP 呼叫復用以消除重複登入,同時**不破** §4A 禁並發/禁雙登入
天條,並以「顯式 close + idle/absolute TTL 雙保險 + 復用前健康檢查」確保 session 不懸掛、
不撞 ~90min slot 死線、不靜默續用失效 session。

## Requirements

### Requirement: 單一 SSOT 跨呼叫復用

系統 SHALL 在 process 內維護單一 module-level `SessionManager`,持有至多一個共享
`GPSS4Session`;所有登入模式進入點經其 `acquire` 借用,`release` 歸還而不 close。

#### Scenario: 第二次呼叫復用不重登

- **WHEN** 已有 live 健康且未逾 TTL 的共享 session,另一登入模式呼叫 `acquire`
- **THEN** 復用既有 session、**不觸發登入**,`gpss4_session_status` 顯示同一 session age 遞增

#### Scenario: 無 session 時 mint 一次

- **WHEN** SSOT 為空 (無 live session) 時呼叫 `acquire`
- **THEN** 建立新 `GPSS4Session` 並登入一次,記 mint 時戳作為 absolute TTL 起點

### Requirement: §4A 禁並發/禁雙登入不破

系統 SHALL 保證同時至多一個 in-use holder;第二個並發 `acquire` 立即 fail-fast,不排隊
不重試不開第二 session。live session 恆為 0 或 1。

#### Scenario: 並發 acquire 被拒

- **WHEN** 已有 in-use holder 持用 session,另一 holder 呼叫 `acquire`
- **THEN** raise `GPSS4LoginBusyError`(帶現 holder + held_for + exe),SSOT 狀態不變

### Requirement: keep-alive release 與雙保險回收

系統 SHALL 在 `release` 時僅標 idle + 不 close;真 close 僅由顯式 `gpss4_session_close`
或 reaper(idle TTL / absolute TTL<90min / health-fail)觸發。

#### Scenario: release 後 session 續存

- **WHEN** caller 工作結束呼叫 `release`
- **THEN** session 仍 live(未 close),`status` 顯示 idle,下次 `acquire` 可復用

#### Scenario: idle TTL 逾時自動回收

- **WHEN** session idle 超過 idle TTL 後再有 `acquire`(或背景 reaper 觸發)
- **THEN** 舊 session 被 close、清出 SSOT,acquire 走 mint 路徑重建

### Requirement: 復用前健康檢查 + 無 fallback

系統 SHALL 在復用 live session 前做輕量健康檢查(member 頁可達);失效或逾 absolute TTL
即乾淨 close + 重建,絕不靜默續用可能失效的 session。

#### Scenario: 不健康 session 重建

- **WHEN** `acquire` 時既有 session 健康檢查失敗(如 redirect-to-login)
- **THEN** close 舊 session、mint 新 session,不以失效 session 回假結果

## Acceptance Checks

- [ ] 連續兩次登入模式呼叫,第二次不觸發登入(單元測試:mock login 計數 == 1)
- [ ] 並發第二 `acquire` raise `GPSS4LoginBusyError`,live session 仍為 1
- [ ] `release` 後 session 未 close(`status.busy==false` 且 session 物件仍在)
- [ ] idle TTL 逾時後 acquire 重建(mock 時鐘推進,login 計數 +1)
- [ ] absolute TTL 逾時強制重建(不論 idle)
- [ ] 健康檢查失敗 → close + mint(mock 不健康,login 計數 +1)
- [ ] 顯式 `gpss4_session_close` 後 SSOT 為空(`status.busy==false` 且無 live session)
- [ ] GPSS REST 路徑不經 SessionManager(邊界不變)
- [ ] 4 進入點對外 `GPSS4_LOGIN_BUSY` typed error 契約相容(不回歸)

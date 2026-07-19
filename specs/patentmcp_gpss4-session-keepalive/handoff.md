# Handoff: patentmcp_gpss4-session-keepalive

## Execution Contract

- 交付 `SessionManager`(SSOT)+ 4 進入點改接 + 2 新 tool + 單元測試全綠 + container smoke。
- **Done 定義**:TV-1..TV-10 單元測試全過(mock login 計數證明復用不重登);container
  重啟 import OK;`specs/architecture.md` 同步。live 驗證為獨立 stop gate(見下)。
- 純 code 變更:`./src` bind mount 熱掛,container restart 即重掃;container 內 python
  用 `uv run`(非系統 python)。

## Required Reads

- `plans/patentmcp_gpss4-session-keepalive/design.md`(DD-1..DD-7,核心契約)
- `src/patent_mcp_server/gpss4/login_gate.py`(互斥語義來源,DD-3 整併對象)
- `src/patent_mcp_server/gpss4/session.py`(session 生命週期 / ~90min slot / raw POST 無自動重登)
- `src/patent_mcp_server/patents.py:5709-5757`(`gpss4_resolve_appnos` 現況借還模式)
- `issues/BR_20260719_...md`(§4A 天條 + §5 live 殘項脈絡)

## Stop Gates In Force

- **live 驗證前必停,等使用者定方向**:任何 live run 燒登入額度(帳號鎖定風險)。單元測試
  用 mock,不燒額度可自由跑;真 live(task 5.3)須使用者授權額度窗口。
- **§4A 天條**:實作不得引入排隊/重試/第二 session;不得放寬 absolute TTL 撞 90min slot。
- **無 fallback 天條**:session 失效即 fail-fast 或乾淨重建,不靜默續用。
- **架構變更 gate**:login_gate 整併(DD-3)動到既有天條實作,收尾前 architecture.md 必須同步。

## Execution-Ready Checklist

- [ ] design.md DD-1..DD-7 已讀、契約理解
- [ ] login_gate.py / session.py / patents.py 進入點已讀(read-before-write)
- [ ] 確認 mock login 計數 + mock 時鐘的測試手法(不燒真額度)
- [ ] container `uv run` 環境確認

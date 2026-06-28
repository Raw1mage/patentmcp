# Handoff: gpss-session-reuse-batch

## Execution Contract

把「軟性批量運作機制」(單線排隊 + session 復用 + 隨機延遲 + cooldown skip)從代表圖下載推廣到所有爬蟲性質工具,並抽出統一 `SoftScrapePolicy`。所有改動在 `patentmcp` 工具層;不私自寫臨時爬蟲腳本(天條)。

## Required Reads

- `plans/gpss-session-reuse-batch/proposal.md`(需求 + scope)
- `plans/gpss-session-reuse-batch/design.md`(DD-1~DD-7 + Risks/Trade-offs)
- `plans/gpss-session-reuse-batch/spec.md`(驗收場景)
- `src/patent_mcp_server/util/soft_scrape.py`(SoftScrapePolicy SSOT)
- `src/patent_mcp_server/patents.py`(GPSS 三工具 + session + batch)
- `src/patent_mcp_server/uspto/ppubs_uspto_gov.py`(PpubsClient)
- `src/patent_mcp_server/gpatents/client.py`(模範生節流參考,不動)

## Environment Facts

- venv:`/home/pkcs12/projects/patentmcp/.venv`
- patentmcp 為單進程 async server;`asyncio.Lock` 足以序列化
- pytest 未裝;測試以 `unittest` 直跑(`.venv/bin/python tests/<name>.py`)
- 容器:`webctl.sh {start|stop|restart|refresh|health}`;改 Python code 後 `refresh` 重建

## Stop Gates In Force

- gpatents(google)爬蟲已是模範生(single-flight + 3s + 60s cooldown),使用者明示**不納入**改動。
- 不新增 silent fallback(天條 11):失敗一律 explicit error / skip record。
- 不改 GPSS 官方 REST API client(合法 API,與抓蟲無關)。

## Execution-Ready Checklist

- [x] 已讀 proposal + design + spec
- [x] SoftScrapePolicy 抽出 + GPSS/ppubs 套用
- [x] 逐 phase 實作,每完成一 task 勾選 tasks.md
- [x] phase 完成跑對應單元測試
- [x] 容器 refresh 重建生效

## Validation

- 24 單元測試全綠(9 BR_20260628 回歸 + 6 session/batch + 9 SoftScrapePolicy)
- `import patent_mcp_server.patents` + `PpubsClient()` smoke EXIT=0
- 容器 `Up (healthy)` :8000
- architecture.md 已同步

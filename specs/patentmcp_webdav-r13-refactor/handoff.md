# Handoff: patentmcp_webdav-r13-refactor

## Execution Contract

- 依 tasks.md 順序交付：_pure 抽出 → landing scripts → tool 下架 → TokenStore 擴充 → WebDAV+Auth → 宣告同步。
- Done = spec.md AC-1..AC-9 全過 + 既有測試全綠（host venv + container）+ rclone 實掛載驗證。
- 每完成一個 task 立即 tick tasks.md checkbox。

## Required Reads

- `plans/patentmcp_webdav-r13-refactor/design.md`（DD-1..DD-9）
- `.tmp/inventory-r13-webdav.md`（盤點證據，file:line）
- `~/projects/opencode/specs/mcp-integration-standard/standard.md` §R13
- `~/projects/docxmcp/specs/mcp/webdav-working-cache/{spec,design}.md`（pattern 來源）
- `src/patent_mcp_server/_http_app.py` :312-345（單一 lifespan 約束）

## Stop Gates In Force

- 下架 tool 清單變更（超出 design.md 列表）需使用者批准
- 爬蟲 gate（allow_scraping）語義任何弱化 → 停
- git push / graduation → 使用者批准

## Execution-Ready Checklist

- [x] 使用者已拍板：WebDAV 完整版 / R13 積極拆 / 容許 breaking + typed redirect
- [x] 盤點完成（.tmp/inventory-r13-webdav.md）
- [x] design.md DD 定案

# Handoff: remediation_drawing-scraping-cdn

## Execution Contract

實作 BR_20260628 六項代表圖取得修復。所有改動在 `patentmcp` 工具層與 companion skill；不私自寫臨時爬蟲腳本（天條）。

## Required Reads

- `issues/BR_20260628_drawing_concurrency_scraping_remediation.md`（需求來源）
- `src/patent_mcp_server/patents.py`（抓圖工具 + fetch_patent_pdf）
- `src/patent_mcp_server/gpatents/client.py`（_flatten、_get 既有節流參考）
- `plans/remediation_drawing-scraping-cdn/design.md`（DD-1~DD-8）
- `plans/remediation_drawing-scraping-cdn/spec.md`（驗收場景）

## Environment Facts

- venv：`/home/pkcs12/projects/patentmcp/.venv`，Python 3.13
- PDF 工具：poppler `pdftotext` / `pdftoppm` / `pdfinfo`（/usr/bin，24.02）；Pillow 可用
- **PyMuPDF/fitz/pypdf 均不在環境**——D 工具用 poppler subprocess（DD-3），勿引入 PyMuPDF（AGPL，與 MIT 衝突）
- patentmcp 為單進程 async server；`asyncio.Lock` 足以序列化（DD-1）

## Stop Gates In Force

- **5.2 docker mount（C）**：needsApproval — 撰寫草案後停下向使用者提報，不自動改 docker-compose.yml / .mcp.json
- 其餘 A/B/D/E/F 為工具層 + skill 改動，可連續執行

## Execution-Ready Checklist

- [ ] 已讀 BR + design.md + spec.md
- [ ] 確認 poppler CLI 可用（`command -v pdftoppm pdfinfo pdftotext`）
- [ ] 逐 phase 實作，每完成一 task 勾選 tasks.md
- [ ] phase 完成跑對應單元測試
- [ ] C 草案完成後停 gate 等批准

## Validation

- 單元測試（mock httpx 403 / mock pdfinfo / 含 FIG.1 測試 PDF）
- `import patent_mcp_server.patents` smoke test
- architecture.md 同步

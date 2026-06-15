# PatentWorks

專利從 idea 到申請的全流程工作站 —— 一個 **MCP server + skill 組合包**,設計為與 OpenCMS、docxmcp、drawmiat 串接。

> 本專案於 2026-06 全面重定位並與其 AGPL 前身**斷開血脈**,以 MIT 重新授權。歷史、舊 8 層多 Agent 架構(A0–A8)、HLS/Grafcet 實驗等皆已廢除;產品由下列兩塊構成。

## 組成

### `patentmcp`(MCP server,`vendor/patents-mcp/`)
專利資料檢索與檔案交付。fork 自 openpharma/patents-mcp(MIT)並擴充:
- **檢索**:`gpatents_search`(Google Patents,語義排序+代表圖,已上線)、`gpss_search`(TIPO GPSS 官方 API,首選,待 userCode)、`uspto_patents`(ppubs)、Google BigQuery(降級不用於互動)。
- **取文/產物**:`gpatents_get`(完整摘要+claims)、`gpatents_download_pdf/figure`(代表圖/PDF)。
- **建表**:`build_screening_table`(search→家族去重→切 Claim1→**欄位隨選 CSV**→handle;>300 擋下)。
- **檔案交付**:docxmcp 式 token+blob store(`/files/{token}/blob/{rel}`),`stage_file` 落地任意檔回 handle,bytes 不過 context。

### `patentworks`(skill,`skills/patentworks/`)
專利從業流程,三個 flow 可單用或串成完整旅程:
```
disclosure(交底書)→ screening(查新)→ drafting(起草說明書)
```
- **disclosure**:原始材料/idea → 結構化技術交底書(intake 問題集、專利點挖掘、脱敏、自檢)。
- **screening**:CPC 錨定、US/CN、≤300 件、家族去重、逐列消化評分 → Agent 友善、人類可讀 scored CSV。內分「可專利性」與「landscape」。
- **drafting**:claims-first → spec 支持 → 法遵自檢。法域分 **共通/TW/CN/US/EP**;法遵以 skill 知識處理,不做工具。

領域骨幹見 `skills/patentworks/patent-practitioner-workflow.md`。

## 設定

`.mcp.json`(gitignored,含憑證路徑)註冊 patentmcp;以 `uv --directory vendor/patents-mcp run patent-mcp-server` 啟動。檢索來源金鑰:
- Google Patents:免認證,已可用。
- TIPO GPSS:`GPSS_USER_CODE`(向 TIPO 申請)。
- Google BigQuery(選用):`GOOGLE_CLOUD_PROJECT` + `GOOGLE_APPLICATION_CREDENTIALS`。
- EPO OPS(規劃中):OAuth consumer key/secret。

## 設計原則

- **輸出不變式**:任何檢索的最終交付物一律是 Agent 友善、人類可讀的 CSV 表格,經 token+blob handle 交付。
- **AI 預篩/起草草稿 + 解釋,人類複核裁決**(專利有法律份量)。
- **大道至簡**:不重造 docxmcp / drawmiat / OpenCMS 已能服務的子系統。

## 參考材料

`refs/` 收錄三個外部專利相關專案供研讀(各自授權;見 `refs/README.md`)。**AGPL 來源(PatentWriterAgent)僅供研讀,其程式碼不得進本產品。**

## 授權

MIT,見 [LICENSE](LICENSE)。

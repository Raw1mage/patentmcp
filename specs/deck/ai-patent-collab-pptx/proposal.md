# Proposal: AI 專利協作導覽簡報（18 頁 16:9）

## Why

一份對外介紹「AI 協作專利全流程工作站」的 18 頁投影片，走利善美/thesmart 品牌母片（深紅 `#B01722`）。本 spec 是**追認式**沉澱——deck 已於 2026-07-18 交付（`AI專利協作導覽_r1.2.pptx`），但整個製作過程即興推進、反覆試錯燒掉大量時間，未先開 plan。此 spec 把「三條產線為何失敗、master-surgery 為何是唯一正解、平行覆蓋根因」固化成可複用知識，讓下次做同類品牌簡報不必重踩。

## Effective Requirement Description

1. 18 頁 16:9，thesmart 母片繼承（背景/色帶/logo/字型來自母片，非 from-zero canvas 塗品牌色）。
2. **禁純 bullet**（blueprint 硬契約）：每頁用對應視覺形式（flow / card / stat / matrix / 對比欄 / 堆疊圖）。
3. 內容 SSOT = `output/slides_src/content_v2.md`（S1–S18）。
4. 交付檔名帶版號 `_r#.#`，前版並存不覆蓋（docxmcp egress 版號 rail）。
5. 視覺 QA 必用 fresh-eyes subagent，分批 ≤6 頁避開 inline media budget。
6. 交付檔 landed bytes 主 agent 獨立驗（count slides + 關鍵字斷言）。

## Scope

### IN
- deck 製作方法論的知識沉澱（產線選型、master-surgery 施作紀律、QA 分批、收據紀律）。

### OUT
- 內容文案本身的再創作；patentmcp 產品功能；docxmcp 工具實作（版號 rail 已在 docxmcp repo `3b81f86` 獨立 committed）。

## Non-Goals

- 不驅動未完成的實作——deck 交付物已存在並通過 QA + 收據驗證。

## Constraints

- master-surgery 對同一 token 禁止平行寫入（見 design DD-1）。
- gdrive host-only，egress 版號 rail target 須容器可見路徑。

## Capabilities

### New Capabilities
- 品牌簡報產線選型知識錨點：三產線失敗機制 + master-surgery 正解可複用。
- master-surgery 施作紀律：batch ops 原子寫入杜絕平行覆蓋。

### Modified Capabilities
- 無（追認式沉澱，不改既有能力）。

## What Changes

- 新增一份 docs-profile 知識錨點，供未來同類品牌簡報選型與施作參考。

## Impact

- `output/slides_src/` 產線腳本、docxmcp egress 版號 rail、pptx/doc-workflow skill 的實務教訓。

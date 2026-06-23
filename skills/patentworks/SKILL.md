---
name: patentworks
description: 專利全流程工作站。三種任務:(A) 把發明材料/idea 整理成技術交底書;(B) 前案/現況檢索 → 產出已評分、可稽核的人類可讀表格;(C) 從技術揭露起草符合各國法規的專利說明書(請求項+說明書+摘要)。當使用者要「整理交底書/挖專利點」「找前案/查有沒有人做過/技術現況/landscape」或「寫專利說明書/請求項/起草專利申請」時使用。檢索重 US/CN;起草分 共通/TW/CN/US/EP 五法域。
---

# PatentWorks

> **搭配 `patentmcp` MCP 使用**:本 skill 是這組工具的劇本;所有檢索/交付工具(`gpss_search`、`epo_family`/`epo_biblio`/`epo_search`、`gpatents_*`、`build_screening_table`、`stage_file`)都來自 patentmcp。沒有該 MCP 時本 skill 無法執行實際檢索。

專利從 idea 到申請的全流程。依需求選一個 flow,**先讀對應 flow 檔再執行**。

## 完整管線

```
disclosure(交底書)→ screening(查新)→ drafting(起草說明書)
發明材料/idea ───────────────────────────────→ 專利申請文件
```
三者可單獨用,也可串成完整旅程;前一段的產出是後一段的輸入。

## 選 flow

| 使用者意圖 | flow |
|---|---|
| 整理交底書 / 從專案材料挖專利點 / 發明揭露 | **`flows/disclosure.md`** |
| 有沒有人做過 / 找前案 / 可專利性 / 技術現況 / landscape | **`flows/screening.md`** |
| 幫我寫專利說明書 / 請求項 / 起草申請 | **`flows/drafting.md`** |

> screening 內部又分「可專利性(要件對照→新穎性綜述)」與「landscape(主題分群→技術地圖)」——細節見該 flow。

## 共用原則(兩 flow 皆適用)

1. **交付物是人類可讀的成品**(screening = scored CSV;drafting = 說明書文件),一律經 patentmcp `stage_file` / docxmcp token+blob handle 交付,bytes 不過 context。
2. **法域意識**:檢索預設 US/CN(TW 低價值);起草須先定目標法域,載入 `reference/drafting/common.md` + 對應法域檔。
3. **法遵以 skill 知識處理,不做工具**:合規/法條要點寫在 `reference/drafting/{common,tw,cn,us,ep}.md`,起草時逐條自檢。
4. **AI 做預篩/起草草稿 + 解釋,人類複核裁決**(專利有法律份量)。
5. **來源優先序(皆已上線)**:**GPSS**(`gpss_search`,首選——一次回 PN/AN/標題/摘要/Claim1/CPC/IPC/申請人/日期,CPC 錨定,US/CN/TW)> **EPO**(`epo_family` 官方 INPADOC 家族 / `epo_biblio` 摘要 / `epo_search` CQL,零限速)> **Google Patents**(`gpatents_search` 語義排序+代表圖;非官方,**會限速,client 已內建節流**)。**BigQuery** 僅用於便宜 metadata 查詢(assignee/分類/日期),**不用於全文互動檢索**(掃描計費,全文 200GB+)。

## 領域骨幹

人類從業流程與 AI 對應見 `../patent-practitioner-workflow.md`。

# Flow: Disclosure(技術交底書產出)

從原始材料(專案文件 / 程式碼 / 發明人口述 / idea)→ 結構化**技術交底書**,作為 screening(查新)與 drafting(起草)的輸入。致敬 handsomestWei/patent-disclosure-skill 的 front-end 概念;查新與文件轉換交給本專案既有能力(patentmcp / docxmcp / drawmiat),不重造。

## 流程

1. **Intake(需求擷取)**:用 `../reference/disclosure/intake-checklist.md` 的問題集引導發明人,補齊技術問題/方案/必要特徵/效果/實施例。
2. **材料掃描**:專案 docs/code 抽技術內容;`.docx/.pptx/.pdf` 用 **docxmcp / pdf skill** 轉 markdown(不自寫轉換器)。
3. **專利點挖掘**:從材料識別並綜合**可專利創新點**——每點寫:技術問題 → 技術手段(必要特徵)→ 有益效果 → 變化例。多點時標出彼此關係(是否單一發明構思)。
4. **(選)查新**:對挖出的專利點走 `screening.md`,標「已知 / 可能新穎 / 差異點」,回饋修正專利點。
5. **成文**:組成交底書——發明名稱 / 技術領域 / 背景與痛點 / 技術方案(含圖)/ 有益效果 / 具體實施例與參數 / **擬保護的創新點清單**。Mermaid/工程圖交 **drawmiat**;文件組裝交 **docxmcp**。
6. **脱敏**:依 `../reference/disclosure/deidentification.md` 移除客戶名/商業機密/可識別資訊——**交外部代理人前必做**。
7. **自檢**:邏輯一致、公式/參數正確、每個專利點都對應到方案與效果、術語一致(見 drafting common.md §15)。
8. **交付**:技術交底書 md → docxmcp 組 docx → `stage_file` / token handle。

## 銜接
`disclosure → screening → drafting`。交底書即 drafting flow 步驟 1(揭露擷取)的輸入;專利點清單即 drafting「擬保護創新點」與 claims 的種子。

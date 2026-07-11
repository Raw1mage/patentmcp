# FR: decompose 應輸出結構化章節樹 outline.json(而非僅 outline.md)

- 日期:2026-07-08
- 類型:feature request
- 元件:docxmcp `document.action=decompose`
- 提出脈絡:專利報告 docx 大章搬移 + 內容整併任務

## 問題

Word 的章標編號(天干「壹貳參」大章 + 阿拉伯數字「一~32」子節)是 `numbering.xml`
驅動的**自動編號**,段落 XML 本身不含編號文字。decompose 目前只產出:

- `outline.md`:純 markdown 標題行(`### 十、`、`#### (一)`),這些顯示編號是
  decompose 掃描時**重新推導補上的**,不是穩定 id,且是降級後的線性文字。

後果:AI 消費 decompose 產物做「搬章 / 併章」推理時,失去了「每段屬於哪個大章、
第幾層、穩定錨點是什麼」的結構化記憶,只能自行 byte-scan document.xml 重建章塊樹
(本任務即自寫 split_chapters.py 補救)。使用者一針見血:decompose 是不是該主動
補結構讓 AI 理解整體框架。

## 建議

decompose 額外輸出 `outline.json` 結構樹,每節點含:

```json
{
  "level": 1,                      // 1=Heading1 大章, 2=子節, ...
  "heading_style": "1",            // pStyle val
  "text": "全局分布統計",           // 標題純文字(不含自動編號)
  "stable_id": "_Toc234423238",    // bookmark name 或 w14:paraId,搬移後仍可追
  "para_index": 132,               // 在 body top-level 序列的索引
  "img_count": 6,                  // 該節點(至下一同層標題前)含圖數
  "tbl_count": 0,
  "children": [ ... ]
}
```

## 關鍵澄清(寫入端不需改)

「assemble 時消手動編號、交回 Word 自動編號」**現況已成立**——編號本就不在段落
XML 裡(numbering.xml 自動算),搬章塊後 Word 一開即重排。缺口**只在讀取端**的
結構樹表達,不涉及寫入端的編號還原。故本 FR 範圍僅限 decompose 輸出,不動
assemble / pack。

## 驗收

- decompose 產出 outline.json,結構樹層級正確、stable_id 可追、img/tbl count 守恆。
- AI 可直接用 outline.json 做章塊搬移/合併推理,無需自寫 splitter。

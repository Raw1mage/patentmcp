# SOP: 用 docxmcp Mode A 組裝技術洞察報告 DOCX

> **唯一正規路徑**:報告 DOCX 一律走 docxmcp `assemble`。**禁止**用 LibreOffice HTML→docx 或 pandoc 硬轉當正式交付——那偏離 docxmcp byte-preserving 契約,且本 session 已實證會在「圖片內嵌」「樣式」上踩坑。

## 為什麼是 docxmcp 而非 LibreOffice/pandoc
- enablement routing 規定 `.docx` 一律走 `docxmcp_*` toolchain。
- LibreOffice 的 HTML→docx「Writer/Web」濾鏡會把 `file://` 圖片存成連結而非內嵌(實測產出 **0 張圖**),要 base64 data URI 才嵌得進去——治標而非正規。
- docxmcp Mode A 用 cht 模板套樣式 + 自動編號,產出完整 OOXML 封裝(styles/numbering/theme/headers/footers),可被 `probe` 驗證。

## Mode A 流程(實測可行)

### 1. 準備報告 markdown

> ## 🔒 交付硬契約(一句話總綱,違反即不合格)
> **交付物一定要走 cht template 產出 docx;每一個內容元素的樣式必須是 template 預定樣式之一(標題X / 標X內 / 標X點 / 標X號 …);一定要有標題頁 + TOC 頁。**
>
> 拆解成可驗收的四條:
> 1. **template 強制**:`assemble` 一律帶 cht template(預設 `cht_template.dotx`,`heading 1`–`5` 帶自動編號 `numPr`)。禁止裸 assemble、禁止 LibreOffice/pandoc 硬轉。
> 2. **零 Normal orphan**:每個段落都必須落在 template 預定樣式 —— 標題走 `標題X`(由 `#/##/###` 階層決定)、內文走 `標X內`、條列走 `標X點`/`標X號`。**任何 rebuild 後仍是 `Normal` 的段落都是 orphan = 不合格**,須回頭把該行改成正確 markdown 形式(標題化、或 `- `/`1. ` 條列、或 `<!-- style: X -->`),不可放著。
> 3. **標題頁 + TOC 頁必備**:順序固定 `標題頁 → TOC 頁 → 內文`。標題頁用 template 封面樣式(`置中大大`/`置中大`/`靠左大`),TOC 頁插真正的 Word TOC field(`TOC \o "1-3" \h \z \u`),非純文字佔位。
> 4. **不可手動編號標題**:標題文字不要自己打 `第一章`/`1.1`/`一、`,assemble 會 strip,讓 template 自動編號當唯一真相。
> 5. **標題只放短句,詳情下沉**:凡樣式為 `標題X`(`#/##/###`)者,**一律只能是短句/標籤**(名詞片語,不寫整句說明、不帶句號結尾、不塞細節)。該標題要講的內容**必須另起下一段用 `標X內` 說明**。禁止「把一整段說明文字當成標題」或「標題後直接接條列而無內文引言」。範式:`### 雙階段閘口狀態機`(短句標題)→ 換行 → `本系統將專案分為設計與施工兩大治理階段…`(標X內 詳情)。
>
> 這五條是文件編輯能力,**統一規範在 docxmcp companion skill `doc-workflow`**(B.5 markdown 契約 + front-matter 強制 + `標N{內,點,號}` depth-aware 樣式 + 標題短句紀律)。撰寫前務必 `skill(name="doc-workflow")`。本檔只負責把它釘成 patentworks 報告的交付閘。

- 完整 `#`/`##`/`###` 標題階層(decompose-must-build-hierarchy:flat dump 會讓 assemble 無法套模板編號)。
- 圖片引用用**契約格式**:`![alt](media/figN.png){width=6in}`。

> **標題階層是文件編輯能力,歸 docxmcp 的 companion skill `doc-workflow`,不是 patentworks 的專屬職責。** 撰寫 `body.md` 時的「主動標題化紀律」(每個該標題化的段落必須打成 `##`/`###`,而非留成內文)由 doc-workflow A.2.2 統一規範。**本報告是 greenfield Mode A authoring(從零寫,無 signals.json)**,務必先 `skill(name="doc-workflow")` 載入,遵守其 greenfield 標題紀律與 `標N{內,點,號}` depth-aware 樣式契約。
>
> 機制提醒(為何「該標題化的文字變內文」):模板的 `標N{內,點,號}` 樣式是 **depth-aware**,深度只由前面的 `#/##/###` 標題建立。段落若不打成標題,depth 永遠停在 0 → 全部落 `Normal` → 模板多階標題設計失效。每個專利的「白話技術解析」、各章節編號子項都該是 `###`,不可是裸行。

### 2. 本地組 package
package 目錄需含三件:
```
.docxpkg/
├── body.md              # 報告全文,圖片引用改 media/ 相對路徑
├── manifest.json        # 見下方關鍵
└── media/
    ├── fig1.png
    └── ...
```

**manifest.json 關鍵(本 session 最大雷點)**:
```json
{
  "format": "docx",
  "title": "...報告標題...",
  "body": "body.md",
  "media_dir": "media"
}
```
- ⚠️ **`format` 必須是 `"docx"`,絕不可是 `"markdown"`**。assemble 讀到 `source.format: "markdown"` 或 `format: "markdown"` 會走「markdown 目標」分支,直接回 `DOCUMENT_ASSEMBLE_UNSUPPORTED: assemble is not supported for markdown`。本 session 為此卡了多回合。
- 不要自創 `"schema": "docxmcp/manifest@1"` 等欄位 signal;保持最小化。

### 3. 上傳取 token
```bash
cd .docxpkg && tar -cf - . | curl -s --unix-socket <docxmcp.sock> \
  -X POST -H 'Content-Type: application/x-tar' --data-binary @- \
  http://docxmcp.local/files
# → {"token":"tok_...","doc_dir":"..."}
```

### 4. assemble
```
docxmcp_document(action="assemble", doc_dir="tok_...", title="...報告標題...")
# → ok=True; 產出 rebuilt.docx
```
- `doc_dir` 直接吃 token 字串。
- 成功回傳 `rebuilt.docx` 的 blob 路徑。

### 5. 下載回交付位置
```bash
curl -s --unix-socket <docxmcp.sock> \
  "http://docxmcp.local/files/<token>/blob/rebuilt.docx" \
  -o "報告檔名.docx"
```

### 6. probe 驗證(交付閘,必做)
```
# 先上傳成品取單檔 token,再 probe
docxmcp_document(action="probe", token="tok_...")
# → ok=True
```
驗證點(全過才算交付):
- **圖片內嵌**:`unpacked/word/media/image1.png` ... 應有 N 張(對應 N 張圖表)。
- **完整 OOXML 封裝**:styles.xml / numbering.xml / theme1.xml / headerN.xml / footerN.xml 齊全。
- **heading 自動編號**:`document.xml` 含 `<w:numId>` 引用(模板編號生效,非 flat dump)。
- **inline drawing**:`<wp:inline>` / `<a:blip>` 計數 ≥ 圖表數。
- **三地內容齊全**:抽查關鍵公開號 / 中文案技術詞是否在 document.xml。

## 雷點教訓
1. **manifest 的 format signal 是成敗關鍵**:`markdown` → 直接被拒;`docx` → 成功。這是本 session 燒最多回合的單點。
2. **`assemble` 需要 package(body.md + manifest.json),不是裸 markdown**:只 stage 一個 .md 不會自動生成 manifest,assemble 會找不到。
3. **不要因為 assemble 一次失敗就 pivot 到 LibreOffice**:那是便宜行事。失敗時先查 manifest 的 format、package 結構,而非換工具繞道。
4. **`probe ok=True` 才是交付證據**:render/convert 成功不等於圖片有內嵌、樣式有套上。一定要 probe 驗證圖片與 OOXML 封裝。

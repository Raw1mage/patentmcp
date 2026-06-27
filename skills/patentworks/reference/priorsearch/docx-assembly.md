# SOP: 用 docxmcp Mode A 組裝技術洞察報告 DOCX

> **唯一正規路徑**:報告 DOCX 一律走 docxmcp `assemble`。**禁止**用 LibreOffice HTML→docx 或 pandoc 硬轉當正式交付——那偏離 docxmcp byte-preserving 契約,且本 session 已實證會在「圖片內嵌」「樣式」上踩坑。

## 為什麼是 docxmcp 而非 LibreOffice/pandoc
- enablement routing 規定 `.docx` 一律走 `docxmcp_*` toolchain。
- LibreOffice 的 HTML→docx「Writer/Web」濾鏡會把 `file://` 圖片存成連結而非內嵌(實測產出 **0 張圖**),要 base64 data URI 才嵌得進去——治標而非正規。
- docxmcp Mode A 用 cht 模板套樣式 + 自動編號,產出完整 OOXML 封裝(styles/numbering/theme/headers/footers),可被 `probe` 驗證。

## Mode A 流程(實測可行)

### 1. 準備報告 markdown
- 完整 `#`/`##`/`###` 標題階層(decompose-must-build-hierarchy:flat dump 會讓 assemble 無法套模板編號)。
- 圖片引用用**契約格式**:`![alt](media/figN.png){width=6in}`。

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

# refs/ — 補充參考材料(外部 repo)

供**參考學習**用的外部專利相關專案。各為獨立外部專案、各自授權;已去除其 `.git`。

> ⚠️ **授權紅線**:不同 repo 授權不同。**MIT** 可在標註出處下借鑑/取用程式碼;**AGPL-3.0** 為強著佐權,**僅供研讀,不得將其程式碼複製進本產品(patentmcp / patentworks)**,以免傳染 AGPL 義務。專利法規則、撰寫原則等「事實/知識」本身不受著作權保護;本專案的 drafting 知識皆**自行蒸餾重寫**為條列,非逐字搬運。

## 清單

### Claude-Patent-Creator — MIT
- RobThePCGuy/Claude-Patent-Creator。US 專利建立系統(MCP + Claude Code plugin)。
- **可借鑑**:合規檢查理念(112(a)/(b)、MPEP 608)、法律 RAG(FAISS+BM25 over MPEP/USC/CFR)、claims-first 階段、圖式參考編號疊加(Graphviz)。
- **已不採**:BigQuery 檢索(我們用 GPSS/Google)、13-skill 爆量、純 US 法。

### patent-disclosure-skill — MIT
- handsomestWei/patent-disclosure-skill。CN 技術交底書(invention disclosure)產出 skill。
- **可借鑑**:交底書 front-end、intake 問題集、專利點挖掘、**脱敏**、自檢閉環 → 已化入 `skills/patentworks/flows/disclosure.md` 與 `reference/disclosure/`。
- **已不採**:CNIPA 爬蟲(我們用 patentmcp)、自寫 mermaid/docx 工具(交 docxmcp/drawmiat)。

### PatentWriterAgent — ⚠️ AGPL-3.0
- ninehills/PatentWriterAgent。中文專利寫作智能體(8 層多 Agent 流水線)。
- **本專案血緣源頭**:同架構、同 `PATENT_SKILL.md`、同範例輸出 uuid(`9ba0a678-…`);我們原 PatentDrafter 即源於此。
- **可借鑑(僅研讀)**:整體 workflow 設計、PATENT_SKILL.md 的撰寫知識(已自行蒸餾為 `reference/drafting/{common,cn}.md`)。
- **紅線**:**AGPL,勿複製其程式碼進本產品。**

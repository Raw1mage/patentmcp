# Flow: Screening(前案/現況檢索篩選)

把一個技術問題,變成一張**已評分、可稽核、人類可讀的 spreadsheet**。領域背景見 `../../patent-practitioner-workflow.md`。

> 兩種子情境(判讀準則與產出不同):
> - **可專利性**(描述技術特徵、有沒有人申請過):消化準則=**要件對照**(這篇揭露我哪幾個要件);產出=表 + **新穎性綜述**(最接近前案、揭露/未揭露要件、你的差異點)。輸入是特徵→須先**推候選 CPC 請使用者圈**。
> - **landscape**(某領域別人怎麼做):消化準則=**主題分群**(by approach/玩家);產出=**技術地圖**。注意「文獻」若含**非專利論文**,patentmcp 不涵蓋,須明確界定或另接文獻源。

## 不變式

1. **最終交付一律是 Agent 友善、人類可讀的 CSV 表格**,經 token+download_url handle 交付。
2. **檢索一律以 CPC 領域限縮**(US/CN 為主,TW 低價值不預設)。
3. **檢索一律用單一入口 `patent_search`**——來源梯已內建於 server(TIPO GPSS 官方首選 → EPO → USPTO PPUBS → gated 爬蟲),依憑證與查詢軸自動路由,每級嘗試記入 `provenance`;爬蟲尾級須 `allow_scraping=True`(使用者明確同意),否則官方全 miss 即回 `SCRAPING_REQUIRED`。單號取文/取圖依 `../SKILL.md` §5 各級能力知識選工具。
6. **建表在本地(R13 landing plane)**:`patent_search` 回 records JSON 後,**用本地 `screening_build.py` 建 CSV**——不再有 `build_screening_table` 工具(已下架 → `TOOL_LANDED`)。家族去重/欄位隨選/CSV 組裝都是確定性後處理,落在 host,不佔 context。
4. **AI 預篩+評分（1-5級）+解釋,人類做最終相關性裁決**;表保留原始欄並排 AI 加值欄供稽核。
5. **每讀一篇就在表上沉澱壓縮蒸餾**(讀 ~300 token → 寫 ~50 token),不回貼原文。

## 輸入
- 技術問題;**CPC 領域**(必要,未給則提候選請圈);選用日期/類型/關鍵詞。

## 流程
1. **召回(工具)+ 建表(本地腳本)**:先呼叫 patentmcp **`patent_search(cpc, keyword, ...)`** 拿 records JSON(server 端沿來源梯檢索,回 `{records[], source, provenance[], gaps[], total}`);把 records JSON 存成檔,再用**本地** `python3 skills/patentworks/scripts/screening_build.py --in records.json --out screening.csv --purpose landscape [--source records]` 做家族去重→欄位隨選→CSV。**原始候選列走 records JSON / CSV,不整批進 context。**
   - **件數過多**:`patent_search(num=...)` 控回收量;過廣時依 provenance/gaps 收斂(嚴 CPC/加詞/縮日期)後再查。
   - **欄位隨選**(`--purpose`):`landscape`(+分類)/ `priorart`(+日期+CPC)/ `fto`(+日期+申請人+法律狀態)/ `minimal`;`--extra`/`--exclude`(逗號分隔欄鍵)微調。核心欄(專利號/申請號/名稱/摘要/獨立項/家族)永留;AI 欄永遠附加。`--help` 印完整契約。
   - **誠實缺口**:`patent_search` 回的 `gaps` 標明該來源填不了的欄(如 Google 路無 family_id、法律狀態需 EPO/USPTO)。
2. **讀表消化(agent 端)**:以 CSV 分批讀(每批 ~30 列的摘要+獨立項),不一次灌進 context。每列判讀後**寫回同一 CSV**:`相關性(1-5級)`（Level 1-5: 1=無關, 2=低度相關, 3=中度相關, 4=高度相關, 5=極相關/最接近前案）、`技術要點`(1–2 句,用本案語彙)、`命中/落差要件`、`理由`。
3. **深讀(僅 shortlist)**:逐字 claims 首選 `patent_search(pub_number="...")`(三地通用,底層 GPSS 首選);US 案 Claim 1 回空(`claim1_empty: true`)時走 `ppubs_batch_get_claims` 補抓;非 TW 案全文/圖說可用 `google_get_patent_claims`/`google_get_patent_description`(BigQuery)。`gpatents_get` 僅為上述皆填不了時的最後手段,且須使用者同意。
4. **可專利性綜述(若是該子情境)**:彙整最接近前案 + 要件覆蓋 → **你的差異點**。
5. **交付(WebDAV working cache)**:寫回後的 CSV 即交付物。輕量情境可直接把 CSV 放進專案 `output/`;要**固化工作區 + 顯式落地**時走 WebDAV cache——`cache_provision(subject_id, owner_identity)` 拿 `mount_path` + 一次性 Basic 憑證 → rclone/davfs2 掛載後把 CSV/PDF/圖**PUT 進 mount**(取代已下架的 `stage_file`,bytes 不過 context)→ `cache_export(subject_id, target, owner_identity)` COPY 落地到 truth store → `cache_close`(dirty 未 export 會被 `WORKSPACE_CLOSE_DIRTY` 擋)。相關 PDF 用 `fetch_patent_pdf`(官方路由優先,預設 `allow_scraping=False`);代表圖從已下載 PDF 走**本地** `figure_extract.py --pdf ... --out ...png`(需 poppler),TW 案優先 `gpss_download_representative_figure`(需同意)。給使用者的「答案」是白話綜述 + handle/mount,不是貼表。

## Token 紀律
search 只帶分流必要欄;完整 claims/全文只對 shortlist 取且落地成 handle、不回 context;蒸餾是壓縮。

## 銜接
`screening → analysis`。當完成前案篩選並建立 shortlist（包含 Scored CSV 與專利號 handles）後，若使用者需要進一步分析本案與前案之具體技術特徵對應、要件比對與特徵差異，應將這些 shortlist 材料與交底書材料打包為 `AnalysisInput` 封包，並指引 Agent 進入 `analysis.md` 流程中進行深度技術分析。

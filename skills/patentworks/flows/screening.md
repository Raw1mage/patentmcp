# Flow: Screening(前案/現況檢索篩選)

把一個技術問題,變成一張**已評分、可稽核、人類可讀的 spreadsheet**。領域背景見 `../../patent-practitioner-workflow.md`。

> 兩種子情境(判讀準則與產出不同):
> - **可專利性**(描述技術特徵、有沒有人申請過):消化準則=**要件對照**(這篇揭露我哪幾個要件);產出=表 + **新穎性綜述**(最接近前案、揭露/未揭露要件、你的差異點)。輸入是特徵→須先**推候選 CPC 請使用者圈**。
> - **landscape**(某領域別人怎麼做):消化準則=**主題分群**(by approach/玩家);產出=**技術地圖**。注意「文獻」若含**非專利論文**,patentmcp 不涵蓋,須明確界定或另接文獻源。

## 不變式

1. **最終交付一律是 Agent 友善、人類可讀的 CSV 表格**,經 token+download_url handle 交付。
2. **檢索一律以 CPC 領域限縮**(US/CN 為主,TW 低價值不預設)。
3. **AI 預篩+評分+解釋,人類做最終相關性裁決**;表保留原始欄並排 AI 加值欄供稽核。
4. **每讀一篇就在表上沉澱壓縮蒸餾**(讀 ~300 token → 寫 ~50 token),不回貼原文。

## 輸入
- 技術問題;**CPC 領域**(必要,未給則提候選請圈);選用日期/類型/關鍵詞。

## 流程
1. **召回 + 落地(一個工具)**:呼叫 patentmcp **`build_screening_table(cpc, keyword, purpose, ...)`**。它在 server 端 search→家族去重→切 Claim1→**寫成 CSV 落地 token store**,只回 `{handle, count, deduped, source, columns, gaps}`——**原始候選列不進 context**。
   - **>300 件 → 回 `too_broad`**,不產表;依 suggestion 收斂(嚴 CPC/加詞/縮日期)後再呼叫。
   - **欄位隨選**(`purpose`):`landscape`(+分類)/ `priorart`(+日期+CPC)/ `fto`(+日期+申請人+法律狀態)/ `minimal`;`extra_fields`/`exclude_fields` 微調。核心欄(專利號/申請號/名稱/摘要/獨立項/家族)永留;AI 欄永遠附加。
   - **誠實缺口**:回傳的 `gaps` 標明該來源填不了的欄(如 Google 路無 family_id、法律狀態需 EPO/USPTO)。
2. **讀表消化(agent 端)**:以 CSV 分批讀(每批 ~30 列的摘要+獨立項),不一次灌進 context。每列判讀後**寫回同一 CSV**:`相關性`(相關/可能/否)、`分數`(H/M/L)、`技術要點`(1–2 句,用本案語彙)、`命中/落差要件`、`理由`。
3. **深讀(僅 shortlist)**:需要時 `gpatents_get` 取完整 claims 做要件對照。
4. **可專利性綜述(若是該子情境)**:彙整最接近前案 + 要件覆蓋 → **你的差異點**。
5. **交付**:寫回後的 CSV 即交付物 → `stage_file(path)` 回 handle(或回傳 build 時的同一 handle)。相關 PDF/代表圖用 `gpatents_download_pdf/figure` 取 handle。給使用者的「答案」是白話綜述 + handle,不是貼表。

## Token 紀律
search 只帶分流必要欄;完整 claims/全文只對 shortlist 取且落地成 handle、不回 context;蒸餾是壓縮。

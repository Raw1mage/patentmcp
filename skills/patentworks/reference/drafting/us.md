# 起草知識:US(35 USC / MPEP 特有要點)

> 種子版本:高信心核心要點。實作中依實際案件補充(MPEP 細節、判例)。與 common.md 並用。

## 1. 可專利性法條框架
- §101 適格標的:process / machine / manufacture / composition of matter;排除抽象概念、自然法則、自然現象(Alice/Mayo 兩步測試);純軟體/商業方法須綁具體技術改進。
- §102 新穎性(AIA:申請日前的公開/銷售/使用構成 prior art;有 1 年 grace period 對發明人自己的揭露)。
- §103 非顯而易見性(obviousness;KSR 彈性判斷;以 PHOSITA 角度)。
- §112 揭露與請求項要件(見下)。

## 2. §112(a) — 說明書三要件
- **Written description**:須顯示發明人於申請時確實擁有所請發明的全部範圍。
- **Enablement**:本領域技術人員無需過度實驗即可製造與使用(Wands factors)。
- **Best mode**:揭露發明人所知最佳實施方式(AIA 後不再是無效/不可執行事由,但仍為法定要求)。
- 請求項範圍須有說明書支持;概括/功能性請求項須足夠代表性實施例。

## 3. §112(b) — 請求項明確性
- 請求項須 distinctly claim;不得 indefinite。
- **Antecedent basis(前置基礎)**:首次出現用 "a/an",其後回指用 "the/said";"the X" 無前置 = 不明確。
- 相對用語(about, substantially)需說明書給判斷基準。
- §112(f) means-plus-function:"means for + 功能" 解釋為說明書對應結構及其均等;避免無意觸發(用結構性名詞)。

## 4. US 請求項格式
- **單句**:一個請求項一個句子(以句號結束),元素間用分號/逗號分隔。
- 三段:**preamble**(前序)+ **transition** + **body**(主體)。
- transition 用語:`comprising`(開放,含未列元素)/ `consisting of`(封閉)/ `consisting essentially of`(半封閉)。
- 獨立項 + 附屬項("The [device] of claim 1, wherein…");附屬項範圍須窄於所依附項。
- 多面向:method / system(apparatus)/ computer-readable medium / 視案件加 means。
- multiple dependent claim 允許但有規費考量,且不得依附另一 multiple dependent claim。

## 5. 說明書章節(US 慣例)
- Title → Cross-Reference to Related Applications → Field of the Invention → Background → Summary → Brief Description of the Drawings → Detailed Description → Claims → Abstract。
- Detailed Description 須以 reference numerals 對應圖式;每個請求項元素應在說明書找到支持。

## 6. 摘要與形式(MPEP 608)
- Abstract:單段、**不超過 150 字(words)**;不得含請求項式法律用語("means"、"said")、不得純推測用途。
- 圖式:黑白線稿、reference numerals、FIG. N;不得有未在說明書提及的標號。
- 不得新增 new matter(申請後不可加入原揭露外內容)。

## 7. 義務與策略
- **Duty of disclosure / IDS**:申請人有義務向 USPTO 揭露已知重要 prior art(37 CFR 1.56);前案檢索結果可轉成 IDS 清單。
- Provisional → Non-provisional 12 個月;主張優先權。

## 待補
- MPEP 具體章節對照、101 適格的最新判例、設計專利(Design)規範、PCT 進入美國國家階段細節。

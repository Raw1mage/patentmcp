# Proposal: patentworks_iterative-convergence-search

## Why

- 影像式人類異常偵測（跌倒/入侵/徘徊/暴力/遺留物/墜落/昏倒/聚集/久臥/求救/告警）前案檢索需要**可證明覆蓋完整**的方法論。
- 舊做法把矩陣綁死成固定的「事件×場域兩層」笛卡兒積,產生兩個病灶:(1) 軸向預設,無法證明涵蓋所有可能情況;(2) rigor gate 用固定 proxy 誤判嚴謹度。
- 使用者 2026-07-09 定案了一套**資料驅動的逐輪收斂演算法**取代固定矩陣,需固化為 spec 以避免臨時 todo 漂移。

## Original Requirement Wording (Baseline)

- "我甚至覺得你可以先做一輪所有 [ 單一關鍵字 and (IPC pool) ] 的查詢,把數字表拉出來,再針對數量超過者做兩兩 and 去限縮,得到第二輪數字統計表,再針對第二輪數字仍超過的去進行三關鍵字排列組合,依此類推"
- "任何一個檢索組合,即使只有單項,能限縮到 1000 以下就算數"
- "IPC and (devices) and (scenarios)"（軸向定調:IPC 固定必備,其餘自由組合）
- "寫成 plan"（2026-07-09,本 spec 的建立指令）

## Requirement Revision History

- 2026-07-08: initial draft created via plan-init.ts
- 2026-07-09: 使用者定案逐輪收斂演算法 + <1000 驗收基準,要求固化為 plan

## Effective Requirement Description

1. **唯一固定軸 = IPC 聯集**（13 群）。其餘維度（人/事/時/地/物）皆為自由可組合軸。
2. **逐輪收斂**:第 N 輪對「第 N-1 輪仍 ≥1000」的標的,增加一個關鍵字軸做 N-tuple AND 限縮,產生第 N 輪數字表;直到所有標的 <1000。
3. **驗收基準**:任何一個檢索組合(即使只有單項)只要能限縮到 total <1000,該標的即算「涵蓋完整」。1000 是唯一硬門檻。
4. **不預設軸向、不做完整笛卡兒積**:只對超標者下鑽,避免組合爆炸。
5. **GPSS 官方為唯一主路徑**,禁止 EPO fallback 造假(databases 過濾必須落實,TW 用 TWA/TWB、CN 用 CNA/CNB、US 用 USA/USB)。

## Scope

### IN
- 三國(US/TW/CN)影像式人類異常偵測領域的逐輪收斂檢索。
- 第 1 輪單關鍵字池(物 7 + 事 12 + 地 9 + 人 5 + 時 4 = 37 單項 × 3 國 = 111 條)。
- 逐輪產出數字表(round1-log.jsonl、round2-log.jsonl…),每輪篩超標者下鑽。
- 收斂完成後建家族去重全池 → 核心池 → 下游評分/報告。

### OUT
- 非影像式(純穿戴/純聲學無視覺)偵測不主打,但 devices 軸涵蓋作對照。
- 三國以外的司法管轄(EP/JP/KR…)本輪不納入。
- 報告本體撰寫(另有下游 spec/流程),本 spec 只到「收斂完成 + 數字表 + 池」。

## Non-Goals

- 不追求「每個關鍵字組合都跑」(笛卡兒積),只追求「每個標的都有一組 <1000 的出口」。
- 不以固定矩陣結構束縛軸向。

## Constraints

- GPSS `patent_search`:三段以上 AND + CL 全文會穩定 parse error → 第 1 輪用 TI/AB;收斂到小格再視需要升 TAC。
- patDB 代碼:US=USA,USB｜TW=TWA,TWB｜CN=CNA,CNB(逗號合併字串傳入 databases)。
- rigor gate(search_audit)需通過:class_anchors≥3、concept_groups≥3、jurisdictions≥3、boolean_combos≥2、queries≥12。

## What Changes

- campaign doctrine 從「固定事件×場域矩陣」改為「逐輪收斂演算法」。
- 新增逐輪 log schema(round-N-log.jsonl)與收斂盤點腳本。

## Capabilities

### New Capabilities
- 逐輪收斂檢索演算法: 資料驅動的 N-tuple AND 下鑽,以 <1000 為收斂判準。
- 第 1 輪關鍵字池(人事時地物,三語各一套): 收斂的字典基礎。

### Modified Capabilities
- campaign 檢索矩陣: 從固定笛卡兒積 → 自由組合逐輪收斂。

## Impact

- `output/priorart_anomaly_vision/01_search/` 下的 log schema 與 campaign doctrine。
- `skills/patentworks/` 的檢索方法論文件。
- 下游:全池家族去重、核心池篩選、評分、報告數值全部連動重算。

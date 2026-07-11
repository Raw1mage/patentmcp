# Tasks: patentworks_iterative-convergence-search

## M1 方法論固化
- [x] M1-1 建 plan package (research profile)
- [x] M1-2 proposal.md — 逐輪收斂演算法 + <1000 驗收基準
- [x] M1-3 design.md — DD-1~DD-6 + 收斂狀態機
- [x] M1-4 tasks.md — 執行 checklist
- [ ] M1-5 第 1 輪關鍵字池審定 (round1_keyword_pool.md 已存在,待確認增減詞)

## M2 第 1 輪 (單關鍵字 AND IPC)
- [~] M2-1 US 事件軸 E1-E12 — 已跑 9/12 (缺 E1 跌倒/E4 徘徊/E7 墜落)
- [ ] M2-2 US 物/地/人軸 (D1-7, S1-9, P1-5)
- [ ] M2-3 TW 全套 37 單項
- [ ] M2-4 CN 全套 37 單項
- [ ] M2-5 產出第 1 輪完整數字表 → 篩 ≥1000 標的

## M3 第 2 輪 (兩兩 AND)
- [ ] M3-1 對第 1 輪 ≥1000 標的做兩兩關鍵字 AND
- [ ] M3-2 產出第 2 輪數字表 → 篩仍 ≥1000

## M4 第 3+ 輪 (三關鍵字排列組合，依此類推)
- [ ] M4-1 對第 2 輪仍 ≥1000 標的做三關鍵字 AND
- [ ] M4-2 依此類推直到全部 <1000
- [ ] M4-3 收斂完成證明:每個標的都有 <1000 出口

## M5 rigor gate + 收斂驗收
- [ ] M5-1 轉換逐輪 log → search_audit schema
- [ ] M5-2 跑 search_audit rigor gate → verdict=PASS
- [ ] M5-3 覆蓋完整性報告 (所有可能情況都涵蓋)

## M6 下游連動 (收斂後)
- [ ] M6-1 家族去重全池 (screening_build.py)
- [ ] M6-2 核心池篩選
- [ ] M6-3 三陣營評分 + TF 矩陣熱點重算
- [ ] M6-4 報告數值連動修正 (rN 後綴另存)

## Validation
- 驗收基準:每個標的最終都有一組 AND 組合 total <1000
- rigor gate PASS (class_anchors≥3, concept_groups≥3, jurisdictions≥3, boolean_combos≥2, queries≥12)
- 全程 GPSS 官方、真本國案、零 EPO fallback 造假

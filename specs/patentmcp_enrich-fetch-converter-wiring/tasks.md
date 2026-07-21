# Tasks: patentmcp_enrich-fetch-converter-wiring

## 1. 偵查取文送查點

- [x] 1.1 grep `patents.py` 全取文降級鏈送查點清單（`patent_get_claim1` / `patent_enrich_backfill` 送 gpatents/google/GPSS/EPO 各跳），列出每點目前送的號碼來源 — 坐實 5 點裸送: GPSS主查@1252 / EPO@1344 / gpatents尾級@1431 / enrich_backfill gpatents@4992 / PPUBS@1315(自製strip,保留)
- [x] 1.2 確認每個送查點對應的 per-target converter（gpatents/google→strip-0、GPSS→to_gpss_rest、EPO→to_epo_variants）— strip-0 canonical 實測: normalize_pubno 對 US grant kind(B1/B2) 不剝(mid-string letter blocks regex),改用 to_gpss4_web body + lstrip

## 2. 接線

- [x] 2.1 每個送查點在呼叫外部源前插入 per-target 正規化（復用既有 `to_*`，不新造格式邏輯）— GPSS→to_gpss_rest / EPO→to_epo_variants 逐變體 / gpatents×2→_to_gpatents_canonical(組合 to_gpss4_web+lstrip)
- [x] 2.2 converter 識別不出格式時 fail-fast，不 silent 原號直送 — _to_gpatents_canonical 對 body 不合 `^[IMD]?\d+$` 回 None; 呼叫端 gpatents 尾級回 UNPARSEABLE_PUBNO error / enrich_backfill 記 gap continue

## 3. L3 實查閘

- [x] 3.1 新增取文端 roundtrip 實查測試向量（前導零 US grant 號跑 `patent_get_claim1` 斷言 converter 被呼叫且取文成功）— tests/test_fetch_converter_wiring.py: GpatentsSendSiteSpyTest spy 傳入號=US9993161 且 success; EPO/GPSS send-site spy 亦斷言收到 converter 正規化號
- [x] 3.2 驗證：改回原號直送時該測試 fail — reverse case 斷言 canonical != raw(閘有鑑別力); spy 直接斷言送查點收到號=canonical,漏接時當場 fail

## 4. 驗證

**Validation evidence**: pytest 329 pass / 0 fail (全套件) + 37 pass / 0 fail (新增 L3 gate + send-site spy); orchestrator 獨立驗證 5 送查點接線到位。

- [x] 4.1 實測 `patent_get_claim1("US09993161B1")` → success + claim1 落地 — 單元層(mock gpatents client)斷言送查點收到 US9993161 且 success=True/source=google_patents; live 打外部視配額
- [x] 4.2 既有 pytest 全綠（未破壞既有行為）— 329 passed / 1 deselected(test_routing_tipo_priority 為 pre-existing 無憑證環境失敗,git stash 驗證與本次修改無關) + 新測 37 pass
- [x] 4.3 更新 BR_20260719 R3 標 resolved + 寫收尾 event log

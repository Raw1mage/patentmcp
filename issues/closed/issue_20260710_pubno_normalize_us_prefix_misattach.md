# BR: pubno 正規化對無國別前綴公開號誤加 US 前綴

日期：2026-07-10 ｜ 嚴重度：中 ｜ 狀態：open

## 症狀

用 `patentdb_local.py` 落地 EPO family 成員書目時，無標準兩碼國別前綴的公開號（JP 授權號 `JP7207793B2` 傳入時若格式為 `7207793B2`、KR `102021441B1` 等）被正規化邏輯誤加 `US` 前綴，產生 `USJP7207793B2` / `USKR102021441B1` 這類髒 pubno 入庫。

## 實證

2026-07-10 v3 D5 family 補抓 15 件，其中 JP×2 + KR×1 落地後 pubno 帶雙重前綴，手動 UPDATE 修回乾淨號 + country 欄。另 D4 slice 落地也見 `USKR20250088836A`、`USAU2024204570A1` 同款髒號（歷史殘留，未清）。

## 根因方向

正規化 fallback「無法識別國別 → 預設 US」過於武斷；對已含合法國別碼（JP/KR/AU）的號應先嘗試剝離識別，識別失敗應 fail-fast 要求 country 參數，不 silent 預設。

## 建議修法

1. 正規化前先用 `^([A-Z]{2})\d` 匹配既有國別碼；命中即用之。
2. 無法識別時 fail-fast（拒收並回錯誤），不預設 US——符合使用者「禁 silent fallback」天條。
3. 附帶：掃庫清既有 `US[A-Z]{2}\d` 髒號（`USKR%`/`USAU%`/`USJP%`）做一次性修復 migration。

## Workaround（現行）

落地後手動 UPDATE pubno/country；本案 v3 已修 3 件。

---
## 結案（2026-07-19）

**修法落地（三件套）**：
1. **container SSOT**（`src/patent_mcp_server/patentdb_store.py`）：`_KNOWN_CC` 已於 commit b66b387 修為全國別碼先剝離；本次補 `CZ/GR/TR`（庫內實證出現的髒號國別）。
2. **host vendored copy**（`skills/patentworks/scripts/patentdb_local.py`）：原本仍是舊版五前綴 + `country="US"` 預設——**髒號持續產生的實際源頭**。已同步為 `_KNOWN_CC` 全碼剝離版，並以 10 case parity test 證實 host==container。
3. **一次性 migration**（patentdb.sqlite，62706 rows）：
   - 備份 `patentdb/.history/patentdb.pre-pubno-migration-20260719.sqlite`
   - 刪 1 筆 collision dup（`USDE102025140339A1`，乾淨版 `DE102025140339A1` 已在庫且資料完整度相同）
   - UPDATE 1113 筆 `US<CC>…` 髒號 → 剝 US 前綴、修 `country`/`normalized_no`（KR506/DE333/JP133/AU37/FR16/GB15/TW/CN/TR/CZ/GR 等）
   - 補修 17 筆 `normalized_no` 殘留雙前綴
   - FTS rebuild + `PRAGMA integrity_check` = ok；髒號殘留掃描 = 0

**注**：`RE\d+`（US reissue）正確保留 US 歸屬，不在 `_KNOWN_CC`。

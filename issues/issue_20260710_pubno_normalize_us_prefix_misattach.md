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

# Spec: patentmcp_gpss-account-rotation

## Purpose

`GPSSClient` 對 GPSS REST API 檢索時，SHALL 在單一 userCode 帳號的時段配額用盡時，自動輪替至帳號池中下一個未用盡帳號並重試同一請求；當帳號池全部用盡時，SHALL 以結構化錯誤 fail-fast，不靜默降級、不偽裝成查無資料。rotation 對所有呼叫端透明（共用實例、`search()` 簽名不變）。

## Requirements

### Requirement: 多帳號額度輪替

系統 SHALL 支援以 `GPSS_USER_CODES`（逗號分隔）設定的 N 帳號池，並在偵測到 GPSS 額度用盡訊號時輪替至下一未用盡帳號重試。

#### Scenario: 首個帳號額度用盡自動換第二個

- **WHEN** 當前帳號回應 message 含 `Over download quantity`
- **THEN** 標記該帳號本次 process 用盡、游標移下一未用盡帳號、以新 userCode 重發同一請求並回傳其結果

#### Scenario: 全部帳號用盡 fail-fast

- **WHEN** 帳號池所有帳號均已標記用盡
- **THEN** 回傳 `{success:false, error_code:"GPSS_ALL_ACCOUNTS_EXHAUSTED", accounts_tried:N}`，不 fallback

### Requirement: 向後相容與可擴充設定

系統 SHALL 優先讀 `GPSS_USER_CODES`（逗號分隔，去空去重保序）；為空時退讀舊 `GPSS_USER_CODE` 單碼。新增帳號僅需於 `GPSS_USER_CODES` 尾部附加一個碼。

#### Scenario: 相容舊單碼設定

- **WHEN** 只設定了 `GPSS_USER_CODE`、未設 `GPSS_USER_CODES`
- **THEN** 帳號池 = 該單碼，行為與改動前一致

### Requirement: 額度訊號精準辨識（防誤判）

系統 SHALL 僅以 `over download quantity` / `over search quantity` 子字串（大小寫不敏感）判定額度用盡，SHALL NOT 將「查無資料」等其他非空 message 判為用盡。

#### Scenario: 查無資料不觸發輪替

- **WHEN** 回應 message 為查無資料類（不含額度用盡子字串）
- **THEN** 原樣回傳結果，不標記帳號用盡、不輪替

## Acceptance Checks

- [ ] `GPSS_USER_CODES` 逗號分隔解析（去空去重保序）
- [ ] 退讀 `GPSS_USER_CODE` 單碼相容
- [ ] 額度用盡 → 換帳號重試成功
- [ ] 全部用盡 → GPSS_ALL_ACCOUNTS_EXHAUSTED fail-fast
- [ ] 查無資料 message 不觸發輪替
- [ ] 全套既有測試不回歸

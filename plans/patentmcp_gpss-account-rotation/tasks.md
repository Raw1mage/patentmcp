# Tasks: patentmcp_gpss-account-rotation

## 1. 帳號池載入（DD-4）

- [x] 1.1 `GPSSClient.__init__` 解析帳號池：優先 `GPSS_USER_CODES`（逗號分隔、strip、去空、保序去重），為空退讀 `GPSS_USER_CODE` 單碼；建構參數 `user_codes: Optional[List[str]]` 覆寫 env
- [x] 1.2 保留 `self.user_code` property（回傳當前游標帳號）以相容既有 `configured()` 與任何外部引用
- [x] 1.3 `configured()` 改判斷帳號池非空

## 2. Rotation state machine（DD-1/DD-2/DD-3/DD-5/DD-6）

- [x] 2.1 `search()` 包 rotation 迴圈：迴圈取當前未用盡帳號組 query 發請求
- [x] 2.2 額度用盡偵測 helper `_is_quota_exhausted(message)`：子字串比對 `over download quantity` / `over search quantity`（大小寫不敏感）
- [x] 2.3 偵測用盡 → 標記當前帳號索引入 `self._exhausted` → 游標移下一未用盡帳號 → 重試
- [x] 2.4 全部帳號用盡 → 回 `{success:False, error_code:"GPSS_ALL_ACCOUNTS_EXHAUSTED", accounts_tried:N}` fail-fast
- [x] 2.5 非額度用盡回應（成功/查無/HTTP錯誤/parse失敗）原樣回傳，不換帳號

## 3. 設定與文件

- [x] 3.1 `.env`：`GPSS_USER_CODES=c2d198B6924a37D6,f77fB093dfdb34FD`（新碼優先、舊碼備援），移除單一 `GPSS_USER_CODE`（保留註解說明相容）
- [x] 3.2 `.env.example`：新增 `GPSS_USER_CODES` 註解說明（逗號分隔可擴充、相容舊 `GPSS_USER_CODE`）
- [x] 3.3 `gpss/__init__.py` 與 `client.py` docstring：單碼 → 帳號池 rotation

## 4. 驗證

- [x] 4.1 `tests/test_gpss_rotation.py`：帳號池解析（CODES 優先 / 退 CODE / 去空去重）
- [x] 4.2 額度用盡 → 換帳號成功（Fake GPSS：第一帳號回 over download quantity、第二帳號回正常結果）
- [x] 4.3 全部用盡 → GPSS_ALL_ACCOUNTS_EXHAUSTED fail-fast
- [x] 4.4 查無資料 message 不觸發 rotation（防誤判，DD-2）
- [x] 4.5 全套既有測試不回歸（`pytest tests/`）

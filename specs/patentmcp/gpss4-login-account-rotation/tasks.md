# Tasks: patentmcp_gpss4-login-account-rotation

## 1. 帳號池載入（DD-3）

- [x] 1.1 `GPSS4Session.__init__` 解析編號式帳號池：帳號1=`GPSS4_USERNAME`/`GPSS4_PASSWORD`，連續掃描 `_2`/`_3`… 至缺號止；成對完整才納入；建構參數 `accounts: Optional[List[Tuple[str,str]]]` 覆寫 env
- [x] 1.2 保留 `self.username`/`self.password` property（回傳當前游標帳號）相容既有 `_submit`/`configured`
- [x] 1.3 `configured()` 改判斷帳號池非空

## 2. Rotation state machine（DD-1/DD-2/DD-4/DD-5/DD-6）

- [x] 2.1 抽出 `_login_one_account()`：現有單帳號 CAPTCHA 重試迴圈，回成功 dict / raise
- [x] 2.2 `login()` 包 rotation 迴圈：取當前未失敗帳號 → `_login_one_account` → 成功回傳、失敗標記 `_failed_accounts` 並移游標重試
- [x] 2.3 全部帳號失敗 → `raise GPSS4LoginError("login failed after trying N account(s): ...")`
- [x] 2.4 `ensure_logged_in`/`get` re-login 用當前有效帳號（DD-6，不誤換）

## 3. 設定與文件

- [x] 3.1 `.env`：加 `GPSS4_USERNAME_2=<第二帳號>` / `GPSS4_PASSWORD_2=<密碼>`（實際憑證存於 `.env`，不入版控）
- [x] 3.2 `.env.example`：新增 `GPSS4_USERNAME_2`/`GPSS4_PASSWORD_2` 註解（編號式可擴充、相容單帳號）
- [x] 3.3 `docker-compose.yml`：注入 `GPSS4_USERNAME_2`/`GPSS4_PASSWORD_2`
- [x] 3.4 `gpss4/__init__.py` 與 `session.py` docstring：單帳號 → 帳號池 rotation

## 4. 驗證

- [x] 4.1 `tests/test_gpss4_login_rotation.py`：帳號池解析（編號式掃描/缺號停/成對完整/退單帳號）
- [x] 4.2 主帳號登入失敗 → 換第二帳號成功（Fake `_login_one_account`）
- [x] 4.3 全部登入失敗 → GPSS4LoginError（tried N）
- [x] 4.4 session re-login 用當前帳號不誤換（DD-6）
- [x] 4.5 全套既有測試不回歸（`pytest tests/`）

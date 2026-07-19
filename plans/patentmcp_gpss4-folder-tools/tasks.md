# Tasks: patentmcp_gpss4-folder-tools

## 1. 登入(GPSS4 web-app auth)

- [x] 1.1 逆向登入序列與 session key 機制(URL-slot session key,per-load mint)
- [x] 1.2 CAPTCHA 破解:md5 對照表 OCR(CaptchaTable,glyph 靜態字模)
- [x] 1.3 固化 session.py:單 slot 鏈 + md5 OCR + SSO meta-refresh 跟進
- [x] 1.4 認證訊號修正(DD-4):以 SSO 落地頁會員標記判斷,非 TTSUID cookie
- [x] 1.5 實測登入成功(GPSS4Session().login() 第 1 次即 success)
- [~] 1.6 韌性驗證完成（`tests/test_gpss4_captcha_retry.py` 4 pass：unknown glyph→重抓新 slot 不 submit '?'／中途 slot 可解則登入成功／全 unknown 耗盡 retry budget fail-fast／happy path 零額外開銷）。**缺字 Z 標 deferred**：md5_table.json 現涵蓋 `0-9 + A-Y`（35/36），唯一缺 Z；補 Z 字模需真登入抽到含 Z 的 CAPTCHA（隨機 + TIPO 帳號鎖定風險，離線無法產出）。影響極低：單次登入含 Z 機率 ~13.6%，且 login() loop 已自動重抓新 slot 重試（max 6），連 6 次全含 Z 機率微乎其微，缺 Z 幾乎不致登入失敗。

## 2. 資料夾/標記清單端點

- [x] 2.1 釐清資料夾入口:home 頁「標記清單」連結 gpssbkm?.<token>(非 kmworkb/,後者為 watch 輔助輪詢)
- [x] 2.2 確認空清單回應(「無標記資料」)
- [x] 2.3 逆向「加入標記」寫入端點(三步:檢索→clickselect AJAX→加入標記,subagent 實測打通)
- [x] 2.4 逆向非空「標記清單」的資料結構(加入標記 POST 回應即清單,同步 HTML 表格)

## 3. MCP 工具實作

- [x] 3.1 folder.py:GPSS4Folder(search_number/select_hit/add_marks/mark_patent/current_marks + MarkList 解析器)
- [x] 3.2 gpss4_folder_list MCP tool(列出標記清單)
- [x] 3.3 gpss4_folder_search MCP tool(號碼檢索,唯讀)
- [x] 3.4 gpss4_folder_mark MCP tool(加入標記,寫入)
- [x] 3.5 註冊工具進 MCP server(3 tools,總 45)

## 4. 驗證與收尾(專案資料夾路)

- [x] 4.1 end-to-end 驗證(登入→檢索→標記→列清單,實測 TW201729166A count=1)
- [x] 4.2 event log 收尾 + architecture.md sync
- [x] 4.3 清 scratch(XDG),確認無 secret 落檔

**Validation evidence**: 全套 gpss4 測試 **34 pass / 0 fail**（含 login_rotation + captcha_retry 4 新增 + patno + session_keepalive）+ 15 subtests，零回歸；adv_search scraper end-to-end 實測 total=24 / family_count=12 / abstract 24/24 / CSV 落地；folder end-to-end 實測 TW201729166A count=1。**Remaining（deferred）**：1.6 缺字 Z 字模需真登入抽到含 Z 的 CAPTCHA（隨機 + TIPO 帳號鎖定風險，離線無法產出；影響極低，login loop 已自動重試涵蓋）。

## 5. 進階檢索 scraping(SCOPE PIVOT — 主線)

> 專案資料夾 export 缺 family → CLOSED。改驅動登入態進階檢索抓帶 family 的結果列表 → CSV,繞過 GPSS API 每日下載配額。

- [x] 5.1 逆向進階檢索 query 送出契約(`_3_10_X` 檢索式 + INFO 憑證 + image submit `_IMG_檢索`)
- [x] 5.2 確認語法規格(官方欄位代碼表:`(詞)@TI` / `CS=xxx` / `AD=y1:y2`,非 `TI=(x)`)
- [x] 5.3 逆向非同步 job 輪詢鏈(`ttsserv_watch?kmwork/km.swp:<num>:<slot>:全部:` → `<!--DB_OK-->`)
- [x] 5.4 排除假根因(語法/機制/逆時假陽性:display:none 逆時 div 常駐,正向 authmarker 才是真訊號)
- [x] 5.5 playwright + session.py cookie 注入走通完整流程(login→進階檢索 tab slot-key URL→query→result,known-good 24 筆)
- [x] 5.6 【成敗關鍵】family 坐實:家族收合後序號欄 `N.M`(家族 N 成員 M)= per-patent 家族綁定鍵 + 「專利家族數量」計數。修正:`clickselect(...,group)` group 是逐筆選取序號、**非**家族鍵(實證 1..18 無共享)
- [x] 5.7 逆向分頁契約:每頁 50 筆、總筆數 `共 N 筆,第 X/Y`。兩種翻頁:簡目=頁碼 select slot-URL / 家族收合=JPAGE 跳頁表單(`#dispjump`)
- [x] 5.8 實作進階檢索 scraper(`adv_search.py`):login→query→輪詢→家族收合→翻頁→抽 family/摘要→CSV。注冊 `gpss4_advanced_search` MCP tool(總 46)
- [x] 5.9 實測驗證:known-good query 端到端跑通—total=24 / family_count=12 / distinct_families 吻合 / 2頁翻頁 / abstract 24/24 / CSV 落地。scrape rate:單帳號互動态瀏覽，低頻即可
- [x] 5.10 spec 範圍全對齊(proposal/design/tasks ✅)+ architecture.md sync(進階檢索 scraper 段落 + DD-10/11 修正 ✅)+ event log 收尾(producer.ts ✅)+ scratch 清理(XDG recon 清,secret 掃描乾淨 ✅)
- [x] 5.11 家族去重(DD-12):`annotate_family_representatives` 純函式—非破壞性標記代表筆(同家族最早申請日,pat_no 破 tie)+ CSV/tool 回傳加 `is_family_representative`。實測:24筆→5家族代表,代表皆為家族內最早申請日。釐清跨頁 group 全域唯一(無擞號,15 distinct == family_count)

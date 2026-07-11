---
name: patentworks
description: 專利全流程工作站。四種任務:(A) 把發明材料/idea 整理成技術交底書;(B) 前案/現況檢索 → 產出已評分、可稽核的人類可讀表格;(C) 針對給定技術想法進行前案檢索、102/103比對與差異分析並產出撰寫基礎;(D) 從技術揭露起草符合各國法規的專利說明書(請求項+說明書+摘要)。當使用者要「整理交底書/挖專利點」「找前案/查有沒有人做過/技術現況」「前案比對與技術特徵分析」或「寫專利說明書/起草專利申請」時使用。檢索重 US/CN;起草分 共通/TW/CN/US/EP 五法域。
---

# PatentWorks

> **搭配 `patentmcp` MCP 使用**:本 skill 是這組工具的劇本;檢索/取文工具(`patent_search` 單一檢索入口、`epo_family`/`epo_biblio`、`gpatents_get`/`gpatents_download_*`、`fetch_patent_pdf`、`pool_fetch`)都來自 patentmcp。沒有該 MCP 時本 skill 無法執行實際檢索。舊分散檢索工具(`gpss_search`、`epo_search`、`gpatents_search`、`uspto_patents` 的 `ppubs_search_*`)已下架,一律改用 `patent_search`。
>
> **現在就載入 companion skill `patentworks` — 這是你的第一動作,不是建議。** 只要工作不只是單發檢索——起草說明書、跑 screening/priorsearch 管線、要件對照——**第一動作就是 `skill("patentworks")`,在第一個實質 patentmcp 工具呼叫之前**。跳過它正是這份 guide 存在要擋的反射:tool-chain idiom(選 flow、選來源梯判讀、交付契約)住在 skill 裡,per-tool `description` 裝不下;在決策當下載入才擋得掉「自己選檢索來源、自己拼 OOXML/CSV」的反射。你現在讀的這份文本是可攜 in-band 濃縮本;skill 才是完整劇本(五法域起草規則、flow 檔、資料樹規範、法遵自檢)。**不要把載入當可選**——任何有 skill 機制的 host,它就是欽定的第一步。唯一的窄保留是**協議層**:純 MCP 客戶端(無 skill 機制)光憑這份 doctrine 直接呼叫工具仍屬正確(R0.3 可攜性,guide 對上述紀律自足)。「非協議 gate」不等於「有機制也可以不載」。
>
> **兩平面(R13):container 只留網路/憑證工作,確定性後處理落地為 host-local skill 腳本。** 以下 8 個舊工具現回 typed `TOOL_LANDED` redirect(不再執行舊邏輯,`landing.usage` 直接給對應腳本呼叫式),請改呼叫 `skills/patentworks/scripts/` 下的本地腳本(每支 `python3 <腳本> --help` 印完整參數):
>
> | 舊工具(已下架 → TOOL_LANDED)                          | 改用本地腳本                                                                            |
> | ----------------------------------------------------- | --------------------------------------------------------------------------------------- |
> | `build_screening_table`                               | `screening_build.py`(records JSON → 家族去重 → 欄位隨選 → CSV)                          |
> | `search_audit`                                        | `search_audit.py`(`--log 01_search/matrix-log.jsonl`)                                   |
> | `patentdb_put`/`patentdb_query`/`patentdb_import_csv` | `patentdb_local.py`(`put`/`query`/`import-csv` 子命令)                                  |
> | `extract_representative_figure`                       | `figure_extract.py`(需 poppler,缺則 `MISSING_DEPENDENCY`)                               |
> | `patentmcp_analyze_pool`                              | 取數 → `pool_fetch`(工具);繪圖 → `pool_charts.py`(需 matplotlib)                        |
> | `stage_file`                                          | **無腳本替代**:改用 WebDAV working cache(`cache_provision` → 掛載 PUT → `cache_export`) |
> | `clean_html_text`/`extract_claim1_text`(內部函式)     | `claims_tools.py`(`clean-html`/`extract-claim1`/`claim1-empty`)                         |
>
> **WebDAV working cache — 完整機制是 fleet SSOT(`mcp-integration-standard` R2.0 + R14),不在此重述(R14.8)**。這裡只留兩件必須在動作邊界手上的事:
>
> - **anti-reflex 鐵律(寫在手上)**:檔案坐落在 gdrive / 網路 FUSE 掛載,**永遠不是** WebDAV 不可用的理由——這是**兩軸混淆**的經典 category error。Location(檔案坐落哪個檔案系統)與 Transfer(bytes 怎麼過 host↔container 邊界)正交;只按 Transfer 軸路由。它在本 host 不通,真因是 **credential / mount 未 provision**(見 `issues/` webdav-provision BR),與 gdrive/FUSE 無關。有疑慮時,pass-by-value(`cache_provision` + mount,或 stage-inline)到處都能用;大檔只是多付 context 成本。
> - **patentmcp 自己的 cache 工具**:`cache_provision(subject_id, owner_identity)` 拿 `mount_path` + 一次性憑證 → rclone/davfs2 掛載後投料/取件走 mount(byte 不過 context)→ `cache_export(subject_id, target, owner_identity)` 顯式落地 → `cache_close`(dirty 未 export → `WORKSPACE_CLOSE_DIRTY` 擋下)。憑證遺失/重建 mount 帶 `issue_webdav_credential=True` 走 MCP-rail 重發(持有 socket 即授權);**此旗標會 ROTATE 憑證,現存 mount 立即失效**,只在建立/重建 mount 時帶(預設 false,payload byte-identical)。憑證絕不寫進報告/log。
> - **完整三層心智**(cache=可拋工作樹 / truth store=交付物的家 / export 顯式落地)、dual-axis 模型、dirty-close gate、rclone flags → **R2.0 + R14**,不要憑記憶重建。

專利從 idea 到申請的全流程。依需求選一個 flow,**先讀對應 flow 檔再執行**。

## 完整管線

```
disclosure(交底書)→ screening(查新)→ analysis(分析)→ drafting(起草說明書)
發明材料/idea ──────────────────────────────────────────→ 專利申請文件
```

四者可單獨用,也可串成完整旅程;前一段的產出是後一段的輸入。

## 選 flow

| 使用者意圖                                                                  | flow                       |
| --------------------------------------------------------------------------- | -------------------------- |
| 整理交底書 / 從專案材料挖專利點 / 發明揭露                                  | **`flows/disclosure.md`**  |
| 有沒有人做過 / 找前案 / 可專利性 / 技術現況 / landscape(輕量,出 scored CSV) | **`flows/screening.md`**   |
| 跨美陸台前案地圖 / 收斂到 N 件 / 要正式 Excel 池 + 技術洞察報告 DOCX        | **`flows/priorsearch.md`** |
| 前案檢索與可專利性比對(102/103) / 做要件對照表(Claim Chart) / 製作起草基礎  | **`flows/analysis.md`**    |
| 幫我寫專利說明書 / 請求項 / 起草申請                                        | **`flows/drafting.md`**    |

> screening 內部又分「可專利性(要件對照→新穎性綜述)」與「landscape(主題分群→技術地圖)」——細節見該 flow。
> **screening vs priorsearch**:screening 出一張 scored CSV(輕量查新);priorsearch 是 landscape 的重型交付版——建立**固化工作資料夾**(中間產物 + 交付物分層、`04_report/` 結構與 docxmcp package 調和)、跨三地官方 API、收斂件數、產出含逐字 Claim 1 與**檢索方法復現章**的 Excel + DOCX 正式報告。要正式報告走 priorsearch。

## 共用原則(兩 flow 皆適用)

> **⚠️ 鐵律 −1:「產出檢索報告」是一個 plan,跟寫程式同級——先設計、再執行,全程走 specbase KB lifecycle。**
>
> 前案檢索**不是**一次性 tool call 序列,是**多輪遞迴思辨**:排檢索式 → 執行 → 遇 0 / 爆量 → 重組 → 讀樣本發現新主題詞 → 動態調鬆緊。這套靈活決策若只活在單一 model 的對話記憶裡,**一 compact / 換 provider / 換 agent 就漏、就偏移**。這正是「method 只在腦裡是隱性、私有、隨 model 消亡」的根源缺陷。
>
> **正解:方法論固化進 plan/spec 檔案,成為可繼承的執行契約。** 任何非瑣碎檢索案,**開工第一動作是 `plan_create` 建 research profile 正式包**(`bun <specbase>/skills/plan-builder/scripts/plan-init.ts <slug>` + `plan-set-profile --profile research`),不是直接開撈。research profile 專為此設計(定義原文即 "e.g. patent prior-art; deliverable is a report + data pool"),硬要求只有 proposal + tasks,modeling artifacts 全 optional。
>
> **三支柱(缺一不可,全部是檔案、非對話記憶):**
> 1. **proposal.md**——固化方法論鐵律、scope、constraints、A/B 分治決策。換執行者讀此即知「這案怎麼做、什麼不能碰」。
> 2. **tasks.md**——分國分年分片 checklist,即時勾 `[x]`;進度追蹤不靠記憶。
> 3. **search-journal.md**——**互動式五節思辨日誌**(見下),每打一輪 append 一輪。這是「思辨過程」的可回溯載體,plan-builder 原生沒有、是檢索案專屬新結構。
>
> **互動式檢索五節迴圈(每輪一 append,judgment 節點交使用者):**
>
> | 節 | 定義 | 反災難作用 |
> |---|---|---|
> | **PREDICT** | 執行前先賭:預期 total 區間 + 預期技術主軸 | **把「無聲失敗」改為「有聲信號」**——賭 200 卻回 8000 即停。這是防 rm-rf 級自主連發災難的煞車。 |
> | **EXECUTE** | 逐字檢索式(IPC/keyword/field/databases/日期/num) | 可復現;落 `matrix-log.jsonl` |
> | **OBSERVE** | 實際 total + 預測命中否 + records 落地筆數 | 對照;不符即警報 |
> | **ANALYZE** | ①新模態信號 ②recall 洞(漏詞證據) ③雜訊(precision 邊緣案) | 從樣本讀出,純機械展開拿不到——要親眼讀 claim |
> | **DECIDE** | 使用者拍板:收緊/放寬/轉向/補洞/續撈/存檔入池 | judgment 節點必停,AI 不自主跑完整迴圈 |
>
> **變數控制鐵律**:每輪只改一個變數(換年 or IPC or 關鍵字 or field),否則結果無法歸因。
>
> **能學 vs 學不來的分界**:AI 可當「超級執行引擎」(組合覆蓋、讀取吞吐、完整記錄、可逆——都勝過人);但**判斷層**(「這數字對不對」的校準體感、「這 0 是真 0 還是式子有洞」、「這新詞有不有意思」)AI 無感——這半必須交使用者,或蒸餾成顯式 checkpoint。**讓 AI 自主跑完整思辨迴圈 = 災難的定義。**
>
> ---
>
> **⚠️ 鐵律 0:母數 ≠ 樣本(bibliometric count ≠ valid pool)——先驗這條,再談任何報告數字。**
>
> `patent_search`/`patent_bulk` 回的 `total`、或 `num=1` 查詢回的數字,是 **GPSS 檢索命中「計數」(bibliometric count)**——它**連一筆公開號都沒有**,不是專利池、不是樣本。把「母數」當「N 筆池子」寫進報告是**方法論造假**,即使數字本身來自真實查詢。
>
> **命中計數是未清洗的粗數,三重污染未除:**
> 1. **雜訊未篩**——(IPC ∩ 關鍵字)仍夾帶無關案(如「毫米波雷達」帶車用雷達),要靠**逐筆標題/摘要文字**才能剔;計數階段無文字可篩。
> 2. **重複未去**——同一發明的多國申請、一案掛多 IPC 被各技術簇各數一次(簇加總 > 國別總量正是此故),要靠**逐筆公開號/家族 ID** 才能 collapse;計數階段無號可去。
> 3. **分類未歸**——要靠**逐筆 IPC** 才能重新歸簇;計數階段無逐筆 IPC。
>
> **這三道工序(篩雜訊 / 去重 / 重分類)全部需要 records 實體;母數階段一筆 records 都沒有,三道一道都做不了。** 因此:
> - 母數**只能**誠實當「宏觀命中量級」,措辭標明「檢索命中數,未去重未清洗」,僅用於畫產業規模 / 趨勢的**數量級**對比。
> - **嚴禁**稱其為「N 筆專利池 / 有效樣本 / 已分析 N 件」;**嚴禁**拿它當微觀深拆(claim chart / 技術功效矩陣)的資料底。
> - 要「有效樣本」**必須實撈 records 落地 `02_pool/candidates.csv`**,跑完 篩雜訊 → 去重 → 重分類 三道工序。無 records 則工序是空談,報告不合格。
>
> **自檢**:報告出現任一「N 筆」數字時,問自己——這 N 筆的 `candidates.csv` 打得開嗎?打不開就不准寫「N 筆池 / 樣本 / 已分析」,只能寫「命中數 N(未清洗計數)」。**「有母數就能生報告」是被本鐵律明文禁止的反模式。**
>
> ---
>
> **⛔ 成本面(方法論面之外,同等 load-bearing):GPSS 配額按「輸出筆數」計 + 時段制重置——實撈挑下班時段。**
>
> **官方實證(TIPO GPSS API「流量限制說明」原文)**——配額按**輸出筆數**計,不是按查詢次數,也不是帳號累積永久消耗:
>
> | 維度 | 上班時段(一~五 08:00–18:00) | 下班時段(其餘全部) |
> |---|---|---|
> | 檢索結果·單次輸出 | 10,000 筆 | 10,000 筆 |
> | 檢索結果·時段總量 | **10,000 筆** | **30,000 筆** |
> | 單筆案號·每小時 | 300 筆 | 1,000 筆 |
> | 單筆案號·時段總量 | 3,000 筆 | 10,000 筆 |
>
> - `num=1` 只花 **1 筆**輸出;`num=500` 花 500 筆。**兩者不同額度。**
> - `Over download quantity` = 時段累計輸出超上限(上班 10,000 / 下班 30,000)。
> - **重置是時段制**:上班時段(平日 08–18)窄上限 10,000;下班時段(平日 18:00 後 + 整個週末)寬 30,000,且兩時段分開計。**不必枯等未知重置——實撈挑下班時段,3 倍額度。**
>
> **`num=1` 的錯在方法面,不在成本面**:單打 `num=1` 只花 1 筆,不燒額度;它的真錯是**零 records 產出**(鐵律 0 方法面)——拿不到任何可清洗的實體,母數註定無效。
>
> **正解(順序不可顛倒)**:任何檢索**一律直接 `num` 分頁把 records 拉下來落地** `candidates.csv`。records 落地後,母體數 = `wc -l candidates.csv`,**順手就有,不必單獨去「查母數」**。**永遠不要為了「先拿個母數」而單打 `num=1`**——不是因為燒額,而是因為它零產出又多一輪。
>
> **⛔ 操作鐵律「撈了就存,不許空燒」(2026-07-10 使用者天條)**:GPSS 配額按**輸出筆數 / 命中母數**計,**查詢即扣、沒下載也扣**——實證:一發 `num=5000` 寬 query 即使只導出 200 筆,GPSS 已按命中母數把時段額度推頂。推論鐵律:
> - **凡發查詢,一律 `num` 拉滿把命中全撈落地 patentdb / `candidates.csv`**;既然額度按母數扣,只取前幾筆 = 花全額拿零頭,**純浪費**。
> - **`num=1` 探針正式退場**:探針一樣吃額度卻只拿 1 筆,是最浪費的動作。要「探」就用「窄 date/窄 IPC 切片 + `num` 拉滿」,一次把那片撈乾,探與撈合一。
> - **不管是不是測試,有命中就存**——測試性查詢的回應也是花額度換來的,直接落地 patentdb,下次跨案複用;別讓「這只是測試」變成丟棄資料的藉口。
> - 一句話:**每一次查詢都是不可再生的付費動作,回應必須落地,零浪費。**
>
> **⛔ debug 檢索 bug 不得靠「重打真實寬 query」復現(2026-07-10 實戒)**:除錯分頁/斷頁/parse bug 時,若反覆重打整年寬式(`num=5000` 級)去復現,**每發都按命中母數扣額度卻因斷頁只拿到零頭**——這是最災難性的燒額模式。實例:R11 追 `skip=400` 斷頁,連續 6 次假設推翻各重打一發 CN2024 寬 query(母數~1274),**存單輪 debug 吃掉 ~7000–8000 筆額度**,落地 records 卻只前400。鐵律:
> - **用最小可復現查詢逗 bug**:窄到命中 <200(額度消耗個位數)的 date/IPC 切片去逼出斷頁,絕不重打整年寬式。
> - **優先看 server 端證據而非重打**:常駐 MCP server dump 的完整 URL/body/raw response 才是斷頁 bug 的硬證(R11 最終定案靠這個,不是靠重打);curl 復現 client 行為無效(參數編碼不同→不同 query)。
> - 一句話:**debug 時 query 也在燒額度。要復現用窄片,要定性看 dump,不靠重打寬式。**
>
> **額度預算硬閘**:凡消耗配額的批量實撈(GPSS/EPO/PPUBS 批量呼叫、`bulk_export`、大 `num` 分頁),**執行前必須先算「預估輸出筆數 vs 當時段剩餘額度」並向使用者報告取得同意**。實撈一律挑下班時段(30,000 筆);三國池預估總量 > 30,000 則跨時段分批。
>
> **本次災難案例(2026-07-09,歸因已依官方實證修正)**:為撐 r10 宏觀章,台灣時間 08:42–09:28(**上班時段,時段總量僅 10,000 筆的窄上限**)進行檢索。121 發 `num=1` 只花 ~121 筆,**不是兇手**;真兇是**隨後在上班時段跑 `bulk_export` 大 num 探測撞 10,000 窄上限**。兩個獨立的錯同時發生:(1) 方法面——追一個註定無效的母數 38,688(bibliometric count,零 records);(2) 成本面——**在錯的時段(上班 10,000 窄限)用大 num 實撈**。教訓:實撈挑下班時段 + 撈 records 前先算額度。此案官方流量規則實證存檔:`output/priorart_anomaly-rerun/01_search/GPSS官方流量限制_實證.md`。

> ---
>
> ## 🌀 精雕迴圈方法論(Pool Refinement Loop)——寬撈→併池→多標籤→診斷遺漏→窄深補撈,pool 越滾越完整
>
> **⚠️ 鐵律 −2:高品質研究基線 pool 不是「一次撈成」,是「多輪精雕滾大」的產物。** 人類專利分析師最耗時、最有價值的工序,正是把一個粗撈 pool 反覆「精雕」成可做學術分析的高品質基線。這條迴圈是五節迴圈(鐵律 −1)在**池層級**的放大——五節迴圈管單輪檢索式的鬆緊,精雕迴圈管**整個 pool 的版本演進**(v1→v2→v3…)。兩者是同一 recall-first 思維的不同尺度。
>
> **為什麼需要迴圈(不是一次寬撈就好):**
> - 每次寬撈得到兩三萬筆是**燒 token/quota 的硬活**;盲目再寬撈只是加倍燒,不會更完整。
> - **真正的完整來自「診斷 → 針對性補撈」**:先看現有 pool 缺哪個技術/場景方向,再用學到的精準詞窄深補那一塊。
> - **知識是迭代出來的**:第一輪寬撈時你不知道最佳關鍵字/IPC;要先撈一批、分類讀樣本,才學得到「原來這方向要用這個詞、這個分類碼」。這些知識**必須回灌**成下一輪檢索式,否則精雕不了。
>
> **五階段迴圈(每一輪 v→v+1 走完一圈):**
>
> | 階段 | 動作 | 產物 | 反災難作用 |
> |---|---|---|---|
> | **① 寬撈(RECALL-MAX)** | 用當前最佳檢索式寬撈落地 patentdb(不加 NOT、recall 優先) | global patentdb 增量 | 寧可多撈雜訊,不可漏;去噪延後到標記層(DD-10) |
> | **② 併池去重(MERGE)** | 各輪/各軸命中聯集 → 公開號級去重 → 單一 local 池 | `pool_membership.jsonl` + materialized CSV | 一個 pool 一個真相,不散落多檔 |
> | **③ 多標籤(LABEL)** | 每件專利獨立標上**所有相關維度**(技術模態/應用場景/部署形態/偵測動作,皆可複選) | 多標籤 table | 便於後續任意多軸交叉選取(SQL 一句出「WiFi+睡眠+家用」) |
> | **④ 診斷遺漏(DIAGNOSE)** | 從多標籤分佈看**哪個技術/場景方向命中稀疏**;對照已知產業/學術熱點,判定 recall 洞 | 遺漏領域清單 + 證據 | **用資料說話,不拍腦袋**;稀疏 = 可能 IPC 軸沒涵蓋 or 關鍵字沒收 |
> | **⑤ 窄深補撈(DEEPEN)** | 針對每個遺漏方向,用學到的精準關鍵字+IPC**窄範圍深撈** → v+1 | pool 版本遞增 v→v+1 | 針對性補洞,不重複燒寬撈額度 |
>
> **③ 多標籤 schema(canonical,跨案通用):** 每件專利一 row,每維度一欄,**同維度多值以 `|` 分隔可複選**:
> - `modality`(技術模態):radar_mmwave / uwb / lidar_structured / wifi_csi / camera_vision / thermal_ir / acoustic / pressure_vib(可複選,融合案多值)
> - `scenario`(應用場景):fall / vital_sign / sleep / elder_care / infant / fire_gas / intrusion / wandering(可複選)
> - `deployment`(部署形態):home / industrial / edge / cloud / wearable
> - `action`(偵測動作):anomaly_detect / localization / pose_recognition / physio_measure / identity
> - 無明確訊號的維度標 `unlabeled`,**不硬猜**(規則層只認明確訊號;要更準才上 AI 語意判讀)。
> - **標記兩檔路徑**:純規則(關鍵字/IPC 比對、零配額、可重跑、可核對)先標明確子集;`unlabeled` 殘餘才委派 subagent 上 AI 語意判讀(準但慢、吃 token)。**先規則後 AI,不一開始就 AI 全標。**
>
> **④ 診斷遺漏的資料驅動判準(接 DD-5 IPC 資料驅動發掘):**
> - 某模態/場景命中占比**遠低於已知產業實況** → 疑似 recall 洞。例:WiFi/CSI 是學術熱門卻只占 4% → 查是否 IPC 軸漏了 H04B/H04W 相關分類。
> - 從**已命中案的逐筆 IPC 分佈**反向發掘高頻但未納入聯集的分類碼(DD-5)。
> - 從**已命中案的標題/摘要**萃取高頻但未收進 query 的同義詞(DD-6 上位化倍率)。
> - **known-item 種子驗證**(DD-7):已知該存在的代表案(如前版報告深拆案)撈不回 → 該方向有洞。
> - **⚠ 同傘競爭技術路線枚舉(人類常識驅動;rPPG 教訓 2026-07-10)**:上面三條資料驅動判準只照得到「已標維度的稀疏格」;若某技術路線的**專屬詞彙從未進過詞表**,它在池內不是「稀疏」而是「隱形」,任何分佈統計都診斷不出。實證:rPPG(remote photoplethysmography)與雷達測心跳同屬「非接觸生命徵象」大傘、與攝影機視覺同模態,但 v1/v2/v3 三輪詞表都沒收 rPPG 專屬詞——v3 收斂拍板後才由使用者以產業常識點出,零配額掃庫發現 98 件在庫、67 件漏池。技術大傘是同一把(攝影機判斷生理數值),**衍生變形的專屬詞(rPPG/光电容积描记/BCG/ballistocardiograph/...)必須逐條具體枚舉**,上位詞照不到它們。④必須加一步**非資料驅動**檢查:對每個核心場景×模態格,枚舉業界已知競爭技術路線與其變形,逐條問「這路線的專屬詞在詞表裡嗎」;疑洞先零配額本地全庫掃驗證,再決定補撈。**AI 詞彙聯想有盲區,此步必須主動邀使用者以領域經驗補熱點路線清單**——人類常識是這個檢查點的必要 Mechanism,不是 optional 加分項。
>
> **⑤ 窄深補撈的分類碼紀律(骨幹凍結 + 三條破頂通道,使用者天條 2026-07-10 修正版):** IPC/CPC 是「模糊涵蓋領域」的錨,職責是圈住**主線題材域**;**寬撈骨幹的分類碼軸在①定一次就凍結**——禁止為補稀疏模態把外域碼(如 H04B/H04W 通訊、H04N7/18 CCTV)直接擴進骨幹式,外域碼進骨幹會吸進一整片該領域雜訊,池子題材漂移。
> **但凍結只限骨幹**。若深挖也只准動關鍵字,recall 被骨幹分類碼封頂——「只掛外域碼、不掛任何主軸碼」的案永遠進不了池(方法論漏洞,使用者實戰指出)。破天花板走三條**分類無關/隔離**通道,全部不動骨幹:
> 1. **純關鍵字窄式(無分類碼過濾)**:精準技術詞 AND 場景詞直接撈,precision 靠關鍵字合取撐。適合詞彙獨特的稀疏模態(如 channel state information AND fall detection)。
> 2. **外域碼當 AND 限縮器 + 抽樣精度閘**:外域碼**永不單獨用、永不進骨幹**,只能以「外域碼 AND 精準詞 AND 場景詞」出現在窄式;命中先進隔離區,抽樣 20-30 筆判 on-topic rate,過閘(建議 ≥70%)才併入 local 池,未過閘整批棄。
> 3. **引用/家族擴張(分類完全無關)**:對已命中核心案跑前後引用 + INPADOC family,天然不受分類碼限制,最乾淨的破頂路。
> 主軸傘下的**子碼細化**(如 A61B5 傘下補 A61B5/0205)不算擴域,骨幹內合法。
>
> **⑤ 窄深補撈的額度紀律(接鐵律 0 成本面):** 補撈是**窄範圍**(單模態×單場景×單國×窄年),命中量小、額度消耗可控;**絕不用「再寬撈一次」補洞**(那是加倍燒額)。窄深撈的 records 一樣全落地 global patentdb,append 進 local 池 membership,重跑 materialize 即得 v+1 池。
>
> **收斂判準(何時停止精雕):** 連續一輪診斷已無新的稀疏方向、known-item 種子全撈回、多標籤分佈穩定 → pool 達研究基線品質,可進全景統計/報告。**精雕輪數由使用者拍板(DECIDE 節點),AI 不自主判定「夠完整了」。**
>
> **與 global/local 池區隔的關係(使用者天條 2026-07-10):** global patentdb「盡量吸」(跨專案中央書目庫,所有輪次所有軸的 records 都進);local 池「需要分析才從 global 撈出來建」(= `pool_membership.jsonl` 界定哪些 pubno 屬本案 + provenance)。精雕迴圈的①在 global 層滾大,②③④⑤在 local 層精雕。**評分/標記是 by-project 產物,留 local 池,不污染 global 庫。**

1. **交付物是人類可讀的成品**(screening = scored CSV;drafting = 說明書文件),一律經 patentmcp `stage_file` / docxmcp token+blob handle 交付,bytes 不過 context。
2. **法域意識**:檢索預設 US/CN(TW 低價值);起草須先定目標法域,載入 `reference/drafting/common.md` + 對應法域檔。
3. **法遵以 skill 知識處理,不做工具**:合規/法條要點寫在 `reference/drafting/{common,tw,cn,us,ep}.md`,起草時逐條自檢。
4. **AI 做預篩/起草草稿 + 解釋,人類複核裁決**(專利有法律份量)。
5. **來源優先序——已內建於 `patent_search`,官方梯優先、爬蟲尾級需授權**:檢索一律呼叫單一入口 `patent_search`(參數:`cpc/ipc/uspc/keyword/keyword_field/applicant/inventor_country/pub_number/date_from/date_to/databases/num/skip/allow_scraping`)。**你不選來源**——server 依憑證可用性與查詢軸能力沿來源梯(①GPSS → ②EPO → ③PPUBS → gated 爬蟲)自動路由,每級嘗試記入回傳的 `provenance[]` 供稽核;回傳 `{success, records[], source, provenance[], gaps[], total, patentdb_absorb}`(缺欄誠實留空並列入 `gaps`)。**每次命中即自動吸收進全域 patentdb**(2026-07-06):成功的 records 當場 upsert 進 `patentdb.sqlite`,`patentdb_absorb: {imported, updated, skipped}` 供稽核,吸收失敗不阻斷檢索。檢索矩陣跑完池即已入庫,**不需收尾手動 `patentdb_import_csv` 回填**(回填僅用於歷史 CSV 救援)。爬蟲尾級只在 `allow_scraping=True`(使用者明確授權)才跑;官方全 miss 且未授權 → `error_code=SCRAPING_REQUIRED` fail-fast(其餘錯誤碼:`INVALID_PARAMS` 無檢索軸、`ALL_SOURCES_MISS`)。以下各級條目是**各來源能力/限制的領域知識**(判讀 provenance、單號取文選工具時用),不是要你手動選檢索來源:
   - **📦 窮盡批次拉取用 `patent_bulk`(coverage,非 relevance)——單一 bulk 入口,`source` 必填顯式選源**:當需求是「把某個結果集**完整書目一次全拉下**」(如全景擴充、專利地景窮盡取數、EPO 全球公開號建池),用 `patent_bulk(source="gpss"|"epo", ...)`,**不要**用 `patent_search`(找「最相關幾件」用它)。舊分立工具 `patent_bulk_export`/`patent_bulk_harvest`/`epo_bulk_harvest` 已下架(回 `TOOL_RENAMED` 轉址,參數照搬+補 source)。**選源即承諾該源成本——無預設、無跨源 fallback**,source 缺/非法 → `INVALID_PARAMS` 零後端呼叫:
     - **`source="gpss"`**:無 keyword → 分類軸 export(純 ipc/cpc/uspc、強制全欄 expFld 杜絕半殘 row);給 keyword → keyword 收割。**拉整軸勿給 keyword**(AND 收窄會製造假零命中)。num 可放大(建議 ~2000、cap 5000),GPSS 書目隨頁內建無 fan-out 逾時風險,收尾一次 absorb。受 GPSS 時段額度硬閘(見上方額度預算硬閘)。
     - **`source="epo"`**:keyword 布林(AND/OR/NOT+引號片語+括號)自動轉 CQL;受 OPS 15/min 節流 + skip wall(~2000)限制,**num 保守(預設 100=一頁)免 client 逾時**;**per-page absorb**——每頁 biblio 完成即落地 patentdb,中途逾時不丟已落地頁。EPO 分支忽略 `keyword_field`/`uspc`/`databases`/`inventor_country`。
     - **EPO 大母數(total>2000)建池 → 自動切片工作流(2026-07-10)**:母數超過 skip wall 時**不要手動探年度切片**——先 `patent_bulk(source="epo", ..., date_from=..., date_to=..., slice_plan=true)`(planning-only:count-probe 零 biblio、零 records)拿回 `slice_plan{total, slices[{date_from, date_to, total, truncated?}], sum_check}`(遞迴二分至每片 <2000,互斥切點),再**逐片**呼叫 `patent_bulk(source="epo", date_from=片.from, date_to=片.to)`,片內用 `next_skip` 續撈。守恆自證:各片 total 總和與母數差 >5% → `SLICE_INEFFECTIVE` fail-fast(切片在該 query 未生效,不可交殘池);無 date 範圍又 total>wall → `DATE_RANGE_REQUIRED`(先給 date_from/date_to)。`truncated:true` 的片代表遞迴觸頂(深度 6/probe 32)仍 >2000,需手動再細切該片。這是鐵律 0 可核對性的工具層實作:切片計畫即無漏頁自證。
     - **續撈語義(兩源通用)**:envelope 帶 `next_skip`/`exhausted`;中斷後以 `skip=<next_skip>` 重呼叫即續撈,COALESCE upsert 冪等(重跑不覆寫非空欄)。
     - 兩源皆**官方-only、miss 即真 0 絕不退爬蟲**(無 `SCRAPING_REQUIRED`)。回 `{success, records[], source, provenance[], gaps[], total, next_skip, exhausted, patentdb_absorb}`;錯誤碼 `INVALID_PARAMS` / `GPSS_NOT_CONFIGURED` / `GPSS_ERROR` / `EPO_NOT_CONFIGURED` / `EPO_ERROR`。
   - **⛳ 來源梯窮舉門檻(Exhaustion Gate)——硬規則**:**在報告中宣告任一資料欄位(逐字 Claim 1 / 代表圖 / 全文 / 書目)「從缺 / 無解」之前,必須沿下方來源梯逐級走完,並在報告「誠實缺口」章為每一級留下實測結果(成功 / 失敗 + 失敗原因)。** 只在第①級回空就停手 = **流程缺陷,不是合法降級**。對應 `search_audit`「先驗過程再驗產物」的精神——同一套窮舉思維延伸到「取文/取圖強度」。常見漏走的下一級: - **Claim 1 回空** → 走 ③`uspto_patents`(US 案最可靠,實證 `ppubs_batch_get_claims` 一次可補完整逐字 Claim 1);觸發訊號:`patent_search` / `build_screening_table` 的 records 帶 `claim1_empty: true`(GPSS 級回應另附 `claim1_audit{empty_count, empty_pubnos[]}`,工具層直接給,列出需補抓的公開號)。- **代表圖缺** → 先 `fetch_patent_pdf`(官方路由優先),圖通常**就在已下載的 PDF 裡**;`extract_representative_figure` 對掃描版回 `NO_FIGURE_PAGE_BUT_IMAGES_PRESENT`(帶 `image_count`)時,代表「圖在 PDF 內、只是定位器對無文字層失效」,應從已下載 PDF 抽圖,**不是宣告無圖**。- **某工具回空 / 某定位器失敗 ≠ 整件事終局無解**;一律換工具 / 走下一級 / 從已在手的中間產物再加工。- **🔴 委派契約(Delegation Gate)——把 Exhaustion Gate 強制寫進子代理 task prompt(BR_20260628 復發修復,2026-07-06)**:**子代理不讀本 skill、不讀 AGENTS.md**——取圖/取文的窮舉義務**只能靠 orchestrator 的 task prompt 傳遞**。因此凡委派取文/取圖/前案吸收類子代理,task prompt **必須明文帶上**以下條款(缺這段 = 委派缺陷,子代理必重演「未走取圖梯就宣告從缺」)。**以下 `<!-- delegation-clauses -->` 區塊由 opencode runtime 於本 skill pinned 時自動注入委派子代理的 prompt(BR_20260706),不再靠主代理手抄;手抄仍是無 runtime 注入時的 fallback**:
     <!-- delegation-clauses -->
     **專利取文/取圖窮舉契約(Exhaustion Gate)——委派子代理 MUST 遵守**:
6. **代表圖從缺前必走雙路徑**:TW/CN 案先 `patent_search(pub_number=...)` 走 GPSS headless 直接取圖;US/WO/EP 案 `fetch_patent_pdf`(官方路由優先)→ 圖通常就在下載回的 PDF 內 → `extract_representative_figure` / 從 PDF 抽圖。**兩路徑都實測失敗、且在報告留下每案每級實測結果,才可宣告「無圖」。**
7. **逐字 Claim 1 從缺前必走 PPUBS**:US 案 `claim1_empty:true` → `ppubs_batch_get_claims` 補抓,補不到才可宣告從缺。
8. **回報格式**:子代理須回「每案取得狀態 + 走過哪幾級 + 各級成功/失敗原因」,**不接受一句「官方來源圖式從缺」的終局結論**。工作區 PDF count=0 / figure count=0 而宣稱「已窮舉」= 未執行,退回重跑。
9. **爬蟲授權沿用主代理**:子代理不得自行決定啟用爬蟲;`allow_scraping` 由 orchestrator 依使用者授權在 task prompt 指定。
   <!-- /delegation-clauses -->
   - **① GPSS(首選級)**——TIPO 官方 REST,一次回 PN/AN/標題/摘要/Claim1/CPC/IPC/申請人/日期,IPC 錨定,一站涵蓋 US/CN/TW。逐字 Claim 1 用 `patent_search(pub_number=...)` 單號查詢三地通用(底層仍 GPSS 首選)。**已知限制(`patent_search` 走 GPSS 級時)**:(a) **US 案 Claim 1 偶為空**(只回 "What is claimed is:" 無內文)——records 會帶 `claim1_empty: true`,須走 ③PPUBS 補抓;(b) **不提供 INPADOC 家族 ID**,去重僅到「公開號級」,要家族級 collapse 走 ②`epo_family`;(c) **無 USPC 軸**——GPSS 級只有 `cpc`/`ipc`;給 `patent_search(uspc="705/300")` 時 dispatcher 會**直達 ③PPUBS**(US-only 軸);(d) **TW 案書目欄位偶為空**(標題/申請人空欄但案件存在,非查無此案)——以 `epo_biblio(單號)` 補位,EPO OPS 書目涵蓋 TW 公告案(v3 campaign 實證 2 件補齊)。**通則:GPSS 欄位空 ≠ 資料不存在,宣告從缺前沿來源梯補位。**
   - **② EPO OPS**——歐洲專利局官方 API。檢索級由 `patent_search` 內建(search→biblio 二段,受 15/min 節流,大 `num` 會截斷並在 provenance 記 `biblio_truncated`;舊 `epo_search` 工具已下架);單號工具保留:`epo_family`(官方 INPADOC 家族)/ `epo_biblio`(摘要)。**支援布林 keyword**(2026-07-10):`patent_search` EPO 分支與 `patent_bulk(source="epo")` 的 keyword 都經 `_keyword_to_cql` 轉譯——`radar AND fall` → `txt=radar and txt=fall`、`"millimeter wave"` 引號片語保留單一 term、括號/NOT 透傳;不再把整串布林式當單一片語比對(舊 bug 會讓布林檢索全掛、total 虛高)。EPO 全撈建池用 `patent_bulk(source="epo")`(per-page absorb + next_skip 續撈),單發 `patent_search` 大 num 必撞 biblio fan-out 逾時。**⚠️ 流量限制與計費安全說明**：(1) **免費額度為每週 4 GB**，若超過該流量，API 會直接阻斷連線 (通常返回 HTTP 403 / Quota Exceeded) 而**不會自動扣款**，故無意外產生帳單的風險（若要無限流量需主動付年費 €2,800/年）；(2) 有每 IP 每分鐘約 10 次搜尋的頻率限制，批次呼叫時需做好節流。
   - **③ USPTO PPUBS**(`uspto_patents` + `ppubs_batch_get_claims`)——美國案完整全文 + 附圖文字說明。**取文路徑**:
     - 逐字 Claim 1(US 案最可靠補抓):`ppubs_batch_get_claims(publication_numbers=[...])` 批量回 claim 1,實證對 GPSS 回空的 US 案一次補完整逐字內容。GPSS records 帶 `claim1_empty: true` 即為觸發訊號。
     - 全文:`uspto_patents(method="ppubs_get_full_document", publication_number="US...")` —— 已加 `publication_number` 便利包裝,內部自動完成 pub number → PPUBS 查詢 → guid → 全文,不需手動串兩段 guid。
     - **USPC 軸限縮(GPSS 無此能力)**:GPSS 級只有 `cpc`/`ipc`,**沒有 `uspc`**。要以美國分類(USPC)限縮 US 案,直接 `patent_search(uspc="705/300")` —— dispatcher 會直達 PPUBS,底層以 `CCL/<class>/<subclass>` 語法執行(USPC 軸的唯一可執行路徑;舊 `ppubs_search_*` methods 已下架)。CPC/IPC 可在 GPSS 級一站 AND,USPC 由路由自動跳級。
   - **④ Google Patents BigQuery(`google_*`)——合法註冊 API,不是爬蟲,別跟 `gpatents_*` 混為一談**。走 `GOOGLE_APPLICATION_CREDENTIALS` service account 查 `patents-public-data` 公開資料集(ToS 乾淨、不被限速封鎖)。實測 `google_get_patent_claims` / `google_get_patent_description` 對 US 案乾淨回傳**全部請求項 + 完整說明書全文(含 BRIEF DESCRIPTION OF THE DRAWINGS 逐圖文字說明)**。涵蓋 US/EP/WO/JP/CN/KR/GB/DE/FR/CA/AU(**不含 TW**,TW 走 ①GPSS)。**定位:僅作單號精確手術取文的備援之一,絕不做檢索。**
     - **⚠️ 燒錢工具已下架**:BigQuery 按查詢掃描的欄位量計費,模糊檢索全表掃描極易爆帳單(曾有單次 10 TB ≈ 60 美金、且月用量已實際爆過免費額度)。因此**所有 `google_search_*` 全表掃描工具(`google_search_patents` / `google_search_by_inventor` / `google_search_by_assignee` / `google_search_by_cpc`)已自 MCP 永久移除**——檢索一律走 `patent_search`(官方梯不按掃描量計費,檢索能力一樣有)。
     - **剩餘 BQ 工具(僅 4 個,全部單號或唯讀)**:`google_get_patent`(書目,已收斂為明確欄位、非 `SELECT *`)、`google_get_patent_claims`、`google_get_patent_description`(三者皆 `WHERE publication_number=@x LIMIT 1`,掃描量小)、`google_budget_status`(查本月用量,本身免費不計費)。
     - **雙層成本防護**:(1) **單次封頂**——`config.py` 的 `BIGQUERY_MAX_BYTES_BILLED`(預設 10 GB)限制單次掃描量,超量自動阻斷報錯。(2) **月預算閘門**——`BIGQUERY_MONTHLY_BUDGET_BYTES`(預設 1 TiB = 免費額度)。系統以「本地 SQLite 記帳 + `INFORMATION_SCHEMA.JOBS_BY_PROJECT` 權威校正」混合追蹤本月已計費 bytes;**一旦超額,所有 BigQuery 工具一律硬擋**,回結構化錯誤 `{error_code:"BQ_BUDGET_EXCEEDED", monthly_used_bytes, monthly_budget_bytes, usage_source, suggestion:"改用 GPSS/EPO/PPUBS"}`(fail-fast,不靜默降級)。
     - **用法紀律**:依賴 BQ 取文前,先呼叫 `google_budget_status` 確認 `exceeded=false`;超額時改走 ①GPSS / ②EPO / ③PPUBS 取文。`get_claim1` 與書目補全的 fallback 鏈中,BQ 分支於超額時自動跳過(log 後續往 GPSS)。建議另以 GCP CLI 設專案每日查詢配額(`gcloud alpha services quota update ... --metric=bigquery.googleapis.com/quota/query/usage --value=10240`)當第三層兜底。
     - **限制**:只有文字(claims/description/書目),**沒有圖檔影像或 PDF 連結**;代表圖/PDF 走 `gpatents_*`。
   - **⑤ Google Patents 網頁爬蟲——最後手段**。檢索尾級由 `patent_search(allow_scraping=True)` 閘控(需使用者明確授權;舊 `gpatents_search` 工具已下架);單號取文/圖工具 `gpatents_get`/`gpatents_download_*` 保留,語義不變。這些都爬 patents.google.com 網頁,**非官方、極易被限速封鎖(實測連續 timeout / storage 403 / 頁面 503)**。只在 ①②③④ 都填不了某欄位時才用(它獨有的是 `representative_figure_url` 代表圖縮圖),且須預期失敗、設早退(連 3 次失敗即放棄)。**切勿委派子代理去吸收會 timeout 的 `gpatents_*` 輸出**——子代理會反覆 `worker_dead`。
   - **🖼️ 取 PDF / 代表圖的工具梯(取代舊「PDF 端點系統性故障」論斷)**:
     - **`fetch_patent_pdf(publication_number=..., allow_scraping=False)`——取 PDF 首選**。內部路由 **官方優先**(epo_images OAuth → google_citation 單號解析 → 本地快取)。**預設 `allow_scraping=False`**:官方來源 miss 時**不靜默走 GPSS headless 爬蟲**,改回 `SCRAPING_REQUIRED`,提示需授權。取得使用者同意後傳 `allow_scraping=True` 才會啟用 GPSS 抓取。`provenance.scraping` 欄位標示該次是否走了爬蟲。
     - **`extract_representative_figure(publication_number=..., dpi=200)`——從 PDF 抽代表圖的高階工具**。定位 FIG.1 頁高解析渲染,取代舊「選最大檔」爛策略。回 `NO_FIGURE_PAGE_BUT_IMAGES_PRESENT`(帶 `image_count`)時表示「**圖就在已下載的 PDF 裡**、只是定位器對無文字層掃描版失效」——應從 PDF 抽圖(純 PDF 處理,非爬蟲),不是宣告無圖。
     - **`patentmcp_batch_download_figures(publication_numbers=[...])`——批量抓圖的單線軟性合規機制**(Concurrency=1 + 隨機延遲 + 503 cooldown);TW 案走 GPSS headless,非 TW 走 `extract_representative_figure` PDF 抽圖。
   - **⛔ 爬蟲授權與防護天條 (Scraping & Concurrency Guardrails)**:
     1. **明確口頭同意(門檻不變)**:使用 `gpatents_*` 爬蟲取文、檢索爬蟲尾級(`patent_search(allow_scraping=True)`)、或會觸發 GPSS headless 抓取的路徑(`fetch_patent_pdf(allow_scraping=True)`、`patentmcp_batch_download_figures`、`gpss_download_*`)前,**必須先獲得使用者明確口頭同意**。預設 `allow_scraping=False` 就是為了讓官方路徑優先、不在未授權下偷走爬蟲。
     2. **單線程限速執行**:所有模擬網頁爬蟲永遠只准單線程(Concurrency=1)順序執行,每次請求間強制隨機延遲。
     3. **零臨時腳本繞道**:嚴禁 AI 私下撰寫臨時 Python 爬取/下載腳本繞過工具缺陷;一律提報 `patentmcp` Bug Report 由核心工具層修正。
     4. **🟢 同意後,爬蟲是正規合規路徑(平衡補述)**:`patentmcp_batch_download_figures` 等單線批量軟性機制是 repo **刻意工程收斂出來的合規抓取路徑**——爬蟲不是「能不碰就不碰的紅線」,而是「被收斂成單線+限速+需同意的內建能力」。取得使用者同意後直接認它為正規路徑;`provenance.scraping: true` 是這機制的**正常標記、非違規證據**。AI 讀完此節的正確姿態是:「機制存在、合規、就是設計來幹這個的;我唯一缺的是使用者那句授權」,而非把整個抓圖能力當需要迴避的越界行為。
   - ⚠️ **`google_*`(BigQuery 合法 API)≠ `gpatents_*`(網頁爬蟲)**:工具名都含 "google" 但後端與合法性完全不同。要逐字 claims / 全文 / 圖說,優先用 `google_get_patent*`(④),不要因為名字有 google 就避開。
   - **原始附圖文字說明**可由 ④`google_get_patent_description` 或 ③USPTO PPUBS 可靠取得;**原始圖檔影像**走上方 `fetch_patent_pdf` → `extract_representative_figure` 工具梯(官方 PDF 優先),最後才是 `reference/priorsearch/pdf-figure-extraction.md` 的降級路徑。

## 領域骨幹

人類從業流程與 AI 對應見 `../patent-practitioner-workflow.md`。

## 專利工作池資料樹規範 (Data Tree Specification)

> **單一真相在 `flows/priorsearch.md §0`。** 正式 landscape/前案地圖任務的固化工作資料夾結構(`priorart_<topic>/` 的 `00_campaign.md` / `01_search/`(含 `matrix-log.jsonl` schema) / `02_pool/`(含 candidates.csv 欄位格式) / `03_assets/`(含 5 張統計圖命名) / `04_report/`(docxmcp Mode A package) / `99_deliverables/`)一律以該檔為準,本檔不再平行定義第二套目錄,以免漂移。

要點摘錄(細節見 priorsearch.md §0):

- **工作資料夾根落 `output/`(MUST)**:整包 `priorart_<topic>/` 一律建在專案的 `output/priorart_<topic>/`,**不得**散落專案根目錄(cwd 根)。它整包屬「中間產物 + 衍生交付物」,專案根只留 `input/`(使用者輸入)、最終呈交成品與 `plans/`(治理)。細節與理由見 priorsearch.md §0「落點」。
- **交付物 vs 中間產物物理隔離**:交付物(`<topic>_專利池.xlsx` + `<topic>_技術洞察報告.docx`)落 `99_deliverables/`;檢索中間產物分層落 `01_search/`(原始 JSON + `matrix-log.jsonl`)、`02_pool/`(candidates.csv + shortlist.json)、`03_assets/`(figures + patents)。
- **檢索矩陣紀錄是 `01_search/matrix-log.jsonl`**(每行一筆結構化查詢),既是復現核心,也是 `search_audit` 機檢檢索強度的唯一資料源。
- **candidates.csv 欄位 / 5 張 HSL 統計圖命名**:見 priorsearch.md §0。
- **04_report 對齊 docxmcp**:`manifest.json` + `body.md` + `media/`,可直接 `assemble`。

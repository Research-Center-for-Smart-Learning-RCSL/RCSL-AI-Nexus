# 備份與還原 Runbook

`launchd/backup.sh` 每天 03:30 把這個平台備份到一個加密的 restic repository。
這份文件是它的另一半：怎麼裝、怎麼知道它還活著、以及**怎麼真的還原一次**。

security.md §9.4 有一句話值得先讀：**沒有驗證過的備份不是備份**。第 4 節的演練
不是選配，它是整件事唯一的證據。這個 repository 已經記錄過八個「設計好、寫進
文件、標記完成、實際上沒有生效」的控制（PROGRESS.md 2026-07-26），一個從來沒有
還原過的備份會是第九個。

相關文件：`launchd/backup.sh` 檔頭寫了每一項「放進去 / 不放進去」的理由；
[security.md](../architecture/security.md) §9.4 是設計；
[secrets/README.md](../../secrets/README.md) 有 `restic_password` 這一列。

---

## 0. 備份裡有什麼，沒有什麼

| | 內容 | 理由 |
|---|---|---|
| 有 | Postgres 全部 schema 與資料 | 平台的狀態本體 |
| 有 | `documents` volume：上傳的檔案與抽出的文字 | 團隊未發表的研究本體 |
| 有 | `secrets/`（不含 `*.example` 與 `README.md`） | **沒有它就不算還原**，見下 |
| 有 | `manifest.txt`：模型清單、schema head、routing policy | 不用先還原就能讀 |
| 沒有 | `prompt_logs` 的**資料列**（schema 保留） | 保存期上限 30 天，備份會讓那個上限失效；而且三週前的除錯逐字稿對災難還原沒有價值 |
| 沒有 | Qdrant passage index | 可從 `documents` 重建，見第 6 節 |
| 沒有 | redis-data / prometheus-data / grafana-data | session 與指標 |
| 沒有 | 模型權重 | 可重新下載，`manifest.txt` 記了是哪些 |

**`secrets/` 在備份裡，這是這套設計最大的一個決定。** 不放的話還原出來的不是一個
可以用的平台：`totp_encryption_key` 是每一組已存 TOTP secret 的加密金鑰，
`api_key_pepper` 是每一支 API key hash 的 pepper。少了這兩個檔，還原出來的資料庫
裡每一個管理員都登不進去、每一支 key 都驗不過。代價是：**restic repository 的
密碼加上讀取權限，就等於整個平台**。所以下一節第 4 步不是形式。

**保存期 daily 7 / weekly 4 / monthly 3，實測跨度 49 天**（2026-08-18，對 130 個
合成的每日快照跑政策，留下 11 個）。monthly 數的是日曆月而不是 30 天視窗，所以
跨度會隨著月份中的位置在大約 32 到 92 天之間擺盪。真正必須成立的是上界低於
`refusals` 自己的 180 天上限——那正是那張表可以放進備份的理由（§9.4 兩個選項裡
的第二個）——92 < 180，成立。

> 同一次量測發現的另一件事：restic 0.19 會用 `oldest daily snapshot` 這個理由
> 把每一組最舊的快照釘住，所以同一天跑兩次備份，兩個都會留下來。它只在政策
> already 保留的範圍內釘，130 個快照那次證明了更舊的確實會被刪掉，所以代價是
> 多一個快照，不是一個永遠不結束的保留期。

---

## 1. 一次性安裝（只做一次）

- [ ] 裝 restic

  ```sh
  brew install restic
  restic version
  ```

- [ ] 準備備份磁碟。

  > ⚠️ **這台機器目前沒有外接磁碟，所以 repository 暫時放在內接碟的
  > `/Users/Shared/nexus-backup/restic`**（2026-08-18，`diskutil list external`
  > 是空的）。**它跟資料在同一顆碟上，所以它不是對磁碟損壞的防護。**
  > 它防得住的是誤刪、壞掉的 migration、手滑 `docker volume rm`、刪錯 collection，
  > 那些是真的會發生而且真的救得回來的事。之所以先這樣做，是因為另一個選項是
  > 讓整套機制在磁碟到貨前都不曾被驗證過，而「設計好但沒有生效」是這個專案已經
  > 記錄過八次的失敗。
  >
  > **外接碟到貨後要做的事**：掛在 `/Volumes/nexus-backup`，把 `backup.sh` 裡的
  > `RESTIC_REPO` 與 `RESTIC_REPO_MOUNT` 兩個常數改回去，在新位置 `restic init`
  > 一次，然後把舊 repository 整個目錄複製過去（或直接讓它從頭開始）。

  外接 SSD 或 USB 磁碟皆可，格式化成 APFS 或 exFAT 都行，掛載點必須正好是
  `/Volumes/nexus-backup`。

  > **為什麼腳本要另外檢查掛載點。** macOS 上一顆沒有插的外接碟，它的掛載點就是
  > 一個普通的空目錄。少了這個檢查，每天晚上會在開機碟上安靜地長出第二個完整的
  > repository，而真正的那個躺在沒人插的磁碟裡不動，**而且每一次都回報成功**。
  > 在目前這個內接碟的暫時設定下，`RESTIC_REPO_MOUNT` 是 `/`，這個檢查會誠實地
  > 通過但咬不到東西——刻意留著而不是刪掉，因為外接碟一接回來它就自己恢復作用。

- [ ] 產生 repository 密碼，並且**立刻**存一份到這台機器以外的地方

  ```sh
  openssl rand -base64 32 | tr -d '\n' > secrets/restic_password
  chmod 600 secrets/restic_password
  cat secrets/restic_password        # 抄進密碼管理器，或印出來
  ```

- [ ] **把那份副本放到機器外面。** 密碼管理器、紙本、另一台機器都行。
  這一步沒有任何程式可以幫你確認做過了沒有，而它是整份文件裡唯一
  「做錯了不會有任何徵兆、直到你需要它的那一天」的一步。
  repository 裡面存了 `secrets/`，所以只把密碼放在被備份的那顆碟上，等於沒放。
  **密碼弄丟，所有既存快照永久無法讀取，沒有救援路徑，這是設計如此。**

- [ ] 手動初始化 repository（腳本刻意不會自己 init）

  ```sh
  mkdir -p /Users/Shared/nexus-backup && chmod 700 /Users/Shared/nexus-backup
  restic -r /Users/Shared/nexus-backup/restic \
         --password-file secrets/restic_password init
  ```

  > **為什麼不讓腳本自動 init。** `RESTIC_REPO` 打錯一個字、或磁碟掛在稍微不同
  > 的路徑，自動 init 會開一個全新的空 repository，之後每一次備份都對著它成功，
  > 而真正的歷史在別的地方。這就是這個 repository 反覆遇到的「只會回答一種答案
  > 的檢查」。初始化是人做一次的事。

- [ ] 先跑一次 dry run，確認每一項前置檢查都過。它會做完所有檢查、印出
  manifest，然後在寫入第一個位元組之前停下來，也不會寫 state：

  ```sh
  NEXUS_BACKUP_DRY_RUN=1 bash launchd/backup.sh
  ```

- [ ] 再手動跑一次真的備份，確認整條路走得通

  ```sh
  bash launchd/backup.sh
  cat /opt/homebrew/var/nexus-backup.state
  ```

  state 檔應該是三行：成功時間、`ok`、以及快照數與位元組數。

- [ ] 安裝 launchd job

  ```sh
  sudo cp launchd/online.rcsl.backup.plist /Library/LaunchDaemons/
  sudo chown root:wheel /Library/LaunchDaemons/online.rcsl.backup.plist
  sudo chmod 644 /Library/LaunchDaemons/online.rcsl.backup.plist
  sudo launchctl bootstrap system /Library/LaunchDaemons/online.rcsl.backup.plist
  sudo launchctl print system/online.rcsl.backup | head -20
  ```

- [ ] 確認健康檢查看得到它。check 15 讀的就是上面那個 state 檔：

  ```sh
  NEXUS_HEALTH_DRY_RUN=1 bash launchd/check-platform-health.sh | grep -i backup
  ```

---

## 2. 平常怎麼知道它還活著

**不用去看它。** `check-platform-health.sh` 的 check 15 會讀 state 檔，每日摘要
的 Figures 區塊固定會印一行「last successful backup N hours ago」。

| 狀態 | 分級 | 你會看到 |
|---|---|---|
| 從來沒有跑完過一次 | tier 1，立刻寄信 | `backup-never-run` |
| 跑過但從來沒成功過 | tier 1，立刻寄信 | `backup-no-success` |
| 最後一次成功超過 72 小時 | tier 1，立刻寄信 | `backup-stale` |
| 最後一次成功 30–72 小時前 | tier 2，隔天摘要 | 一行 warning |
| 上一次跑失敗，但前一次成功還很新 | tier 2，隔天摘要 | 指出失敗在哪個 stage |
| 一切正常 | 摘要的 Figures | 小時數與快照數 |

> **為什麼「超過三天」是 tier 1 而不是 warning。**
> `check-platform-health.sh` 檔頭的原則是：有前置時間的東西進摘要，因為一個
> 連續兩週寫著 FAILING 的主旨列等於沒有主旨。備份不屬於那一類——沒有東西會
> 自己把它修好，而且它的代價不是逐步累積的，是在需要它的那一天一次付清。
> 一個晚上失敗是真的在「劣化」，所以留在摘要裡。

想自己看的話：

```sh
restic -r /Users/Shared/nexus-backup/restic --password-file secrets/restic_password snapshots
tail -40 /opt/homebrew/var/log/nexus-backup.log
```

---

## 3. 一個備份不會告訴你的事

`backup.sh` 每次跑完會執行 `restic check`，但那是**結構檢查**：它確認每個快照的
metadata 解得開、index 裡沒有缺少的 pack。**它不會把資料讀回來**，所以它偵測不到
一個安靜損壞的 pack。

把資料真的讀回來就是下一節。這件事是人拿著 runbook 做的，不是每晚的排程做的，
理由是它要花時間也要花磁碟；而說清楚這兩者的差別很重要，因為
「check 過了」正是日後有人會記成「備份驗證過了」的那一句話。

---

## 4. 演練還原（每季做一次，不碰正式環境）

**這一節是整份文件的重點。** 全程在臨時容器裡做，正式的 Postgres 與 volume 完全
不會被碰到。

- [ ] 取出資料庫快照。`--stdin` 建立的快照，檔案就放在根目錄下：

  ```sh
  export RESTIC_REPOSITORY=/Users/Shared/nexus-backup/restic
  export RESTIC_PASSWORD_FILE=/Users/rcslmac1/dev/RCSL-AI-Nexus/secrets/restic_password

  restic snapshots --tag database          # 挑一個，或用 latest
  restic dump --tag database latest /nexus.sql > /tmp/rehearsal.sql
  wc -l /tmp/rehearsal.sql
  ```

- [ ] 開一個丟棄式 Postgres。`--tmpfs` 的理由跟 README.md 講整合測試時一樣：
  `postgres` image 把資料目錄宣告成 `VOLUME`，沒有它每跑一次就漏一個匿名 volume，
  而 `--rm` 不保證回收。

  ```sh
  docker run --rm -d --name nexus-restore-test -p 127.0.0.1:15433:5432 \
    --tmpfs /var/lib/postgresql/data:uid=70,gid=70 \
    -e POSTGRES_USER=nexus -e POSTGRES_PASSWORD=devpw -e POSTGRES_DB=nexus \
    postgres:17-alpine
  sleep 5
  ```

- [ ] 灌進去。`ON_ERROR_STOP=1` 是必要的，否則 psql 會一路跳過錯誤跑完，
  然後你得到一個看起來成功的部分還原：

  ```sh
  docker exec -i nexus-restore-test psql -U nexus -d nexus -v ON_ERROR_STOP=1 \
    < /tmp/rehearsal.sql
  echo "exit=$?"
  ```

- [ ] 問它幾個問題。這幾行才是「還原成功」的定義：

  ```sh
  docker exec -i nexus-restore-test psql -U nexus -d nexus -tAc "
  select 'alembic head = '||version_num from alembic_version
  union all select 'users        = '||count(*)::text from users
  union all select 'api_keys     = '||count(*)::text from api_keys
  union all select 'models       = '||count(*)::text from models
  union all select 'documents    = '||count(*)::text from knowledge_documents
  union all select 'usage        = '||count(*)::text from usage_records
  union all select 'audit        = '||count(*)::text from audit_log
  union all select 'refusals     = '||count(*)::text from refusals
  union all select 'prompt_logs  = '||count(*)::text||' (應為 0，且這張表必須存在)' from prompt_logs
  "
  ```

  **`prompt_logs` 那一行要 0，而且不能報錯。** 報錯代表 schema 沒被保留，
  還原出來的平台會在第一個請求就掛掉。這是刻意用 `--exclude-table-data`
  而不是 `--exclude-table` 的原因，也是唯一能證明它有效的地方。

  `alembic head` 要對得上 `manifest.txt` 裡那一行。對不上的話，這份 dump 是在
  另一個 schema 版本下取的，直接拿去用是這整件事唯一會安靜失敗的方式。

- [ ] 取出並展開 documents，抽驗幾個檔案

  ```sh
  restic dump --tag documents latest /documents.tar > /tmp/rehearsal-docs.tar
  mkdir -p /tmp/rehearsal-docs && tar -xf /tmp/rehearsal-docs.tar -C /tmp/rehearsal-docs
  find /tmp/rehearsal-docs -name original.bin | head -5
  du -sh /tmp/rehearsal-docs
  ```

  版面是 `<tenant_id>/<document_id>/original.bin` 與 `extracted.txt`
  （`adapters/storage/filesystem_documents.py`）。

- [ ] 確認 secrets 也回得來，而且內容是對的：

  ```sh
  restic dump --tag secrets latest /Users/rcslmac1/dev/RCSL-AI-Nexus/secrets/api_key_pepper \
    | diff - secrets/api_key_pepper && echo "pepper 相同"
  ```

- [ ] 收工

  ```sh
  docker rm -fv nexus-restore-test
  rm -rf /tmp/rehearsal.sql /tmp/rehearsal-docs.tar /tmp/rehearsal-docs
  ```

- [ ] **把結果寫進 [PROGRESS.md](../PROGRESS.md)**，包含日期、用的是哪個快照、
  以及上面每個計數。一次沒有留下記錄的演練，六個月後和沒做過沒有分別。

---

## 5. 真的災難還原（到一台新機器）

順序有一個地方會錯，先讀完再動手。

- [ ] 先照 [first-deploy.md](./first-deploy.md) 把新機器做到第 6 節結束
      （Docker、Tailscale、GeoLite2、取得專案），**但不要 `docker compose up`。**

- [ ] 取回 `secrets/` 與 manifest：

  ```sh
  export RESTIC_REPOSITORY=<備份 repository 的位置>
  export RESTIC_PASSWORD_FILE=<你手上那份密碼>
  restic dump --tag manifest latest /manifest.txt     # 先讀它，決定要拉哪些模型
  restic restore --tag secrets latest --target /tmp/restored
  cp -R /tmp/restored/Users/rcslmac1/dev/RCSL-AI-Nexus/secrets/. secrets/
  chmod 600 secrets/*
  ```

- [ ] 照 `manifest.txt` 把模型重新拉回來（`ollama pull <ref>`），
      這一步可以跟下面並行。

- [ ] **只**啟動 Postgres，讓它建立一個空的 `nexus` 資料庫：

  ```sh
  docker compose up -d postgres
  ```

- [ ] 灌 dump。**這一步必須在 `migrate` 之前。**

  ```sh
  restic dump --tag database latest /nexus.sql \
    | docker compose exec -T postgres psql -U nexus -d nexus -v ON_ERROR_STOP=1
  ```

  > **為什麼順序不能反。** `migrate` 會跑 alembic 建立整個 schema；先跑它，
  > dump 裡的 `CREATE TABLE` 就會撞上已存在的表而整份失敗。反過來先灌 dump，
  > `alembic_version` 已經在 head，`migrate` 進去只會確認沒有要套用的 migration，
  > 然後做它另一半的工作——把 `nexus_gateway` 與 `nexus_admin` 兩個帳號
  > 與 grant 建起來，那兩個帳號**不在** dump 裡（dump 用了 `--no-owner
  > --no-privileges`），是 `infrastructure/db_roles.py` 從兩個 URL 檔生出來的。

- [ ] 跑 `migrate`，它會補上兩個最小權限帳號：

  ```sh
  docker compose up migrate
  docker compose ps            # migrate 要 Exited (0)
  ```

- [ ] 把 documents 灌回 volume。先讓 admin entrance 起來（它掛著那個 volume），
      再用 `docker cp` 反方向送進去：

  ```sh
  docker compose up -d admin-tailnet
  restic dump --tag documents latest /documents.tar > /tmp/documents.tar
  docker cp /tmp/documents.tar "$(docker compose ps -q admin-tailnet):/tmp/documents.tar"
  docker compose exec -T admin-tailnet \
    sh -c 'cd /var/lib/nexus/documents && tar -xf /tmp/documents.tar && rm /tmp/documents.tar'
  ```

- [ ] 整組起來：`docker compose up -d`

- [ ] **做第 6 節的對帳，再做第 7 節的重建索引。** 在那兩步做完之前，
      這個平台的知識庫會回答不出東西，而且不會說為什麼。

---

## 6. 還原後的對帳（不能跳過）

資料庫的 dump 與 documents 的 tar 是兩個時間點取的，**沒有任何順序能讓它們一致**。
`backup.sh` 檔頭有完整的論證，結論是：先 dump 資料庫、後取檔案，讓常見的那種
不一致（備份期間新上傳的檔案）落在無害的一邊——多出一個沒有資料列的孤兒檔案。
剩下那種罕見的（備份期間被刪除的文件）會留下一列指向不存在的檔案，而那正是
會在六個月後變成「某份文件打開就 500」的東西。

所以不要假設它一致，去問：

```sh
docker compose exec -T postgres psql -U nexus -d nexus -tAc \
  "select tenant_id||'/'||id from knowledge_documents order by 1" | sort > /tmp/rows.txt

docker compose exec -T admin-tailnet \
  sh -c 'cd /var/lib/nexus/documents && ls -d */*/ 2>/dev/null' \
  | sed 's#/$##' | sort > /tmp/files.txt

echo "--- 有資料列但檔案不在（要處理）---"
comm -23 /tmp/rows.txt /tmp/files.txt

echo "--- 有檔案但沒有資料列（孤兒，無害）---"
comm -13 /tmp/rows.txt /tmp/files.txt
```

第一份清單如果不是空的：那幾份文件在備份視窗中間被刪掉了。正確的處理是把那幾列
刪掉（從管理介面刪除該文件），而不是想辦法把檔案變出來。第二份清單是磁碟空間，
不是問題。

兩份都空的話，把「對帳過，兩邊都空」寫進還原記錄——「檢查過而且沒事」跟
「根本沒檢查」是兩種不同的狀態，而這是唯一能分辨的地方。

---

## 7. 重建 Qdrant 索引

備份裡沒有 passage index，因為它是衍生的。重建靠的是 per-document 的 reindex
端點，而 `adapters/vector/qdrant_store.py` 的 point id 是推導出來而不是生成的，
所以重跑是冪等的——中途斷掉就再跑一次。

**先確認 `embedding` capability 有 routing policy。** 沒有的話 indexing 會用一個
具名錯誤失敗，而檢索會安靜地回傳空的（PROGRESS.md「Where things stand」有記）。

從管理介面登入拿到 session cookie 之後：

```sh
BASE=https://<tailnet admin entrance>
COOKIE=<你的 session cookie>

docker compose exec -T postgres psql -U nexus -d nexus -tAc \
  "select id from knowledge_documents where status = 'ready'" \
| while read -r doc; do
    curl -sS -X POST "$BASE/admin/knowledge/documents/$doc/reindex" \
      -H "Cookie: $COOKIE" -o /dev/null -w "$doc %{http_code}\n"
    sleep 1
  done
```

`202` 是接受了。跑完之後在知識庫畫面上實際搜尋一次，確認真的搜得到東西——
`chunk_count` 是資料庫欄位，它從 dump 回來就有值，**所以它不能拿來證明索引存在**。

> 代價說在前面：這一步是把每一份文件重新 embedding 一次。文件多的話這會佔用
> GPU 一段時間，而且會跟正在服務的推論搶。挑離峰時間做。

---

## 8. 這套東西目前的缺口

寫在這裡，因為一份不講自己缺什麼的備份文件，會被讀成保證。

- **repository 跟資料在同一顆磁碟上**（第 1 節有完整說明）。這是暫時的，而且是
  這份清單裡最重要的一項：現在的設定救得了誤刪，救不了磁碟壞掉。
- **只有一份 repository，不是 3-2-1。** §9.4 要的第二腿是異地，而它卡在一個
  這一端無法回答的問題：機構政策與合作協議允不允許未發表的研究資料放在第三方
  雲端儲存。在有人回答之前寫上去，就會變成第九個「標記完成但沒有生效」的控制。
  補上第二腿是加一個 repository 與一次 `restic` 呼叫，不是重寫。
- **`restic check` 不讀資料。** 見第 3 節。只有第 4 節的演練會把位元組讀回來。
- **演練還沒有排定週期的強制機制。** 目前靠這份文件說「每季一次」，沒有任何東西
  會在你沒做的時候提醒你。這跟外部 dead man's switch 是同一類問題。
- **備份磁碟本身沒有被監控。** check 15 看的是「上一次成功是多久以前」，
  磁碟寫滿會表現成備份開始失敗，也就是說它會被抓到，但是是事後而不是事前。

# 計畫性停機與復機 Runbook

把整個平台**刻意**停下來，然後完整地帶回來。

這份文件跟 [`boot-recovery-acceptance.md`](./boot-recovery-acceptance.md) 處理的是
相反的兩件事。那一份問的是「機器自己重開之後，平台會不會自己回來」——它測的是
**非計畫**的中斷。這一份問的是「我現在要它下線，等一下要它原樣回來」，中斷是
計畫好的，而計畫性停機有一個非計畫中斷沒有的風險：**你關掉的東西，跟你以為你
關掉的東西，可能不是同一組**。第 2 節就是這個風險的紀錄。

首次實際執行：2026-09-08（PROGRESS.md 2026-09-08）。第 2 節的兩個發現來自那一次；
它們的**根因**是隔天 2026-09-09 第一次真的走完復機程序時才問出來的，第 2 節已經改寫。

相關文件：[`restore.md`](./restore.md) 是**資料**的還原，跟這份無關——這份不動任何
volume；[`first-deploy.md`](./first-deploy.md) 是從零開始安裝，這份假設一切都已裝好。

---

## 0. 平台有幾層，停機要停到哪一層

平台不是一個東西，是三層。停到哪一層決定了復機要做多少事，也決定了停機期間
這台機器還剩下什麼。

| 層 | 內容 | 停掉之後 |
|---|---|---|
| A. 服務 | `docker-compose.yml` 的 11 個服務 | 對外全斷，Docker VM 和模型還在，復機一道指令 |
| B. 主機層背景工作 | colima、ollama、socat-forwards、host-metrics、backup、reconciler | 機器真正閒置，復機要逐一 bootstrap |
| C. 主機本身 | macOS | 見第 6 節，跟前兩層是不同的問題 |

**A 和 B 之間的差別不只是「多關幾個」。** Colima 是 Docker VM 本體，關掉它，
`docker` 這個指令就不再有對象；Ollama 停掉，模型權重會從記憶體卸載，下一次推論
要重新載入。只想省電或讓機器安靜，A 就夠了；要動硬體、搬機器、或讓 Mac Studio
真的空出資源，才需要 B。

**只做 A 的時候，`docker compose stop` 而不是 `down`。** 兩者都不動具名 volume
（`postgres-data`、`documents`、`qdrant-data`、`redis-data`、`prometheus-data`、
`grafana-data`），資料都安全，差別在容器本身：`stop` 保留容器，復機是 `start`
級的；`down` 移除容器與網路，復機要重建。要改設定或升版才用 `down`。

---

## 1. 停機前要先決定的一件事：告警信

`check-platform-health.sh` 每 300 秒跑一次，**狀態一變就寄信**，收件人寫死在
腳本裡（`ALERT_TO`，目前兩位）。平台下線是它設計來偵測的事，所以停機一定會觸發。

**它不會每 5 分鐘寄一次，這一點值得先講清楚，因為它會影響你的決定。** 寄信的
條件是簽章*改變*，不是簽章為失敗，所以停機大約會產生兩封而不是一串：一封在服務
停掉時，一封在 Colima 停掉時（簽章多出 `docker` 這一項，構成第二次變化）。
之後簽章穩定，就不再有故障信了。

真正會持續的是另一個：**每天 `DIGEST_HOUR` 之後的每日摘要照常寄**，內容會是
平台失效中。所以停機跨過早上，就會有一封摘要出去。停機一小時和停機過夜，噪音
量差很多，決定要不要靜音時看的是這件事。

**這個健康檢查沒有維護模式。** 沒有靜音開關、沒有 snooze 檔、沒有維護視窗——
2026-09-08 找過，確認不存在。所以只有兩個選項，沒有第三個：

- **接受它寄信。** 停機期間兩位收件人會收到故障告警。好處是這封信同時是「停機
  確實生效」的獨立證據。
- **停機前先 bootout 它**，復機後再 bootstrap 回來：

  ```sh
  sudo launchctl bootout system/online.rcsl.health-check
  ```

  代價是這段期間平台**真的**出事你也不會知道。如果停機是計畫好、時間可控的，
  這個代價可以接受；如果會停過夜，讓它寄信比較安全。

先決定，再往下做。這一步之後才動任何服務。

---

## 2. 兩個 `launchctl bootout` 停不掉的 daemon，以及它們為什麼停不掉

**這是這份文件最重要的一節。** 直覺的做法是「主機層那些 daemon 都是 launchd 管的，
`launchctl bootout` 一輪就停乾淨了」。2026-09-08 實測，這個直覺對六個裡的四個成立，
對另外兩個不成立，而且**失敗是無聲的**——`bootout` 回傳 0，什麼都不印，程序還活著。

| Daemon | `bootout` 之後 | 真正停掉的方式 |
|---|---|---|
| `colima` | `limactl hostagent` 與 `usernet` 續活，`docker info` 照常有回應 | `colima stop` |
| `socat-forwards` | supervisor shell 續活（它自己還有 `trap` 和重啟迴圈） | `kill` 該 shell，讓它的 `trap cleanup` 收掉三個 socat |
| `ollama` | 確實停止 | — |
| `host-metrics` | 確實停止 | — |
| `backup` | 確實停止（本來就沒在跑） | — |
| `reconcile-port-bindings` | 確實停止（本來就沒在跑，`KeepAlive=false`） | — |

### 為什麼是這兩個（2026-09-09 修正）

2026-09-08 當下記下的原因是「這兩個 job 的工作程序已經 reparent 到 PID 1，`bootout`
收掉的是 job 登記而不是那些已脫離的程序」。這描述了機制，但沒有回答「為什麼偏偏是
這兩個」。隔天復機時同樣這兩個 job 起不來，才問出真正的原因，而它比原本的說法更根本：

**launchd 從來沒有 spawn 過這兩個 job，所以那些程序一開始就不是它的子程序。**

`launchd` 是以 job 的 `UserName` 身分去開 `StandardOutPath`，不是以 root。這兩個
plist 把日誌寫在 `/var/log`（`root:wheel drwxr-xr-x`）而 `UserName` 是 `rcslmac1`，
建檔會拿到 `EACCES`，spawn 在程式執行之前就失敗了。六個 daemon 裡只有這兩個是這個
組合——其餘都寫在 `/opt/homebrew/var/log`，那裡 `rcslmac1` 寫得進去——而它們正好就是
`bootout` 停不掉的那兩個。兩個缺陷同時在 `106c412`（Replace Docker Desktop with
Colima）進來。

**這個失敗從外面完全看不見**，這是它能潛伏數週的原因：`bootstrap` 依然回傳 0，因為
「把 job 載入 domain」確實成功了，失敗的只是 spawn。job 就停在：

```
active count = 0
state = spawn scheduled
```

那麼當時在跑的 VM 和三個 socat 是誰起的？是某次手動 `colima start` 和手動跑那支腳本
留下來的，脫離終端機之後 reparent 到 PID 1，一直活著。`bootout` 停不掉它們，不是因為
它們從 launchd 手上跑掉了，而是因為它們從來就不在 launchd 手上。

**已修**（2026-09-09）：兩個 plist 的 `StandardOutPath`／`StandardErrorPath` 都移到
`/opt/homebrew/var/log/`，與其餘 daemon 一致。

### 修好第一個之後，第二個才現形：colima 找不到 `limactl`

路徑修好、job 終於 spawn 起來的第一件事，是每 10 秒吐一行這個：

```
lima compatibility error: error checking Lima version:
exec: "limactl": executable file not found in $PATH
```

**launchd 給 job 的是最小 PATH**（`/usr/bin:/bin:/usr/sbin:/sbin`），而 `colima` 只是
一個 wrapper，真正做事的 `limactl` 在 `/opt/homebrew/bin`。`KeepAlive=true` 於是把它
變成一個十秒一次的無限失敗迴圈。已在 plist 加上：

```xml
<key>EnvironmentVariables</key>
<dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
</dict>
```

`socat-forwards` 不需要這一項：那支腳本對 `socat` 和 `ifconfig` 都用絕對路徑，其餘用到
的 `awk`／`date`／`sleep` 都在最小 PATH 裡。

**這兩個缺陷互相遮蔽，這是整件事最值得記住的地方。** 日誌路徑不可寫，spawn 在程式執行
前就失敗，所以永遠看不到 PATH 的錯誤；而在終端機手動 `colima start` 一定會成功，因為
操作者的 shell 有 Homebrew 在 PATH 上。**兩個缺陷都只在 launchd 底下發作，而且要修好
第一個，第二個才看得見。** 修好之後 `bootout`／`bootstrap` 對六個都成立，2026-09-09
復機時驗證過：`launchctl print` 的 `active count = 1`，日誌最後一行是
`keeping Colima in the foreground`。

### 這一節留下來的通則

修掉根因不代表這一節可以刪。**每次停機都要回頭看程序，不要看 `bootout` 的回傳值**——
`bootstrap`／`bootout` 的結束碼講的是 domain 登記，不是程序生死，這一點跟這個 bug 修
不修無關。

診斷一個「回傳 0 但什麼都沒發生」的 job，看這兩個欄位：

```sh
sudo launchctl print system/online.rcsl.<label> | grep -E 'active count|state ='
```

`active count = 0` 配上 `state = spawn scheduled`，就是 launchd 想 spawn 而 spawn 不
起來——第一個要查的是 `StandardOutPath` 的目錄，該 job 的 `UserName` 有沒有權限建檔。

順帶一提，`sudo -n launchctl print system/<label>` 在這台需要密碼，非互動的檢查
拿不到 job 狀態——所以在沒有密碼的情境下，「還在不在」這個問題，程序面仍是唯一可靠的
答案。

---

## 3. 停機程序

順序是刻意的：由上而下，先停用它的，再停被它用的。反過來做，會在 Docker 還在
服務時抽掉 VM。

- [ ] **決定告警信怎麼處理**（第 1 節）。要靜音的話現在就 bootout `health-check`。

- [ ] **停 A 層：11 個服務**

  ```sh
  cd ~/dev/RCSL-AI-Nexus
  docker compose stop
  docker compose ps --services --status running    # 必須是空的
  ```

  最後那行是驗證，不是裝飾。半停的堆疊比全開或全關都糟：Docker 會把還在跑的那些
  留著，reconciler 之後會遇到一個既不空也不完整的集合。**空輸出才算過。**

  只到這裡就停手的話，A 層完成，跳到第 5 節看它會不會自己回來。

- [ ] **停 B 層：主機層背景工作**（需要 root；plist 在 `/Library/LaunchDaemons`，
      屬 system domain）

  ```sh
  sudo launchctl bootout system/online.rcsl.reconcile-port-bindings
  sudo launchctl bootout system/online.rcsl.backup
  sudo launchctl bootout system/online.rcsl.host-metrics
  sudo launchctl bootout system/online.rcsl.socat-forwards
  sudo launchctl bootout system/online.rcsl.ollama
  sudo launchctl bootout system/online.rcsl.colima
  ```

  `colima` 放最後：它是 Docker VM，先關它其餘的就無從收尾。

  > `refresh-geolite2` 不在名單裡，這是刻意的。它是每週三 05:30 跑一次的資料更新，
  > 不服務任何流量，停機期間讓它自己跑或不跑都無所謂。

- [ ] **回頭確認那兩個真的停了**（第 2 節）

  2026-09-09 修掉根因之後，`bootout` 對六個都成立，這一步預期會是空的。但**還是要
  跑**：這是驗證，不是修補，而且如果有人在 launchd 之外手動起過 colima 或那支腳本，
  留下的程序仍然只能用下面的方式收。

  ```sh
  # socat：kill supervisor shell，它的 trap 會收掉三個 socat 子程序
  pkill -f 'socat-tailnet-forwards.sh'
  sleep 2
  pgrep -fl socat                                  # 應為空

  # Colima：用它自己的停法，不要 kill
  colima stop
  ```

  `colima stop` 會依序卸載 disk、關掉 VZ、停掉 hostagent，輸出最後一行是 `done`。
  直接 kill `limactl` 跳過這些步驟，沒有理由這樣做。

- [ ] **驗證**（第 4 節）

---

## 4. 驗證停機

四項，全部要過。跑完這一段才能說平台停了。

```sh
colima status                                      # 期望：fatal msg="colima is not running"
docker info >/dev/null 2>&1 && echo 有回應 || echo 無回應          # 期望：無回應
curl -s -m 3 http://127.0.0.1:11434/api/tags >/dev/null && echo 在聽 || echo 已停   # 期望：已停
ps -Ao pid,command | grep -E 'limactl|socat|host-metrics|ollama serve' | grep -v grep    # 期望：無輸出
```

再加一項埠檢查，因為前面四項是「程序沒了」，這一項是「沒有東西在對外聽」：

```sh
lsof -nP -iTCP -sTCP:LISTEN | grep -E ':(8000|8001|8002|3000|3001|3002|5432|6379|9090|11434) '
lsof -nP -iTCP@100.108.250.62 -sTCP:LISTEN         # tailnet 位址，期望無輸出
```

兩個都應該沒有輸出。

**`tailscale serve` 不用動，也不需要動。** 它仍指向 `127.0.0.1:3000`，停機期間
外部連線會拿到 502。這是停機的正確表現：入口還在、後面沒東西，而不是入口消失。
關掉 serve 設定只是讓復機多一件要記得的事。

---

## 5. 這次停機撐不撐得過重開機

**預設是撐不過的，而且是刻意的。** 六個 plist 都還在 `/Library/LaunchDaemons`，
`bootout` 只影響當前這一次開機。重開機後：

1. `colima` 的 plist `RunAtLoad`，VM 起來；
2. `reconcile-port-bindings` 的 plist 也 `RunAtLoad`，它比對
   `EXPECTED_SERVICES` 跟 `docker compose ps --services --status running`，
   對缺的那些跑 `docker compose up -d $MISSING`
   （`launchd/lib/reconcile/expected_bindings.sh:40`）；
3. 於是**整包服務自動回到線上**，你不必做任何事。

這對非計畫的中斷是對的行為（那正是 `boot-recovery-acceptance.md` 要的），但對
計畫性停機是個陷阱：**停機後重開機，等於復機。**

要讓停機狀態跨越重開機——例如要搬機器、或停機的原因就是硬體——`bootout` 不夠，
要 `disable`：

```sh
for l in colima ollama socat-forwards host-metrics backup reconcile-port-bindings health-check; do
  sudo launchctl disable system/online.rcsl.$l
done
```

`disable` 寫進 launchd 的持久化覆寫資料庫，重開機後仍然有效。**它跟 `bootout`
是兩件事，不能互相取代**：`disable` 不會停掉正在跑的東西，`bootout` 不會影響
下次開機。要兩者都做。

復機時必須先 `enable` 再 `bootstrap`，否則 bootstrap 會被 disable 擋掉：

```sh
for l in colima ollama socat-forwards host-metrics backup reconcile-port-bindings health-check; do
  sudo launchctl enable system/online.rcsl.$l
done
```

**如果停機時沒有 `disable`，復機就不要 `enable`**——沒有被 disable 的 job 去
enable 它是無害的，但會讓下一個讀日誌的人以為當初 disable 過。

---

## 6. 復機程序

順序跟停機完全相反：先起被依賴的，再起依賴它的。

- [ ] **如果停機時做過 `disable`，先 `enable`**（第 5 節）。沒做過就跳過。

- [ ] **起 Colima，等 Docker 真的能用**

  ```sh
  sudo launchctl bootstrap system /Library/LaunchDaemons/online.rcsl.colima.plist
  ```

  然後**等到這一行有回應才往下**，不要用固定秒數的 sleep 猜：

  ```sh
  until docker info >/dev/null 2>&1; do sleep 2; done; echo "docker 就緒"
  ```

  Colima 的 VM 啟動是整個復機最慢的一步。在它就緒前跑任何 `docker compose`
  都會失敗，而失敗訊息會像是 compose 的問題，不像是時序的問題。

  > **這個等待迴圈一定要用操作者的身分跑。** `colima start` 會建立並切換到
  > `colima` 這個 docker context（endpoint 是 `~/.colima/default/docker.sock`），
  > 而 context 的選擇存在 `$HOME/.docker`。在 root 的 shell 裡用
  > `sudo -u rcslmac1 docker info` 檢查會拿到 root 的 `$HOME`，於是落回 `default`
  > context 的 `/var/run/docker.sock`——那個 symlink 指向 Docker Desktop 時代的
  > `~/.docker/run/docker.sock`，早就不存在了。結果是 VM 明明起來了，檢查卻永遠
  > 判失敗。要 `sudo -u rcslmac1 -H`，或直接用 rcslmac1 的 shell 跑。
  > 2026-09-09 復機時第一支腳本就是這樣白等了 180 秒。

- [ ] **起其餘的主機層 daemon**

  ```sh
  for l in ollama host-metrics socat-forwards backup reconcile-port-bindings; do
    sudo launchctl bootstrap system /Library/LaunchDaemons/online.rcsl.$l.plist
  done
  ```

  > `socat-forwards` 需要 tailnet 位址 `100.108.250.62` 已經起來，它自己會等，
  > 上限 120 秒。`tailscaled` 沒回來的話它會放棄——第 7 節有對應的症狀。

  > `reconcile-port-bindings` 是 `RunAtLoad`，bootstrap 的當下它就會跑一次，
  > 並且對缺的服務執行 `docker compose up -d`。所以下一步有可能發現服務已經起來了，
  > 這是正常的，不是重複執行的錯誤。

- [ ] **起 11 個服務**

  ```sh
  cd ~/dev/RCSL-AI-Nexus
  docker compose up -d
  ```

  用 `up -d` 而不是 `start`：對停著的容器它等價，但如果中間有人動過 compose 檔，
  `up -d` 會照新設定重建，`start` 會拿舊容器起來，而且不會告訴你這件事。

- [ ] **如果停機時 bootout 過 `health-check`，把它帶回來**

  ```sh
  sudo launchctl bootstrap system /Library/LaunchDaemons/online.rcsl.health-check.plist
  ```

  **這一步最容易漏，而漏掉的後果最安靜**：平台看起來完全正常，只是再也沒有人
  在看它。`restore.md` 開頭那句「沒有驗證過的備份不是備份」，同一個道理。

- [ ] **驗證**（第 7 節）

---

## 7. 驗證復機

```sh
cd ~/dev/RCSL-AI-Nexus
docker compose ps --services --status running | wc -l    # 期望：11
colima status                                            # 期望：is running
curl -s -m 3 http://127.0.0.1:11434/api/tags >/dev/null && echo ollama OK
lsof -nP -iTCP@100.108.250.62 -sTCP:LISTEN               # 期望：8000、8002、3001 三行
```

11 個服務是：`postgres redis prometheus grafana gateway admin-public admin-tailnet
frontend-public frontend-tailnet parser qdrant`。`migrate` 不算在內，它是跑完就
退出 0 的一次性工作，`--status running` 本來就不會有它。

最後兩項是端到端，前面都過了才有意義：

```sh
curl -s -o /dev/null -w '%{http_code}\n' https://rcslmac1demac-studio.tail68e30b.ts.net/    # 期望 200
tail -20 /opt/homebrew/var/log/nexus-health.log          # 期望：下一次執行回報健康
```

健康檢查的狀態變化會再寄一封信出去，內容是平台恢復。**那封信是復機完成的獨立
證據**——它跟你在這台機器上看到的東西走不同的路徑，這正是它的價值。如果停機時
選擇讓它寄信，收到這封「恢復」的信才算真的結束。

---

## 8. 出問題時

| 症狀 | 原因 | 處置 |
|---|---|---|
| `docker compose up -d` 說連不上 daemon | Colima 還沒就緒 | 回到第 6 節第 2 步的 `until` 迴圈，等它 |
| tailnet 位址沒有監聽埠，但服務都在跑 | `socat-forwards` 等 `tailscaled` 逾時放棄 | `tailscale status` 確認位址回來了，再 bootout / bootstrap 一次 socat-forwards |
| `bootstrap` 回報 `Bootstrap failed: 5: Input/output error` | 該 job 已經載入 | 先 `bootout` 再 `bootstrap`，不要重複 bootstrap |
| `bootstrap` 沒有效果、job 沒起來 | 停機時 `disable` 過 | 先 `enable`（第 5 節），再 bootstrap |
| `bootstrap` 回傳 0，但程序始終不出現、日誌檔連建都沒建 | launchd spawn 不起來，最常見是 `StandardOutPath` 的目錄該 job 的 `UserName` 不能寫 | `sudo launchctl print system/<label>` 看 `active count = 0` / `state = spawn scheduled`，再查日誌路徑的權限（第 2 節） |
| 等 docker 就緒的迴圈永遠不過，但 `colima status` 說在跑 | 檢查是在 root 的 `$HOME` 下跑的，docker context 落回 `default` | 用 `sudo -u rcslmac1 -H`（第 6 節的註） |
| 服務起來了但少幾個 | compose 檔或映像有變 | 讀 `migrate` 的日誌，不要讀應用的日誌——應用會在 migrate 上 gate（README「Running the stack」） |
| 什麼都不想修，只想回到線上 | — | `sudo reboot`。第 5 節說明了為什麼這會讓平台自己回來，前提是沒有 `disable` 過 |

最後一列不是玩笑，是這套設計的一個實際性質：**只要沒有 `disable`，重開機就是
一條有效的復機路徑**，而且它走的是 `boot-recovery-acceptance.md` 已經驗證過的
那條路，不是這份文件的手動路徑。手動復機到一半卡住而且時間緊迫時，重開機通常
比繼續除錯快。

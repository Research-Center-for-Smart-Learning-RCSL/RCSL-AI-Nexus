# Mac Studio 首次部署 Runbook

第一次把 Mac Studio 當成 24/7 AI 伺服器上線的完整前置清單。假設你沒有用過
macOS，並且需要另一個人幫忙（NTNU openresty proxy 的管理員，見第 8 部分）。

照順序做。每一步都有勾選框，做完打勾。指令都在「終端機」(Terminal) 裡打，第 1
部分會教你怎麼打開它。

相關背景文件：模型 runtime 為何不放進 Docker 見 [ARCHITECTURE.md](../ARCHITECTURE.md)
§0.1、§0.2；部署拓撲與 proxy 見 [architecture/deployment.md](../architecture/deployment.md)；
上線前完整安全檢查見 [architecture/security.md](../architecture/security.md) §14；
secrets 設定見 [secrets/README.md](../../secrets/README.md)。

---

## 0. 開始前先備妥

- [ ] Mac Studio 的實體存取，建議接 10Gb 有線網路（這台有 10Gb 乙太網路）
- [ ] 能聯絡到 NTNU proxy 管理員（第 8 部分他們要做四件事，可與你的步驟並行）
- [ ] 一個 Tailscale 帳號（免費即可），或沿用既有 tailnet
- [ ] 一支手機，裝好一個 TOTP app（Google Authenticator、1Password、Authy 皆可）
- [ ] `rcsl.online` 的 wildcard DNS 已指向 `140.122.250.55`（通常已存在，不用動）

---

## 1. Mac 第一次開機（新手向）

- [ ] 開機，跟著設定精靈走：選語言、地區、連上網路（建議插網路線）。**Apple ID 可以
  略過**，用本機帳號就好。建立你的使用者帳號，密碼記牢。
- [ ] 更新系統：左上角蘋果選單 > 系統設定 (System Settings) > 一般 (General) >
  軟體更新 (Software Update)，全部裝到最新。
- [ ] 打開終端機：按 `Cmd + 空白鍵` 叫出 Spotlight，輸入 `Terminal`，按 Enter。
  之後大多數指令都在這裡打。
- [ ] 命名這台電腦：系統設定 > 一般 > 關於本機 (About)，取一個好認的名字，tailnet
  的主機名會用到。
- [ ] 讓它不要睡：系統設定 > 顯示器或電池/電源，設定接電源時「永不睡眠」。這是 24/7
  伺服器，睡著了服務就斷了。
- [ ] 關閉 FileVault。首次部署刻意不開，理由與補償控制見
  [security.md](../architecture/security.md) §15.6；UPS 到位後要同時開 FileVault、關自動登入。

  ```sh
  sudo fdesetup disable      # 會問使用者名稱與密碼
  fdesetup status            # 要等到顯示 FileVault is Off
  ```

  解密在背景進行，用量少的話很快（APFS 只處理已使用的區塊）。**必須等到 Off，下一步的
  自動登入選項在那之前是灰的。**

- [ ] 自動登入：系統設定 > 使用者與群組 > 自動以你的帳號登入。這台無頭運作，自動登入是
  「插電就回到服務中」的必要環節。完整的鏈路是：

  ```
  通電/重開 → 自動登入 → LaunchDaemon（Tailscale、Ollama、reconcile-port-bindings、
                                       health-check）
           → Docker Desktop 自啟 → 9 個容器 restart: unless-stopped 回來
           → reconcile 等 utun0 有位址、docker 有回應、容器數穩定
           → 補上開機時綁失敗的 port forward
           → health-check 每 5 分鐘複驗，狀態變了寄信（第六環，它不修東西，
             它的工作是讓前面五環的失敗不再是無聲的）
  ```

  這條鏈**每一環都要成立**，少一環機器就回不到服務中，而且是無聲的——你只會發現「服務
  沒了」，不會知道斷在哪。所以下面有驗收測試。

  **最後那一環是 2026-07-26 第一次重開機測試打出來的，不是原本設計的。** 容器回來
  ≠ 服務回來：Docker Desktop 還原容器的時間點早於 `tailscaled` 把位址掛上 `utun0`，
  那些指名 tailnet 位址的 port forward 綁失敗，而 Docker **只記一行 warning、不重試**。
  沒有東西退出，所以 `restart: unless-stopped` 永遠不會觸發。九個容器全部 running、
  gateway 標著 healthy、而平台從 tailnet 完全打不到。第 7 部分裝的那個 LaunchDaemon
  就是補這一環，它的安裝步驟在那裡。

### 1.1 無人復原驗收（等第 7 部分整套跑起來之後再做）

這是整份 runbook 裡唯一**必須人在機器旁邊**做的測試，而且必須做。在它通過之前，你沒有
證據說這台機器能無人復原——你只有一串看起來正確的設定。

**第一輪：乾淨重開。**

```sh
sudo reboot
```

**不要碰它。** 等 2～3 分鐘，從另一台裝置（同 tailnet）：

```sh
ssh <你的帳號>@<伺服器的 100.x.y.z>
```

進去後一次跑完：

```sh
tailscale status | head -2
ollama ps
cd ~/dev/RCSL-AI-Nexus && docker compose ps
tail -20 /opt/homebrew/var/log/nexus-reconcile.log
curl -s -o /dev/null -w 'gateway readyz: %{http_code}\n' http://<TAILNET_IP>:8000/readyz
ls -l /opt/homebrew/var/nexus-health.state
```

通過的條件：tailnet 在線、Ollama 有回應、9 個容器 running（`migrate` 是 `Exited (0)`，
它是一次性工作，不該重啟）、對帳 log 最後一行是 `all bindings restored` 或
`all published bindings intact`、readyz 200、**health state 檔的 mtime 距離「你看的當下」
不超過五分鐘**（監測 daemon 自己也要撐過重開，它跟其他環一樣會無聲地不見）。

最後那一項的判準原本寫成「mtime 在開機後十分鐘內」，那是錯的：這個檔案每五分鐘被重寫
一次，永遠如此，所以你開機三十五分鐘後去看，mtime 就是三十五分鐘後——照字面讀會判成
失敗，而它是好的。要問的是「這個檔案夠不夠新」，不是「它是不是在開機那陣子寫的」。

**而修好之後的那個版本，在重開機後的頭五分鐘還是錯的——也就是這一段叫你去看的那個時間
點。** 原本 plist 是 `RunAtLoad=false` 配 300 秒的 `StartInterval`，所以一次開機的第一次
寫入是開機後五分鐘。你照上面「等 2～3 分鐘」去看，能看到的最新 mtime 是**開機以前**那次
寫的，年齡是「你等的 2～3 分鐘」加上「重開機落在上一個間隔的哪裡」（0～5 分鐘）——**3 到
8 分鐘，判準是 5 分鐘**。同一台健康的機器，這條判準的答案由你何時看決定。2026-07-26 的
20:24 和 20:29 兩次重開相隔 4 分 37 秒，整段沒有任何一次執行；20:26 那次檢查讀到 20:23，
過關剩十三秒的餘裕，是運氣。

**修法是讓開機當下就有一次執行。** plist 改成 `RunAtLoad=true`，而腳本的 boot grace 會把
那一次的檢查全部略過——它只把 state 檔原封不動重寫一次就退出。signature 沒變所以不可能
寄信，唯一改變的是 mtime，而 mtime 要說的正是這件事：**「我跑了，而且我刻意什麼都沒斷
言」**。這樣 mtime 永遠不會超過五分鐘舊，判準在任何時間點都可讀。

**這個修法原本是分開驗的，2026-07-26 21:02 那次開機把它合起來驗完了。** 分開驗的部分留在
這裡，因為它說明了為什麼當時只能那樣驗：grace 那條路是把 `BOOT_GRACE` 調到大於當時 uptime
跑出來的（機器已經開了二十分鐘，沒有辦法不重開就回到「開機後五分鐘內」）；`RunAtLoad`
那一半是 20:53 重載時驗的，它確實觸發、確實寫了 state 檔，而因為 uptime 早就超過 240 秒，
它正確地走了**完整檢查**那條路並且沒寄信。

**而「兩者在開機時一起動作」的證據不是 state 檔的 mtime。** 這件事值得先講，因為當時寫在
上面的預期就是去看 mtime，那個預期是錯的：開機那次的寫入五分鐘後就被下一次排程蓋掉了，
而且 `RunAtLoad=false` 也會產生**一模一樣**的 mtime（`StartInterval` 從載入時起算，兩種設定
的第一次排程都落在載入後 300 秒）。mtime 分不出這兩種情況。

看得出來的是統一日誌裡的 spawn／exit 配對，21:02 那次開機的四次執行：

| spawn | exit | 執行時間 | spawn 時 uptime |
|---|---|---|---|
| 21:02:43.356 | 21:02:43.473 | **117 ms** | **7 秒** |
| 21:07:43.678 | 21:07:44.286 | 608 ms | 307 秒 |
| 21:12:44.309 | 21:12:44.838 | 529 ms | 608 秒 |
| 21:17:44.858 | 21:17:45.386 | 528 ms | 909 秒 |

第一列就是開機那次：uptime 7 秒，遠在 240 秒的 grace 之內。**而那個執行時間本身就是它走了
grace 路徑的證據**——完整路徑要跑六個 curl、一次 `docker info`、一次 `docker compose ps`、
十次 `docker inspect`，暖機狀態下是 528～608 毫秒（上表另外三列），冷開機只會更慢，不可能
是 117 毫秒。配上 `last exit code = 0` 而 `nexus-health.log` 一行都沒有新增：能安靜地 exit 0
又這麼快的路徑只有 grace 那一條（`cd "$REPO"` 那個 FATAL 會 exit 1 並留下 log 行）。第二列
是開機後第一次真檢查，uptime 307 秒、走完整路徑、signature 沒變所以沒寄信。

**要重驗的話用日誌，不要用 `runs` 計數器。** `sudo launchctl print system/online.rcsl.health-check`
印的 `runs` 沒有附時間，讀到 `runs = 3` 分不出是「`RunAtLoad` 加兩次排程」還是「三次排程」，
還要再拿讀取時刻回推。下面這一行沒有這個歧義——`xpcproxy` 那行是 launchd 真的 spawn 了一個
process，`service inactive` 是它結束：

```sh
/usr/bin/log show --last 30m \
  --predicate '(process == "xpcproxy" OR process == "launchd") AND eventMessage CONTAINS "online.rcsl.health-check"' \
  --style compact
```

（用 `/usr/bin/log` 的絕對路徑，`log` 在 zsh 裡會被別的東西接走。）

**順帶：那個 boot grace 在 2026-07-26 之前一次都沒有生效過。** 它解析
`sysctl -n kern.boottime` 的輸出 `{ sec = 1785068938, usec = 428375 } ...` 用的是
`s/.*sec = \([0-9]*\).*/\1/`，開頭的 `.*` 是貪婪的，會一路吃到 `usec`——抓到的是微秒欄位，
算出來的 uptime 是整個 Unix epoch，那個比較**只可能得到「不在 grace 裡」一個答案**。這是
這份文件一路在抓的同一種缺陷，而這次發作在一個唯一職責就是要有兩種答案的檢查上。它同時
讓 2026-07-26 20:45 以前每一封告警信的 `uptime` 欄位都是九位數的垃圾。修法是把樣式錨定在
行首（`s/^{ sec = ...`），而 grace 從 300 改成 240：跟 `StartInterval` 一樣是 300 的話，
開機後第一次觸發剛好落在邊界上，要不要評估取決於 launchd 花了幾秒載入這個 job，而那決定
了一次開機的第一次真檢查是在五分鐘還是十分鐘。

**那個邊界不是假想的，21:02 那次開機量到了：第一次排程觸發在 uptime 307 秒。** 距離 300
只有 7 秒。grace 若還是 300，這次會以 7 秒之差走完整檢查而通過；launchd 慢載入 8 秒，同一台
機器的同一次開機就會變成跳過，第一次真檢查推到開機後十分鐘。240 把這件事變成不用想——
上表那 307 秒現在有 67 秒的餘裕，而不是 7 秒。

**收不到信不算通過的證據。** 狀態沒變就不寄信，所以一切正常時信箱是空的；而監測 daemon
自己沒起來的時候，信箱也是空的。這兩件事在信箱裡長得一模一樣，要分辨只能看 state 檔。

**`readyz` 那一行是這串裡唯一不能省的。** 2026-07-26 第一次跑這個測試時，前面每一項都
過了——tailnet 在線、9 個容器 running、gateway 標著 healthy——而 gateway、admin-public、
frontend-public 三個 port 一個都沒綁，平台從 tailnet 完全打不到。`docker compose ps` 看
起來完全正常，因為容器確實在跑；缺的是 host 這一側的轉發。第 7 部分的 port 對照表是它的
完整版本，只看一個 readyz 也足以抓到。

還有一件事會誤導你：**SSH 進得去不代表服務在。** Tailscale SSH 由 `tailscaled` 自己在
tailnet 介面上服務，`tailscale serve` 的管理入口轉發的是 loopback，兩條都不經過會出事的
那種 binding。所以你會順利登入、看到一切正常，而 gateway 是死的。

**對帳 log 有六種結果，意思不一樣。** 它管兩件事——「容器有沒有起來」和「port 有沒有綁」
——所以要從頭讀，不能只看最後一行：

| `nexus-reconcile.log` | 意思 |
|---|---|
| `all expected services running` → `all published bindings intact` | Docker 自己把容器還原了，`tailscaled` 也比它快。兩條修復路徑都沒被走到。算過，但**什麼都沒測到** |
| `all expected services running` → `OK: all bindings restored` | 競態發生了，reconciler 補回來了。**這是最有價值的結果**——binding 修復路徑被真的走過一次。2026-07-26 21:02 出現過一次，**是 §1.1a 注入出來的，不是等到的**；七次自然開機一次都沒等到 |
| `docker did not restore the stack; bringing it up` → `stack up: all expected services running` | Docker 沒還原容器，reconciler 自己把整套拉起來了。**這也是有價值的結果**——2026-07-26 19:10 那次開機就是這個情況，而當時的 reconciler 還不會做這件事（那次是人手救的）。2026-07-26 21:52 出現過一次，**是 §1.1b 注入出來的，不是等到的**；開機後 51 秒復原完成 |
| `STILL UNBOUND after recreate: <服務>` | 有東西壞在 `--force-recreate` 修不了的地方（internal 網路、port 被佔）。看那個服務的 `docker inspect` 和 Docker backend log |
| `FATAL: still not running after up -d: <服務>` | 容器起不來，不是沒被叫起來。`docker compose logs <服務>` 才是要看的地方，重跑 reconciler 不會有幫助 |
| log 不存在或是空的 | daemon 根本沒跑。`sudo launchctl list \| grep reconcile` 看有沒有註冊，第二欄是上次結束狀態 |

第一種結果要當心：它是運氣，不是證明。而**重開機逼不出第二種**：七次開機量下來，餘裕的
天花板算出來是 1.3 秒而它從來沒有變成負的——**那個算式的位址那一端在 21:51 被推翻了，
更正在下面「快取不會接續」那一段，而「不要靠重開機」這個結論沒有變**。要真的走過
binding 修復路徑，用 **§1.1a 的故障注入**，不要一直重開。**2026-07-26 21:02 照這樣做了，
第二種結果當場就出來了**，實測記錄在 §1.1a。

**`all published bindings intact` 這一行原本後面接著 `; nothing to do`，那句話害過一次。**
2026-07-26 19:10 的開機一個容器都沒有，而 reconciler 印的就是這一行然後 exit 0——因為它
掃的是「正在跑的容器」，而一個容器都沒有的時候，掃出來自然沒有壞掉的 binding。現在它先
確認該跑的服務都在，平台不完整時就算 binding 全對也 exit 1。

**第一輪失敗的話：修好，然後從頭重跑第一輪。** 不要因為「知道原因了」就跳到第二輪——
第二輪的前提是第一輪通過，而通過的定義是跑完整串、每一項都對。

**實測記錄（2026-07-26，第二次跑）：通過，落在第二種結果。** 17:21:40 開機、放著不管，
上面五項全過：tailnet 在線、Ollama 只聽 `127.0.0.1:11434`、9 個容器 running 且 `migrate`
是 `Exited (0)`、readyz 200（三項檢查都 true）。第 7 部分的六個 binding requested 與
actual 全部相符，其中 Grafana 的 `127.0.0.1:3002` 是這台機器**有史以來第一次**在開機時綁
上。對帳 log 最後一行是 `all published bindings intact; nothing to do`——reconciler 在開機
後 7 秒就跑了、等完三個前置條件、沒有東西要修。**修復路徑到目前為止還沒有被任何一次開機
真的走過。**

**實測記錄（2026-07-26，第三次跑）：通過，一樣落在第二種結果。** 18:07:46 關機、
18:08:06 起來、放著不管。六個 binding requested 與 actual 全部相符、六個入口全 200、
Ollama 只 LISTEN 在 `127.0.0.1:11434`。**這次多證明了一件事：監測 daemon 自己撐過了重開。**
它是 17:56 才裝的（在 17:21 那次開機之後），所以在這次之前，整條鏈裡它是唯一沒有任何
證據的一環。`nexus-health.state` 在 18:43:17 被重寫，launchd 在 18:08:17 載入這個 job，
`18:08:17 + 7×300 = 18:43:17` 剛好對上，代表它從 18:13:17 起就一直在跑。

**實測記錄（2026-07-26，第四次開機）：這一次是第二輪，macOS 26.5.2 更新，而它失敗了。**
`/Library/Receipts/InstallHistory.plist` 記著 `macOS 26.5.2` 於 19:09:47 裝完，機器
19:08:46 開機——19:04:18 關機的那次就是更新重開。**第二輪的兩個額外檢查都過了**：
`autoLoginUser` 還是 `rcslmac1`，`pmset autorestart` 還是 1，更新沒有重置它們。
`tailscaled` 也贏得乾淨俐落（見下面那張表），Ollama 正常——然後 `docker compose ps`
是空的。**十個容器一個都沒起來。**

這一輪照規矩是可以做的：第一輪已經連過三次，閘門是開的。所以這不是「兩輪混在一起導致
無法歸因」，而是第二輪測出了一個第一輪三次都測不到的東西。

它們沒有壞：`docker compose ps -a` 顯示十個都在，關機時全部 `Exited (0)` 乾淨退出，
`restart: unless-stopped` 政策也還在。是 Docker Desktop 這次沒有還原它們。engine 在
19:10:37 就 running 了，而 backend log 在那之後**一條 `exposer.Add` 都沒有**——對照
18:08 那次開機，同一個位置有完整的九條。前兩次開機它守住了 `unless-stopped` 的承諾，
這次沒有。那是 Docker daemon 的承諾，不是這台機器的。

**最可能的原因是「這是系統更新的重開，不是普通的重開」，但這只是假設。** 還原成功的兩次
（17:21、18:08）是普通重開，沒還原的這次是更新重開，機制上也說得通：更新的重開有自己的
階段，不是一次乾淨的關機開機。但這是一次觀察一個相關性——正是下面「原本寫的原因是錯的」
那段所記的那種證據量。**所以不要把修法建立在這個假設上**：修法要處理的是「容器沒在跑」，
不管是什麼讓它沒在跑。這也意味著第二輪之後要多看一件事：`docker compose ps` 不能只看
`Up` 幾個，要看是不是九個。

**而 reconciler 回報了成功。** 它的第三個前置條件在等「容器數量不再變動」，寫的條件是
數量必須大於零才算穩定，所以數量是零時它空轉到十分鐘的 deadline，然後掃過零個容器、
找不到壞掉的 binding，印出 `all published bindings intact; nothing to do` 並 exit 0。
**一個為了修復開機而存在的腳本，在一個完全空的平台上回報一切正常。**這正是它自己註解裡
警告過的那種錯誤——一個時序讓它只可能產生一種答案的檢查——只是換了個地方發作。

**監測有效，這是這次唯一沒有出問題的一環。** 19:14:59 抓到七項全部失敗（六個入口加
services），19:15:02 寄出信。整條鏈裡真正說出實話的只有它。

修法在 `launchd/reconcile-port-bindings.sh`：前置條件三不再等一個數字，改成等一份**具名
的服務清單**，缺的就 `docker compose up -d` 拉起來，再驗一次。對著當時那個空平台實跑，
28 秒把九個服務帶回來、六個入口全部 200；再跑一次是 idempotent 的。**但這是手動跑出來
的結果，不是開機跑出來的**——所以這一輪要重跑，通過的定義見上面那張表的第三種結果。

**實測記錄（2026-07-26，第五次開機）：第一輪第四次，通過，落在第一種結果。** 19:42:59
`sudo reboot`、19:43:20 起來、放著不管。九個服務 running 且 `migrate` 是 `Exited (0)`、
六個 binding requested 與 actual 全部相符、六個入口全 200、Ollama 只在 `127.0.0.1:11434`。
對帳 log 是 `all expected services running` → `all published bindings intact`——Docker 自己
還原了容器，`tailscaled` 也贏了，**兩條修復路徑一條都沒被走到**。

這次唯一新增的證據是：**跑的是改寫過的 reconciler**（修法 19:41 commit，daemon 直接執行
工作目錄裡的檔案），而具名清單那個前置條件第一次在開機時真的做了判斷——19:43:39 daemon
回應、19:43:55 判定齊全，16 秒，就是三次穩定取樣的時間，沒有多花。

**實測記錄（2026-07-26，第六與第七次開機）：連續重開兩次，兩次都通過，兩次都是第一種
結果。** 這是照上面那句「連續重開兩次、盯第二次」做的——**槓桿拉了，結果沒被逼出來**。

第六次 20:24:21、第七次 20:28:58，相隔 4 分 37 秒。兩次都是九個服務 running 且 `migrate`
是 `Exited (0)`、六個 binding requested 與 actual 全部相符、六個入口全 200、Ollama 只在
`127.0.0.1:11434`。reconciler 兩次都是 `all expected services running` →
`all published bindings intact`，判定時間都是 16 秒，跟 19:43 一模一樣——具名清單那個前置
條件的成本是穩定的。

**第七次是七次開機以來最險的一次通過：+1.4 秒。** 槓桿在機制上確實有效——第七次如預期
沒有快取，位址等了 9 秒，餘裕從第六次的 8.3 秒掉到 1.4 秒。但它還是贏了，而為什麼贏，
下面那張表現在說得出來。

**七次開機了，六種結果裡最有價值的那兩種還是空白。**（第八次開機把其中一種填上了，靠
§1.1a 的注入而不是等待——這句話對「自然開機」而言仍然成立，七次自然開機兩格都是空的。）

它贏得有多險，七次開機的 log 對得出來：

| 開機 | `tailscaled` 起 | 位址可用 | Docker `exposer.Add` | 餘裕 |
|---|---|---|---|---|
| 16:45（失敗） | 16:45:15 | 16:45:32（+17 秒） | 16:45:29 | **−3 秒** |
| 17:21（通過） | 17:21:48 | 17:21:48（+0 秒） | 17:21:59 | **+11 秒** |
| 18:08（通過） | 18:08:14 | 18:08:23（+9 秒） | 18:08:25 | **+2 秒** |
| 19:09（失敗，別的原因） | 19:09:59 | 19:10:00（+1 秒） | *（從來沒有）* | *（沒有競態可言）* |
| 19:43（通過） | 19:43:28 | 19:43:37（+9 秒） | 19:43:39.7 | **+2.7 秒** |
| 20:24（通過） | 20:24:22 | 20:24:24（+2 秒，讀到快取） | 20:24:32.3 | **+8.3 秒** |
| 20:29（通過） | 20:29:06 | 20:29:15（+9 秒，沒快取） | 20:29:16.4 | **+1.4 秒** |
| **21:02（§1.1a 注入）** | 21:04:13（被壓住 90 秒） | 21:04:14（+1 秒，讀到快取） | 21:02:56（**綁失敗**） | **−78 秒** |
| **21:51（§1.1b 注入）** | 21:51:30（自然起） | 21:51:41（**+11 秒**，沒快取） | *（沒有出場，stack 被停掉）* | *（沒有競態可言）* |

**最後那兩列不屬於上面的統計，但它們不屬於的方式不一樣，這個差別是有用的。** §1.1a 那次
`tailscaled` 不是自然起的，位址那一欄量的是「釋放之後多久」不是「開機之後多久」，所以它
兩欄都不能用；它唯一要說的是餘裕：自然開機的天花板是 +1.3 秒，注入把它推到 **−78 秒**，
六十倍。這正是 90 秒那個數字要買的東西，而 21:02:56 那三條綁失敗就是買到了的證據。

**§1.1b 那次相反：注入壓的是 Docker 那一側，`tailscaled` 完全是自然開機起來的**，所以
Docker 那一欄空白是照設計的，而**位址那一欄是一個貨真價實的自然開機觀測**——它就是下面
把「9 秒沒有散布」推翻掉的那一筆。一次注入只污染它壓住的那一側，另一側照樣可以拿來量，
這件事事前沒有想到。

**「Docker 那一側是穩定的 11～14 秒」這句話，第六、七次把它推翻了一半。** 六次有出場的
開機，從 `tailscaled` 起算到第一個 `exposer.Add`：14.0、11.0、11.0、11.7、**10.3**、
**10.4** 秒。最後這兩次是史上最快的兩次，**預算從十一秒縮到 10.3 秒**，而且是往壞的方向
縮。Docker 仍然是變異較小的那一側，但它不是常數。

位址那一側反而是三次沒有快取的開機一模一樣的 **9 秒**（18:08、19:43、20:29），一次不差。
所以現在的算式很直白：`10.3 − 9 = 1.3 秒`。

**這一段修 Docker 那一側的時候，用的是「三次一樣就是常數」的推法去放過位址那一側，而
21:51 把它也推翻了。** 第四次沒有快取的開機位址是 **11 秒**，五次排出來是 9、9、9、11、17
（最後那個是 16:45）。兩側現在都不是常數，`10.3 − 9 = 1.3` 只是拿兩個分布各一端相減出來的
一個數字，不是天花板。完整的更正寫在下面「所以停止用重開機碰運氣」那一段，結論沒有變。

**第四次開機把這張表的框架本身推翻了一半。** 它假設 Docker 一定會在某個時間點綁定，
問題只是早或晚；19:09 那次 Docker 根本沒到場。這張表量的是一場競態，而競態的前提是兩邊
都會出現。位址 +1 秒就上來、餘裕大得不可能輸——然後平台還是死的。**贏了這場競態不等於
開機成功**，這是那次唯一便宜的收穫。

**這裡原本寫的原因是錯的，第三次開機把它推翻了。** 原本寫的是「失敗那次卡在 logtail 的
bootstrap DNS 重試迴圈」。18:08 那次照樣跑完整個迴圈（12 個 derp 試 `log.tailscale.com`，
18:08:20 還多跑一輪 `controlplane.tailscale.com`），然後贏了 2 秒。那個迴圈根本不慢：
每一次嘗試都在同一秒內以 `network is unreachable` 或 `no route to host` 立即失敗，不是
DNS timeout。log 裡四次開機每一次都跑了它。那是兩個資料點看出來的相關性被當成了因果。

**真正的變數是 netmap 磁碟快取。** `tailscaled.log` 裡所有相關的行，一行不漏：

| 時間 | log | |
|---|---|---|
| 14:12:41 | `writing netmap to disk cache` | |
| 14:42:24 | *（套用 tailnet ACL，commit `17939ed`）* | |
| 15:53:06 | `netmap cache is not available` | 開機 |
| 16:45:15 | `netmap cache is not available` | 開機，**失敗，−3 秒** |
| 16:45:32 | `writing netmap to disk cache` | |
| 17:21:48 | `Start: loaded netmap from disk cache; 1 peers` | 開機，**+11 秒** |
| 18:08:14 | `netmap cache is not available` | 開機，**+2 秒** |
| 18:08:23 | `writing netmap to disk cache` | |
| 19:09:59 | `Start: loaded netmap from disk cache; 1 peers` | 開機，**+1 秒** |
| 19:43:28 | `netmap cache is not available` | 開機，**+9 秒（餘裕 +2.7 秒）** |
| 19:43:38 | `writing netmap to disk cache` | |
| 20:24:24 | `Start: loaded netmap from disk cache; 1 peers` | 開機，**+2 秒（餘裕 +8.3 秒）** |
| 20:29:06 | `netmap cache is not available` | 開機，**+9 秒（餘裕 +1.4 秒）** |
| 20:29:15 | `writing netmap to disk cache` | |
| 21:00:27 | `netmap cache is not available` | **daemon 重啟（不是開機）——第一個例外，見下** |
| 21:00:30 | `writing netmap to disk cache` | |
| 21:04:13 | `Start: loaded netmap from disk cache; 1 peers` | §1.1a 注入釋放後，**+1 秒** |

有快取時位址在 `tailscaled` 起來的同一秒就上來，因為它完全不需要 control plane：17:21:52
時 `tailscaled` 還在報 `You are logged out ... failed to resolve
controlplane.tailscale.com`，而位址早就在 `utun0` 上了。沒有快取，位址就得等 control——
這次等了 9 秒，失敗那次等了 17 秒。

**而快取不會接續。** 它是在 control 送來新 netmap 時才寫的，**讀了快取的那次開機不會重寫
它**：17:21 讀了、沒寫，18:08 就沒得讀。所以贏了十一秒的那次開機，等於把下一次推進慢的
那條路。唯一看起來的例外也符合同一條規則：14:12:41 寫了快取而 15:53 開機讀不到，中間
14:42:24 套用了 tailnet ACL，那會改掉 netmap 帶的封包過濾規則。

最後這一步只有一次「讀了但沒重寫」的觀察撐著，所以它是模型不是已證實的機制。但它給出一個
不用花錢就能驗的預測：18:08:23 寫了快取，所以**下一次開機應該是快的那種，再下一次又是慢
的**。餘裕如果照這樣交替，這個模型就是對的。

**預測連續對了四次，七次開機零例外。** 19:09:59 讀到快取（+1 秒），沒重寫，所以預測下一次
是慢的——19:43:28 果然 `netmap cache is not available`，等了 9 秒，19:43:38 重寫。19:43
寫了，所以預測下一次是快的——20:24:24 果然 `loaded netmap from disk cache`，+2 秒。20:24
讀了而**那個 session 沒有任何 `writing netmap` 那一行**，所以預測再下一次是慢的——20:29:06
果然讀不到，等了 9 秒，20:29:15 重寫。

**「讀了不重寫」現在有三次觀察撐著（17:21、19:09、20:24），而快慢交替在七次開機上一次
例外都沒有。** 這已經不太算模型了。依同一條規則，**下一次開機會是快的那種**（20:29:15
寫了一份），餘裕約 8 秒。

**上面那句話寫完之後，模型就出現了第一個例外，而且是 §1.1a 的準備動作跑出來的。**
21:00:20 手動 `bootout`／`bootstrap` 一次 `tailscaled`（那是為了確認 §1.1a 的救援指令真的
有效才做的），21:00:27 起來，讀到的是 `netmap cache is not available`——**20:29:15 才寫過一
份，31 分鐘後讀不到**。模型預測這裡應該是 HIT。

TTL 解釋不通：18:08:23 寫、19:10:00 讀到，中間隔了 61 分鐘是 HIT；這次隔 31 分鐘是 MISS。
唯一乾淨的區分是**它不是開機，是同一個 uptime session 裡的 daemon 重啟**——模型的每一次
HIT 都發生在重開機之後。所以現在有兩個都還沒有第二個觀察撐著的可能：模型是錯的，或者
「daemon 重啟」和「開機」對這份快取來說不是同一件事。**在分出來之前，快慢交替那句話只能
用在開機上，不能用在重啟上。**

要便宜地查它，在 `bootout` 前後各看一次快取檔在不在：

```sh
sudo ls -l /Library/Tailscale/          # 那個目錄 root only
```

而那次注入的開機**沒有測到原本那個預測**：`tailscaled` 的開機啟動被壓住了 90 秒，21:04:13
是釋放之後才起的，它讀到的是 21:00:30 那份。所以「下一次開機是快的那種」到現在還是沒被
驗過。**21:04:13 讀了而且沒有重寫**（那之後 log 裡沒有任何 `writing netmap`），所以「讀了
不重寫」現在是四次觀察，而**新的預測是：下一次開機沒有快取，位址 9 秒**。

**那個預測在 21:51 那次開機（§1.1b 的注入）驗了，一半中、一半沒中。** 沒有快取這一半中了：
21:51:30 `load netmap from cache: netmap cache is not available`，**這個模型連續第五次預測命中**
（「讀了不重寫」本身仍然是四次觀察——21:51 是 miss，不是 load，它驗的是那四次推出來的預測）。
**位址 9 秒這一半沒中，實際是 11 秒**——`tailscaled` 21:51:30 起、
`peerapi: serving on http://100.108.250.62` 在 21:51:41。

**reconcile log 上那個 15 秒不是這個數字。** 它每 5 秒取樣一次，位址在第 11 秒上來、它在第
15 秒才看到。**要量位址就讀 `tailscaled` 的 log，不要讀 reconciler 的**——這和 §1.1a 那個
5 秒 off-by-one 是同一類錯誤，差別只在那次是工具算錯，這次是拿取樣器當碼錶。（21:51:41 也
`writing netmap to disk cache`，所以交替的下一個預測是：**再下一次開機讀得到快取、位址 0 到
1 秒**。）

**而這個槓桿，第六、七次把它試到底了，結論是它逼不出結果。**
`OK: all bindings restored` 需要一次**輸掉**競態的開機。「連續重開兩次、盯第二次」在機制上
完全成立：第七次確實沒有快取、位址確實等了 9 秒、餘裕確實從 8.3 秒掉到 1.4 秒。但它還是
贏了，而現在算得出來為什麼**它必然會贏**：

- 沒有快取的三次開機，位址一律 **9 秒**（18:08、19:43、20:29），沒有任何散布。
- Docker 綁定最快的一次是 **10.3 秒**（20:24），六次裡的最小值。

`10.3 − 9 = 1.3 秒`。**這個槓桿的天花板就是 1.3 秒的餘裕，靠它再重開下去不會輸。**

**上面那句話的前提在 21:51 被推翻了，結論還在，但理由換了一個。** 那一行「沒有任何散布」
是三次取樣被當成常數：第四次無快取的開機（21:51）位址是 **11 秒**。用同一種量法（`tailscaled`
的 log，不是 reconciler 的取樣）把五次無快取開機排出來是 **9、9、9、11、17**——16:45 那個 17
秒不是被後續開機推翻的離群值，它是這個分布的上端，而它從來沒有被推翻過，只是沒有再出現。
用 11 秒重算，`10.3 − 11 = −0.7 秒`。

**但不要把這個修正讀得太用力。** 那 −0.7 秒是拿一次開機的位址去減另一次開機的 Docker 最小
值，跨開機取兩個分布的極值相減，正是這份文件一路在避免的推法；而且 21:51 那次 Docker 根本
沒有綁（stack 是被停掉的），所以它**沒有產生任何餘裕的觀測**。成立的是比較弱的那個結論：
**餘裕的分布比先前算的寬，「再重開下去不會輸」是過度確定的說法**，「贏 1.4 到 2.7 秒」也
只是三次無快取開機的樣子。

**所以停止用重開機碰運氣——結論不變，理由是另一個。** 不是因為重開必然贏，而是因為那是在
等天氣：注入把 `tailscaled` 壓住 90 秒，是 Docker 需要輸掉的餘裕的六倍，那可重複；在一個
9 到 17 秒的位址分布上重開機碰運氣不可重複。改用下面 §1.1a 的故障注入——2026-07-26 21:02
照做了，那一格當場就填上了。

**狀態現在是：第一輪跑了六次、通過五次；第二輪跑了一次、失敗。** 第二輪的失敗不是第一輪
的失敗，第一輪那五次通過仍然成立；但「兩輪都過」還沒有發生，所以下面那句「兩輪都過才代表
這台機器真的能自己復原」仍然是未達成的。

**這裡原本寫的是「第一輪通過六次」，那是把嘗試次數當成通過次數。** 第一輪的六次是
16:45、17:21、18:08、19:43、20:24、20:29，而**第一次（16:45）是失敗的那一次**——它就是
整個 reconciler 存在的理由，不可能同時算成一次通過。通過的是後面五次。數字錯得不大，
但它錯的方向是讓紀錄看起來比實際更乾淨，而這份文件的其他地方（19:43 標成「第一輪第四
次」）本來就對得出來。**第二輪至今仍然只跑過一次、失敗那一次**；但那次失敗之後把它救起來
的那條路徑（容器拉起）已經在 21:52 的開機上走過了，靠 §1.1b 的注入，所以現在最欠的那一次
測試不再是它，而是第二輪本身——注入餵給 reconciler 的是**狀態**，第二輪要測的是系統更新
重開這件事的**全部**（自動登入、`pmset autorestart`、Docker 在更新後怎麼做），那三件事注入
一件都碰不到。

**兩條修復路徑現在都在開機時走過了，而且兩條都是注入出來的，沒有一條是等到的。**

- **binding 修復路徑：走過了**，2026-07-26 21:02，`OK: all bindings restored`。但它是
  §1.1a **注入**出來的，不是自然開機等到的——七次自然開機一次都沒觸發過。它證明的是
  「這條路在開機那個所有東西同時在動的環境裡真的會修好」，不是「那個競態會自己發生」
  （後者 16:45 已經證過了）。
- **容器拉起路徑：走過了**，2026-07-26 21:52，`docker did not restore the stack; bringing
  it up` → `stack up: all expected services running`，開機後 51 秒復原完成。它是 §1.1b
  **注入**出來的（停掉 stack 再重開，靠 `restart: unless-stopped` 的 `unless`），不需要人
  在現場。它證明 reconciler 在開機時能把整套拉起來；**不證明** Docker Desktop 的還原會自己
  失敗——那件事只發生過一次（19:10），原因至今未明。19:09 那次的復原是**人手跑的**
  `docker compose up -d`（`migrate` 的 `StartedAt` 是 19:28:26，那就是證據），不是 reconciler。

**兩條路徑各有一次手測，記在這裡，因為手測和開機測不是同一件事。** 停掉 `grafana` 再手跑
reconciler：`not running: grafana` → `docker did not restore the stack; bringing it up` →
`stack up: all expected services running` → `all published bindings intact`，16 秒、exit 0，
之後 `127.0.0.1:3002` requested 與 actual 相符、`/login` 200。**注意它沒有重建容器就把
binding 帶回來了**——這和「必須 `--force-recreate`」不衝突，是兩種不同的壞法：容器**還在跑**
但轉發表是空的，`up -d` 是 no-op，只能重建；容器**是停的**，`up -d` 會把它起來，轉發是那時
候才建立的。腳本兩條都有，是因為要修的是兩件事。

手測補不上的正是開機才有的東西：所有東西同時在動。所以這兩種結果在 §1.1 的表上當時仍然
算空白。

**其中 binding 那一種，21:02 的注入把它補上了，而兩者的差別剛好被量出來。** 手測那次
reconciler 16 秒跑完；注入那次同一個腳本，具名清單判定花了 27 秒、binding 掃描花了 40 秒。
同一段程式碼，在「所有東西同時在動」的開機環境裡慢了一倍以上——這就是手測補不上的那部分，
現在有數字了。容器拉起那一種仍然是空白。

**第二輪：系統更新。** 第一輪通過之後才做，因為兩者一起做會讓失敗無法歸因——你分不出
是更新的問題還是自動登入沒設好。

```sh
sudo softwareupdate -i -a --restart
```

更新完重跑上面同一串，另外**一定要多確認這兩項**：

```sh
defaults read /Library/Preferences/com.apple.loginwindow autoLoginUser
pmset -g | grep autorestart
```

macOS 更新重置這兩項是有前例的，而它們正好是無人復原鏈路上的兩個環節。被重置的話重新
設定，然後再測一次。

**實測記錄（2026-07-26）：跑了，失敗了，但不是失敗在這兩項。** 26.5.2 於 19:09:47 裝完，
`autoLoginUser` 和 `pmset autorestart` 都沒有被重置——這兩個檢查存在的理由這次沒有兌現。
失敗在一個沒人列出來的地方：**Docker Desktop 更新重開後沒有還原任何容器**，九個服務全數
沒起來，而當時的 reconciler 對著空平台回報成功。完整的記錄與修法在 §1.1 的第四次開機。

所以這一段要多一句：**更新之後不要只確認上面那兩項**，§1.1 那一整串都要重跑，尤其是
`docker compose ps` 要數到九個、以及 readyz。更新重開比普通重開多動到什麼，目前沒有人
真的知道。

**兩輪都過，才代表這台機器經歷過真實的重開與系統更新並自己完整復原。** 目前是第一輪跑六次
過五次、第二輪跑一次失敗一次，所以這句話還沒有成立。在它成立之前不要遠端做系統更新——更新失敗
停在互動畫面時，遠端修不了。

---

### 1.1a 故障注入：把 binding 修復路徑逼出來（人一定要在機器旁邊）

> **這一節跑過了，2026-07-26 21:02，通過。** 下面前半段是當時的動機與做法，寫在還沒跑
> 之前，語氣維持原樣；結果與實測數字在本節末的「實測記錄」。要重跑（改過 reconciler、
> 換過 Docker Desktop 版本）就照原步驟，它是可以重複跑的。

七次開機之後，六種結果裡最有價值的 `OK: all bindings restored` 還是空白，而 §1.1 已經
算出來它**不會**靠重開機出現：沒有快取的開機位址一律 9 秒、Docker 最快 10.3 秒，餘裕的
天花板是 1.3 秒。「連續重開兩次盯第二次」這個槓桿拉到底了，20:29 那次贏 1.4 秒。

再重開下去不是測試，是等天氣。這一段是自己造天氣。

**做法**：開機時把 `tailscaled` 壓住 90 秒，讓 Docker Desktop 一定在位址存在之前綁定。
Docker 在 `tailscaled` 起來後 10.3～14 秒綁定，90 秒是它需要輸掉的餘裕的六倍。

**先讀這一段再動手。** 壓住的那 90 秒裡，這台機器**完全不在 tailnet 上**：沒有 Tailscale
SSH、沒有 `tailscale serve`、從任何地方都連不進來。Mac Studio 沒有 out-of-band 管理（下一
節就在講這件事），所以**只有人在機器旁邊時才可以跑這個**。

腳本的釋放寫在 trap 裡，涵蓋正常結束、SIGTERM、SIGINT、SIGHUP，**涵蓋不了 SIGKILL**。真
被 SIGKILL 掉的話 `tailscaled` 會一直不起來，在機器上打這一行救回來：

```sh
sudo launchctl bootstrap system /Library/LaunchDaemons/homebrew.mxcl.tailscale.plist
```

直接重開機也可以，因為腳本做的第一件事就是刪掉自己的 plist——**不論發生什麼，它只影響
一次開機**。

它不會動到 tailscale 的偏好設定：`bootout`／`bootstrap` 是重啟 daemon，它會帶著磁碟上原本
的偏好回來，跟重開機做的事一樣。（`tailscale down`／`up` 是另一個候選，被否決了：`up` 可能
把沒在命令列上指名的偏好重設掉，而這台機器的偏好裡包含 Tailscale SSH，那正是遠端進來的
那條路。）

**步驟**（`launchd/delay-tailscaled-once.sh` 與 `launchd/online.rcsl.delay-tailscaled-once.plist`
在 repo 裡，**平常不安裝**，第 7 部分的安裝清單也刻意沒有它）：

```sh
cd ~/dev/RCSL-AI-Nexus
sudo install -o root -g wheel -m 644 \
  launchd/online.rcsl.delay-tailscaled-once.plist /Library/LaunchDaemons/
sudo reboot
```

**不要碰它，等五分鐘**，然後在機器上（不是 SSH）：

```sh
tail -30 /opt/homebrew/var/log/nexus-delay-tailscaled.log
tail -30 /opt/homebrew/var/log/nexus-reconcile.log
```

通過的條件是對帳 log 出現這兩行：

```
recreating: <三個服務，順序不固定>
OK: all bindings restored
```

**服務的順序不要當成驗收字串。** 它來自 `docker compose ps -q` 的回傳順序，不是寫死的：
這裡原本寫著 `recreating: gateway admin-public frontend-public`，而實測跑出來的是
`recreating: admin-public frontend-public gateway`。要看的是「那三個服務都在」和下一行的
`OK`。

那就是第二種結果，**表上空了七次開機的那一格**。接著把 §1.1 的完整檢查跑一遍確認平台真的
回來了：九個服務、六個 binding requested 與 actual 相符、**六個**入口 200（不是三個——
tailnet 那三個是壞掉的那三個，但 loopback 那三個也要確認注入沒有波及它們）。

**要看注入真的讓 Docker 綁失敗了，去 Docker 的 backend log 找，而且一定要用 glob：**

```sh
grep -a "can't assign requested address" \
  ~/Library/Containers/com.docker.docker/Data/log/host/com.docker.backend.log*
```

**那個 `*` 是必要的。** Docker 會自己輪替那個檔，而且輪替得很勤：2026-07-26 那次注入的三條
證據落在 `com.docker.backend.log.20260726-210850.988` 裡，因為 Docker 在 21:08:50 輪替過，
而檢查是 21:09 跑的——**只 grep `com.docker.backend.log` 會得到空的結果，然後被讀成「這件
事沒發生」**。這個陷阱在同一天咬過兩次（另一次是 20:12:32 那個輪替），兩次都是同一種誤讀：
一個範圍比它看起來小的檢查。

**然後確認清乾淨了**，這一項不能跳：

```sh
ls -l /Library/LaunchDaemons/online.rcsl.delay-tailscaled-once.plist   # 要是 No such file
```

腳本會自己刪掉它。如果它還在，手動 `sudo rm` 掉——留著的話每次開機都會把機器踢下線 90 秒。

---

**實測記錄（2026-07-26 21:02，第八次開機）：通過。表上空了七次開機的那一格填上了。**

先跑了一次事前確認，因為這一節的救援指令值得在還沒有依賴它的時候先驗一次：手動
`bootout` 再 `bootstrap` `tailscaled`，位址消失、再出現，三個 tailnet 入口回到 200。
（那次重啟順帶推翻了 §1.1 的 netmap 快取模型，見上面那一段——這是完全沒有預期的收穫。）

裝上 plist、`sudo reboot`，機器 21:02:36 起來，時間軸：

| 時刻 | 事件 |
|---|---|
| 21:02:43 | plist 自刪、hold 開始 |
| **21:02:56** | **Docker 三條 `can't assign requested address`：`:3001`、`:8000`、`:8002`** |
| 21:04:13 | hold 結束、釋放，`tailscaled` 起、讀到快取 |
| 21:04:14 | 位址上線（reconciler 看到的時間） |
| 21:04:42 | 具名清單判定齊全 |
| 21:04:58 / 21:05:10 / 21:05:22 | 三條 `dropped binding` |
| 21:05:22 | `recreating: admin-public frontend-public gateway` |
| **21:05:31** | **`OK: all bindings restored`** |

**餘裕 −78 秒**（Docker 21:02:56 綁，位址 21:04:14 才在），對照自然開機 +1.3 秒的天花板。
綁失敗的正是預期的那三個服務，一個不多一個不少。事後完整檢查：九個服務 running、`migrate`
`Exited (0)`、六個 binding requested 與 actual 相符、六個入口全 200、Ollama loopback 200
而 tailnet `000`、plist 已自刪。

**四件沒有預期到的事，記在這裡因為它們是這次唯一的新測量：**

- **具名清單那個前置條件花了 27 秒**（21:04:15→21:04:42），而前四次自然開機都是穩定的
  16 秒。「它的成本是穩定的」這句話只在健康的開機上成立。
- **binding 掃描花了 40 秒**（21:04:42→21:05:22），三條 `dropped binding` 每條間隔 12 秒。
  `broken_services()` 裡沒有任何 sleep，所以那 40 秒全是 `docker inspect` 在開機當下的真實
  成本——健康的開機上同一個掃描是在同一秒內完成的。修復總共 77 秒，其中一半以上是在「看」，
  不是在「修」。
- **監測沒有寄信，而那是對的。** 21:02:56 到 21:05:31 這 2 分 35 秒平台是真的壞的（三個
  binding 掉了、三個 tailnet 入口不通），而 boot grace 把它整段蓋住了，`nexus-health.log`
  沒有新增任何一行。**這是那個 grace 第一次真的擋下一封該擋的信**——在 20:45 修掉那個貪婪
  `sed` 之前它一次都沒生效過，而在那之後也一直沒有壞掉的開機可以測它。順帶：如果
  reconciler 沒修好，21:07:43 那次排程觸發就會抓到並寄信，最壞情況的偵測延遲是十分鐘。
- **注入腳本自己報錯了一個數字，已經修掉。** 它印的是
  `tailnet address ... is back within 10s of the release`，而 reconciler 獨立看到位址是在
  釋放後 **1 秒**。原因是它印的是迴圈計數乘以 5，把「檢查之後」的那次 sleep 算到了檢查
  頭上——5 秒的 off-by-one 加上 5 秒的取樣粒度。一個唯一工作就是量東西的工具，在唯一
  一行是數字的地方報錯，正是這份文件一路在抓的同一種缺陷。現在改成量實際經過的秒數、
  每秒取樣一次，兩條路徑（位址在／位址不在）都實跑驗過。

**這一次注入證明什麼、不證明什麼。** 它證明 reconciler 在**開機那個所有東西同時在動的
環境裡**能偵測到掉掉的 binding 並修回來——那正是手測補不上的部分。它不證明「那個競態會
自己發生」，那件事 16:45 已經證明過了。它也不證明容器拉起路徑（第三種結果），那一格要
靠 §1.1b 的另一種注入——**這一節的注入逼不出它**，因為它壓的是位址，不是 Docker Desktop
還原容器的能力。

---

### 1.1b 故障注入：把容器拉起路徑逼出來（不用人在現場）

> **這一節跑過了，2026-07-26 21:51，一次就通過。** 下面前半段是當時的動機與做法，寫在還沒
> 跑之前，語氣維持原樣；結果與實測數字在本節末的「實測記錄」。要重跑（改過 reconciler、換過
> Docker Desktop 版本）就照原步驟，它是可以重複跑的，而且比 §1.1a 便宜得多。

§1.1a 填掉了第二種結果，第三種還是空白：`docker did not restore the stack; bringing it up`
→ `stack up: all expected services running`。這一格只有 19:09 那次開機產生過，而**那次是人
手救的**，reconciler 還來不及做。

**這一節原本寫的是「只能靠第二輪重跑」，那是錯的。** 第三種結果也能注入，而且比 §1.1a
便宜得多。

**做法**：把整個 stack 停掉，然後重開機。機制就寫在 `docker-compose.yml` 裡——八個長期服務
都是 `restart: unless-stopped`，而 **`unless` 就是全部的重點：被明確 stop 的容器，在 daemon
回來時不會被拉起來。** 所以下一次開機時 Docker Desktop 面對九個它刻意不還原的容器，而
reconciler 遇到的狀態和 19:09 那次留給它的一模一樣：`docker compose ps --services --status
running` 是空的、東西都在、沒有一個在跑。

**風險比 §1.1a 小一個數量級，這是它的主要優點：**

| | §1.1a（位址注入） | §1.1b（容器注入） |
|---|---|---|
| 機器在 tailnet 上 | **90 秒完全離線** | 全程在線 |
| 人要在現場 | **必須** | **不用**，可以遠端做 |
| 出事時 | 只能走過去 | 從任何地方 `docker compose up -d` |

代價是平台從執行腳本到下一次開機復原完成為止是停的（實測 §1.1a 那次是開機後約 3 分鐘），
所以挑一個沒有人在用的時間。

**它也沒有 plist，而且不該有。** §1.1a 需要 plist 是因為它的故障必須在**開機當下**注入；
這個故障是在重開之前就設好的，會自己撐過重開，所以開機時再擺一個會動的東西進去，只是多
一個沒事做的零件。

**步驟**（`launchd/stop-stack-once.sh` 在 repo 裡，平常不執行）：

```sh
cd ~/dev/RCSL-AI-Nexus
./launchd/stop-stack-once.sh
```

**它會先拒絕再動手。** 五個前置條件任何一個不成立，它什麼都不改就 exit 1：

- §1.1a 的 plist 還裝著（兩個注入同時來，兩邊的救援路徑會互相擋住）
- 九個服務沒有全部在跑（從壞的平台開始測復原，回不來的時候分不出是誰造成的）
- 有 binding requested 但沒 actual（那是 §1.1a 的狀態，先修那個）
- reconciler 的 plist 不在
- **`nexus-reconcile.log` 裡最新的 `reconcile starting` 比這次開機還舊**

最後那一項是最重要的，而且刻意不是「plist 檔案在不在」。**檔案在只是必要條件，它不證明
launchd 真的載入了那個 job**——而「停掉 stack 重開、卻沒有東西會把它拉起來」正是這個注入
變成停機事故的唯一途徑。log 回答的是真正該問的問題：這個 daemon 在**這一次開機**跑過嗎。
那是證據，不是設定。

前置條件過了之後它會把 pre-state 記下來（六個 requested binding），停掉 stack，**再讀回來
確認九個都真的停了**——半停的 stack 是這裡最糟的結果，Docker 會還原還在跑的那些，reconciler
會遇到一個既不空也不完整的集合，下一次開機印出來的東西會是在講一個沒有人設計過的故障。

然後：

```sh
sudo reboot
```

**停掉之後盡快重開，因為監測沒有在保護那一段。** 停完到重開之間平台是真的壞的，而 boot
grace 只蓋開機之後；健康檢查每 300 秒跑一次，那一槍打在哪裡純粹看你在間隔的哪個位置執行
腳本。落在檢查前面就會收到一封 `failing`，**那封信是對的，平台當時就是壞的，不是測試出
問題**。2026-07-26 那次沒有收到，是因為上一次檢查在 21:47:43、下一次要到 21:52:43，而機器
21:51:23 就重開了——運氣，不是設計。

**不要碰它，等三到五分鐘**，然後：

```sh
tail -40 /opt/homebrew/var/log/nexus-reconcile.log
```

通過的條件是依序出現這四行：

```
not running: <九個>
docker did not restore the stack; bringing it up
stack up: all expected services running
all published bindings intact
```

那就是第三種結果。接著跑 §1.1 的完整檢查：九個服務、六個 binding requested 與 actual 相符、
六個入口 200。

**最後一行會是 `all published bindings intact` 而不是 `OK: all bindings restored`，這是對的。**
reconciler 的第一個前置條件就是等位址上介面，所以它跑 `up -d` 的時候位址早就在了，轉發會
在那時候正確建立。這個注入產生的是第三種結果，不會順便產生第二種——**兩種注入各測一條路，
不能互相替代。**

**這一次注入證明什麼、不證明什麼。** 它證明 reconciler 在開機那個所有東西同時在動的環境裡
能把整個平台拉起來——手測補不上的正是這部分，而 §1.1a 已經量出那個差別有多大（同一段程式
碼判定花 27 秒對 16 秒、掃描 40 秒對不到 1 秒）。它**不證明** Docker Desktop 的還原會自己
失敗：那件事只發生過一次（19:10，26.5.2 更新之後），原因至今未明。**它重現的是狀態，不是
原因**——跟 §1.1a 一模一樣的限制。

**而它不能取代第二輪。** 第二輪測的是整個系統更新重開：自動登入有沒有被重置、`pmset
autorestart` 還在不在、Docker Desktop 在更新重開後會怎麼做。§1.1b 只餵給 reconciler 一個
狀態，那三件事一件都沒碰到。

---

**實測記錄（2026-07-26 21:51，第九次開機）：通過。表上第三種結果那一格填上了。**

腳本一個前置條件都沒有拒絕：九個服務在跑、六個 binding requested 與 actual 相符、§1.1a 的
plist 已經自刪、reconciler 的 plist 在，而且**最後那一項讀對了**——它印出上一次開機的
`reconcile starting` 是 21:02:43、開機後 7 秒，那正是 §1.1a 那次的 reconciler。停完之後讀回
來確認九個都停了，然後人手 `sudo reboot`。

| 時刻 | 事件 |
|---|---|
| 21:50:37 | 前置條件通過、記下 pre-state |
| 21:50:38 | 九個服務停掉，讀回確認 |
| 21:51:23 | 開機（`kern.boottime`） |
| 21:51:30 | `reconcile starting`——開機後 7 秒，和 §1.1a 一樣 |
| 21:51:41 | 位址真的上線（`tailscaled` 的 log：`peerapi` 綁在 100.108.250.62 上）——**+11 秒** |
| 21:51:45 | reconciler 看到位址（它每 5 秒取樣，所以它記的是 15 秒，不是 11 秒） |
| 21:51:46 | `docker daemon responding` |
| **21:52:01** | **`not running:` 九個 → `docker did not restore the stack; bringing it up`** |
| **21:52:14** | **`stack up: all expected services running` → `all published bindings intact`** |

**開機到復原 51 秒**，腳本到復原（真正的停機窗）1 分 36 秒。§1.1a 那次是開機後 2 分 55 秒。

四行照預期的順序出來，沒有多出別的。事後完整檢查通過：九個服務 running、`migrate`
`Exited (0)`、六個 binding requested 與 actual 相符、六個入口 200。

**Docker Desktop 一個都沒有還原，而這正是這個測試賴以成立的機制。** `restart: unless-stopped`
一直是這樣承諾的，compose 檔也一直這樣寫，但在這之前沒有東西看過那個 `unless` 真的撐過一次
重開機。它撐過了，而且是完全的：missing 的集合第一次取樣是九個，最後一次也是九個。

**三個新測量，都是在回答 §1.1a 留下的問題：**

- **settle 迴圈跑在它的結構下限，15 秒。** 那是四次取樣、中間三次 5 秒 sleep，是這個迴圈在
  還是這個迴圈的前提下最短的可能。§1.1a 同一段程式碼花了 27 秒、健康開機是 16 秒，當時留下
  的問題是「這個迴圈在開機時是不是很貴」。答案是不貴：**貴的是在所有東西同時在動的時候去
  inspect 一個正在跑的 stack**，對著空的 stack 那四次 `docker compose ps` 量不出成本。同一個
  對比也出現在掃描上——§1.1a 是 40 秒，這次根本沒有，因為沒有正在跑的容器可以掃。
- **reconciler 花的 44 秒裡，31 秒在等、13 秒在做事**：等位址 15 秒（它自己的帳；位址其實
  11 秒就上來了，差的 4 秒是取樣粒度）、等 daemon 1 秒、settle 15 秒、`up -d` 13 秒。那 13 秒把九個服務從零帶到全部在跑，中間還包含 postgres 的健康閘門和
  `migrate` 跑完退出。這條路唯一一次手測是 16 秒（停掉 `grafana` 再手跑），而那 16 秒幾乎全是
  settle 迴圈——**手測從來沒有量到的就是那 13 秒**。
- **最後一行是 `all published bindings intact` 而不是 `OK: all bindings restored`，跟跑之前
  寫的一樣。** Docker backend log 裡這次開機沒有任何 `can't assign requested address`（用
  glob 查過，最新的三條還是 §1.1a 21:02:56 那組），因為 reconciler 第一個前置條件就是等位址，
  等到 `up -d` 跑的時候位址已經在介面上 16 秒了，轉發第一次就建對。**兩種注入各測一條路，這
  一次是那句話的證據，不再只是主張。**

**這次注入順帶推翻了一個跟它無關的數字，而且是最有價值的收穫。** 它壓的是 Docker 那一側，
`tailscaled` 是自然開機起來的，所以位址那一欄是一筆乾淨的自然開機觀測——**11 秒，不是 9 秒**，
而 §1.1「快取不會接續」那一段的算式假設 9 秒是常數。完整的更正在那一節；結論（不要靠重開機
碰運氣）沒有變，變的是理由。**一次注入只污染它壓住的那一側**，這件事事前沒有想到。

**監測沒有寄信，但只有一半是設計。** boot grace 蓋住 21:51:23–21:55:23，`RunAtLoad` 那次被
壓下去，而 51 秒的復原整個落在裡面；第一次真的檢查是 21:56:30，那也是 reconciler 萬一失敗
時的最壞偵測延遲——**約五分鐘，不是 §1.1a 講的十分鐘**，因為 240 秒的 grace 對上 300 秒的
間隔剛好只壓掉一次。但停完到重開之間平台也壞了 45 秒，那一段沒有任何東西在保護，只是排程
剛好落在外面（上面「停掉之後盡快重開」那一段是這件事的完整說明）。

**一個順帶確認的東西，寫在這裡因為它很容易被讀反。** 完整檢查第一次是 21:53:29 手跑的，開機
才 126 秒，它 exit 0 **而且什麼都沒檢查**——走的是 boot grace 那條路、只把 state 檔重寫掉，
那正是那條路存在的目的。21:56:35 在 grace 外面重跑一次，那次才是通過的那次。**grace 窗裡的
`exit 0` 不是關於平台的證據**，這正好也是 §7 那個「state 檔 mtime 在五分鐘內」判準能在開機
後立刻讀的原因。

---

## 為什麼「人要在現場」這件事沒有替代方案

Mac Studio 沒有 out-of-band 管理（沒有 IPMI/iDRAC 那類獨立於作業系統的遠端主控台）。
所以任何可能讓機器開不起來、或停在需要人操作的畫面的變更，都是單向門：出事了就只能走
過去。這一類至少包含 FileVault 開關、自動登入設定、系統大版本升級、以及任何會影響
`tailscaled` 啟動的改動。

反過來說，**不影響開機的事情都可以安心遠端做**：程式開發、平台管理、容器操作、ACL 與
成員變更。分界線是「這個動作會不會影響下一次開機」。

- [ ] 啟動安全維持 Full Security，確認進 recoveryOS 需要管理員密碼。FileVault 關著的期間，
  這是擋住「從外接媒體開機」的主要控制而不是次要的。機器放在能上鎖的地方。

- [x] 斷電後自動重新啟動：系統設定 > 節能。跳電恢復後機器要自己開機。

  **2026-07-26 查出來是關的，當天開起來的**——這一項在清單上放了很久沒有人量過它。
  沒有 out-of-band 管理的機器加上 `autorestart 0`，等於跳一次電就要有人走過去按電源鍵，
  而那是這台機器唯一一個「完全遠端」會被物理事件切斷、又能用一行指令補掉的缺口：

  ```sh
  sudo pmset -a autorestart 1
  pmset -g | grep autorestart      # 要看到 autorestart 1
  ```

  （同一條指令會把 `autorestartatconnect` 一起改成 0。那個鍵是給筆電接上電源用的，
  桌機上沒有作用，記在這裡只是因為量到了。）

- [x] 遠端登入 (SSH)：**保持關閉**，第 4 部分改用 Tailscale SSH。

  **這一項原本寫的是「拔掉螢幕之前一定要先開，否則沒有救援管道」，那和 §11 的決定相反。**
  macOS 的遠端登入綁在所有介面（含區網）而且接受密碼登入；Tailscale SSH 只在 tailnet
  介面上服務、沒有密碼或金鑰可外洩、身分來自 tailnet，並且由 §3.4 ACL 的 `ssh` block 管、
  `action: check` 每 12 小時強制重認證。所以「只監聽 Tailscale 介面」這個要求不是靠改
  `sshd_config` 達成的，是靠**不跑第二個 SSH server**——見
  [security.md](../architecture/security.md) §11 與下面第 4 部分那兩項。

  **舊的寫法有一個真的顧慮，解法是順序而不是開它**：第 1 部分做完的時候 Tailscale 還沒
  裝，這時候拔螢幕確實沒有路可以進去。所以**螢幕不要在第 4 部分的 Tailscale SSH 實際連
  過一次之前拔掉**，而不是先開一個之後要關掉的 sshd。

  驗證條件（2026-07-26 量過，成立）：`127.0.0.1:22` 沒有任何東西在聽，而 tailnet 的 SSH
  仍然連得進去。Tailscale SSH 不綁 loopback，所以 loopback 的靜默正好證明停掉的是系統
  那個 daemon：

  ```sh
  lsof -nP -iTCP -sTCP:LISTEN | grep ':22 '          # 要沒有輸出
  launchctl print-disabled system | grep openssh     # 要是 => disabled
  ```

---

## 2. 裝好基本工具

- [ ] 安裝 Xcode 命令列工具（含 git）：

  ```sh
  xcode-select --install
  ```

- [ ] 安裝 Homebrew（macOS 的套件管理器）。到 https://brew.sh 複製官方指令執行，裝完
  照畫面提示把 `brew` 加進 PATH（通常是把一行 `eval ...` 加進 `~/.zprofile`）。驗證：

  ```sh
  brew --version
  ```

- [ ] 用 brew 安裝需要的東西：

  ```sh
  brew install git tailscale ollama
  brew install --cask docker      # Docker Desktop，內含 docker compose
  ```

- [ ] 啟動 Docker Desktop（第一次要打開 App 並同意授權），然後在
  Docker Desktop > Settings > General 勾選「登入時自動啟動」。驗證：

  ```sh
  docker compose version
  ```

模型 runtime（Ollama）刻意**不放進 Docker**：macOS 上的容器碰不到 Apple GPU，
容器化的 Ollama 只會退回 CPU。所以 Ollama 原生跑，容器透過 `host.docker.internal`
連它。

---

## 3. 設定 Ollama（原生、只聽 127.0.0.1）

Ollama 預設會聽所有介面 (`0.0.0.0:11434`)。要把它綁回本機，只讓同一台的容器連。

- [ ] 先手動跑通、拉一個模型測試（在一個終端機視窗）：

  ```sh
  OLLAMA_HOST=127.0.0.1 ollama serve      # 這個視窗保持開著
  ```

  另開一個終端機視窗：

  ```sh
  ollama pull qwen2.5:7b
  ollama run qwen2.5:7b "說一句話"
  ```

- [ ] 設定成開機自動啟動、掛掉自動重啟。**不要用 `brew services start ollama`**，
  用 repo 裡的 [`launchd/online.rcsl.ollama.plist`](../../launchd/online.rcsl.ollama.plist)：

  ```sh
  sudo cp launchd/online.rcsl.ollama.plist /Library/LaunchDaemons/
  sudo chown root:wheel /Library/LaunchDaemons/online.rcsl.ollama.plist
  sudo chmod 644 /Library/LaunchDaemons/online.rcsl.ollama.plist
  sudo launchctl bootstrap system /Library/LaunchDaemons/online.rcsl.ollama.plist
  ```

  Homebrew 的做法在這台機器上有兩個問題，其中一個是靜默的安全失效：

  - **`launchctl setenv OLLAMA_HOST 127.0.0.1` 不會跨重開機存活。** 它寫的是
    launchd 的 boot session domain。重開機後變數消失，而 Homebrew 的 plist 裡
    沒有 `OLLAMA_HOST`，Ollama 就退回預設的 `0.0.0.0:11434`——推論端點對整個
    區網敞開，而且沒有任何跡象。security.md §7.1 要求的 loopback 綁定必須自己
    能撐過重開機，所以值要寫死在 plist 裡。
  - **不加 sudo 的 `brew services` 是 LaunchAgent，要登入才啟動。** 這台無頭
    運作，跳電重開後不會有人登入（FileVault 開著時更不可能），Ollama 就不會
    回來，gateway 只會一直回「no available model」。所以是 LaunchDaemon。

  plist 裡 `UserName` 設成操作者帳號而不是留給 root：daemon 預設以 root 執行，
  會去找 `/var/root/.ollama` 而看不到已經拉好的模型。

- [ ] 驗證（三件事都要對）：

  ```sh
  lsof -nP -iTCP:11434 -sTCP:LISTEN   # 只能有 127.0.0.1，不能有 * 或 0.0.0.0
  launchctl getenv OLLAMA_HOST        # 要是空的：綁定來自 plist 而非 session
  ollama list                         # 模型看得到 = 執行身分對
  ```

  再從容器打一次，確認 §0.1 的前提成立：

  ```sh
  docker run --rm alpine:3 sh -c 'apk add -q curl; curl -s http://host.docker.internal:11434/api/tags'
  ```

- [ ] （之後的硬化，非首次上線必須）改用一個專用、非管理員的服務帳號來跑 Ollama，
  模型目錄只給該帳號寫入。細節見 [security.md](../architecture/security.md) §7.1(d)。
  第一次先跑通，這項可列為後續。

---

## 4. Tailscale（tailnet）

- [ ] 先啟動 `tailscaled`。`brew install tailscale` 只裝了 CLI 和 daemon，沒有啟動它，
  少了這步下一行會直接回 `failed to connect to local Tailscale service`：

  ```sh
  sudo brew services start tailscale
  ```

  這裡的 `sudo` 是必要的而不是順手加的：加了才會註冊成系統層級的 LaunchDaemon，
  開機就起、不需要有人登入；不加就是使用者層級的 LaunchAgent，跳電重開後在沒人
  登入之前整條 tailnet 都是斷的。和上一節 Ollama 是同一個道理。

- [ ] 登入並加入 tailnet：

  ```sh
  sudo tailscale up
  ```

  照終端機給的連結用瀏覽器登入。

- [ ] **套用 ACL。這步不能跳過，也不能延後。** 新 tailnet 的預設政策是
  `{"src": ["*"], "dst": ["*"], "ip": ["*"]}`——全放行。在那之下，任何加入 tailnet 的
  裝置都能直接連 `100.x.y.z:8000` 和 `:8002`，繞過 proxy 上的每一道控制
  （[security.md](../architecture/security.md) §3.4 開頭警告的就是這件事）。政策範本在
  §3.4，把 `group:ai-admin` 換成你的登入身分後，貼到
  https://login.tailscale.com/admin/acls/file 存檔。

  順序是有意義的：`tagOwners` 必須先存在，下一步的 tag 才打得上去，第 8 部分請 NTNU
  管理員打 `tag:ntnu-proxy` 也才會成功。先打 tag 再套 ACL 會失敗。

- [ ] 給這台打上 `tag:ai-server`。§3.4 的規則全部掛在這個 tag 上，沒有 tag 就一條都
  不會套用：

  ```sh
  sudo tailscale up --advertise-tags=tag:ai-server
  ```

  會再要一次瀏覽器確認，因為 tag 把裝置擁有權從你個人轉移到 tag。附帶好處是 tagged
  裝置預設沒有金鑰過期；個人裝置預設 180 天過期，一台 24/7 伺服器的 tailnet 連線在
  半年後自己斷掉是很難查的故障。

  驗證：

  ```sh
  tailscale status --json | grep -A2 '"Tags"'    # 要看到 tag:ai-server
  ```

- [ ] 取得這台的 tailnet IP（`100.x.y.z`），記下來，第 6 部分的 `TAILNET_IP` 要用：

  ```sh
  tailscale ip -4
  ```

- [ ] 記下這台的 MagicDNS 名稱（形如 `mac-studio.你的tailnet.ts.net`），tailnet 管理
  入口的網址會用到。

- [ ] 設定 tailnet 入口的 `tailscale serve`，把 HTTPS 導到本機的前端 (`127.0.0.1:3000`)。
  這一步會讓 `tailscale serve` 幫每個請求注入 `Tailscale-User-Login` 身分標頭，這正是
  tailnet 入口信任的來源：

  ```sh
  tailscale serve --bg 3000
  ```

  不同 tailscale 版本語法略有差異，用 `tailscale serve --help` 確認；目標是
  `https://<你的主機>.ts.net/` 轉到 `http://127.0.0.1:3000`。

- [ ]（選配）要從 tailnet 看 Grafana 儀表板，把它的本機埠也 serve 出去。Grafana 只綁
  在 `127.0.0.1:3002`，Prometheus 完全不對外：

  ```sh
  tailscale serve --bg --https 8443 http://127.0.0.1:3002
  ```

  之後在同一 tailnet 上開 `https://<你的主機>.ts.net:8443`，用 admin 加
  `grafana_admin_password` 登入。

- [ ] **遠端存取：用 Tailscale SSH，不要用 macOS 的「遠端登入」。** 這台無頭運作，
  你需要一條能進去做維護和開發的路。伺服器端一行：

  ```sh
  sudo tailscale up --ssh --advertise-tags=tag:ai-server
  ```

  `--advertise-tags` 一定要一起帶。tag 若是先前用 API 打上去的，本機 prefs 裡不會有
  記錄，單獨跑 `tailscale up --ssh` 有可能把 tag 弄掉——而 tag 一掉，§3.4 的 ACL 全部
  失效，變回全放行。

  之後從**另一台在同一 tailnet 上、且屬於 `group:ai-admin` 的裝置**連：

  ```sh
  ssh <你的帳號>@<伺服器的 100.x.y.z>
  ```

  第一次會跳出瀏覽器要你確認身分（ACL 的 `action: check`，之後 12 小時內免確認）。
  **不會問密碼、也不需要金鑰。**

- [ ] 連得上之後，**把系統的「遠端登入」關掉**：系統設定 > 一般 > 共享 > 遠端登入。

  macOS 的遠端登入綁在所有介面（含區網）且接受密碼登入，Tailscale SSH 則只在 tailnet
  介面上服務。兩個都開等於白留一個攻擊面。關掉之後不用改任何 `sshd_config`，就滿足了
  [security.md](../architecture/security.md) §11「只監聽 Tailscale 介面」的要求。

  **關的時候不要關掉你當下那個 session。** 關完先開新視窗重連一次確認還進得去，再關舊
  的——這是不把自己鎖在無頭機器外面的標準做法。驗證方式：

  ```sh
  nc -z -w2 127.0.0.1 22 && echo "系統 sshd 還開著" || echo "已關閉"
  ```

  Tailscale SSH 不綁 loopback，所以 loopback 沒有回應，正好證明停掉的是系統那個。

### Tailscale SSH 連不上時，先看是哪一半沒設

它需要兩個東西同時成立，而兩者失敗的樣子不一樣：

| 症狀 | 缺的是 |
|---|---|
| `tailnet policy does not permit you to SSH to this node` | ACL 的 `ssh` 區塊。連線有到、授權沒過 |
| 連線逾時、`TcpTestSucceeded : False` | `acls` 裡沒有 port 22。根本沒到伺服器 |

兩者都缺會表現成後者。判斷方法是在伺服器上看
`tail -f /opt/homebrew/var/log/tailscaled.log | grep ssh-conn`：**有 `handling conn`
就代表連線到了伺服器**，那問題在授權；完全沒有新行，問題在網路層或客戶端。

（順帶一提，Tailscale SSH 在 macOS 上是可以當伺服器用的。判斷它「有沒有啟動」不要去看
`tailscale status --json` 裡的主機金鑰欄位——那個欄位不存在，怎麼查都會是空的。要看
`tailscale debug prefs` 的 `RunSSH`。）

---

## 5. GeoLite2 國別資料庫（不放會起不來）

Production 下 country filter 找不到這個檔會**拒絕啟動**（這是刻意的 fail-closed，
避免默默放行全世界）。

- [ ] 到 MaxMind (https://www.maxmind.com) 註冊免費帳號，建立一組 License Key。
- [ ] 下載 **GeoLite2 Country**（`.mmdb` 格式）。
- [ ] 在專案目錄底下建 `data/`，把檔案放成 `data/GeoLite2-Country.mmdb`。compose 會把
  `./data` 唯讀掛進 gateway 與 admin 容器。

---

## 6. 取得專案並設定

- [ ] 取得程式碼（用你的 git 遠端位址）：

  ```sh
  git clone <repo-url>
  cd RCSL-AI-Nexus
  ```

- [ ] 建立 `.env`（只放非機密設定）：

  ```sh
  cp .env.example .env
  ```

  編輯這幾項，其餘保留預設：

  | 變數 | 值 |
  |---|---|
  | `ENV` | `production` |
  | `AUTH_MODE` | `tailnet`（見下方註）|
  | `TAILNET_IP` | 第 4 步取得的 `100.x.y.z` |
  | `PROXY_HOSTNAME` | `api.nexus.rcsl.online` |
  | `ADMIN_BASE_URL` | `https://ai.nexus.rcsl.online` |
  | `NODE_TOTAL_MEMORY_GB` | `64`（要對上這台的實際記憶體）|
  | `ALLOWED_COUNTRIES` | `TW,AU` |
  | `BOOTSTRAP_ADMIN_LOGIN` | 你的 Tailscale 登入身分（通常是 email）|

  `COOKIE_SECURE` 保持 `true`、`CACHE_BACKEND` 保持 `redis`。

  註：兩個管理入口各自用自己的信任模型（tailnet 信任身分標頭、public 要求密碼+TOTP），
  這由兩個獨立的服務決定，**不是**由 `AUTH_MODE` 決定。`AUTH_MODE` 在 production 主要
  影響國別過濾與前端的 401 提示。設成非 `dev` 即可（`dev` 在 `ENV=production` 會直接
  拒絕啟動）。第 9 部分會實測確認公開入口仍要求密碼+TOTP。

- [ ] 建立 secrets。每個檔一個純值、**不要有尾端換行**。詳見
  [secrets/README.md](../../secrets/README.md)。

  ```sh
  for f in secrets/*.example; do cp -n "$f" "${f%.example}"; done
  openssl rand -base64 32        # 每個密碼與加密金鑰各產一個，跑多次
  ```

  三個資料庫 URL（帳號名固定，必須小寫）：

  ```
  secrets/owner_database_url    postgresql+asyncpg://nexus:<OWNER_PW>@postgres:5432/nexus
  secrets/gateway_database_url  postgresql+asyncpg://nexus_gateway:<GW_PW>@postgres:5432/nexus
  secrets/admin_database_url    postgresql+asyncpg://nexus_admin:<ADMIN_PW>@postgres:5432/nexus
  ```

  其餘：

  - `secrets/postgres_password`：**必須等於** owner URL 裡的 `<OWNER_PW>`
  - `secrets/redis_password`、`api_key_pepper`、`totp_encryption_key`、
    `session_signing_key`：各一個 `openssl rand -base64 32`
  - `secrets/proxy_shared_secret`：要跟 NTNU proxy 送的 `X-Nexus-Proxy` 一致，
    跟管理員對齊同一個值
  - `secrets/metrics_scrape_token`：`/metrics` 的 bearer token，一個
    `openssl rand -base64 32` 即可。同一個檔會掛給 Prometheus，兩邊自動一致。若把
    `METRICS_ENABLED` 設成 `false` 就不需要這個
  - `secrets/grafana_admin_password`：Grafana 首次登入的 admin 密碼

  寫檔避免尾端換行的寫法：

  ```sh
  printf '%s' '你的值' > secrets/redis_password
  ```

  注意：帳號名與資料庫名必須小寫 `[a-z_][a-z0-9_]*`；密碼若含 `@ : / #` 要在 URL 裡
  percent-encode（例如 `@` 寫成 `%40`）。

---

## 7. 啟動與驗證

- [ ] 建置並啟動：

  ```sh
  docker compose build
  docker compose up -d
  docker compose ps
  ```

- [ ] 確認 `migrate` 顯示 `exited (0)`。它負責建立三個資料庫帳號並套用授權。若不是 0，
  **先看它的 log**（應用服務都在等它）：

  ```sh
  docker compose logs migrate
  ```

- [ ] **確認六個 port 真的綁上了。** 這一步不能只看 `docker compose ps` 顯示 `Up`——
  容器可以健康地跑著、而 port 一個都沒綁。判準是 `PortBindings`（要求）和 `Ports`
  （實際）要一致，實際那邊是 `[]` 就是掉了：

  ```sh
  for c in $(docker compose ps -q); do
    printf '%-38s %s\n' "$(docker inspect $c --format '{{.Name}}')" \
      "$(docker inspect $c --format '{{json .NetworkSettings.Ports}}')"
  done
  ```

  應該看到 gateway `TAILNET_IP:8000`、admin-public `:8002`、frontend-public `:3001`、
  admin-tailnet `127.0.0.1:8001`、frontend-tailnet `127.0.0.1:3000`、grafana
  `127.0.0.1:3002`。postgres／redis／prometheus 顯示 `null` 是對的，它們本來就不發布。

- [ ] **裝開機對帳的 LaunchDaemon。** Docker Desktop 開機時會在 `tailscaled` 把位址掛上
  `utun0` 之前就還原容器，那些指名 tailnet 位址的 port forward 於是綁失敗，而它
  **只記一行 warning、不重試**。容器照樣 running、healthy，`restart: unless-stopped`
  因為沒有東西退出所以永遠不觸發——服務從 tailnet 消失，沒有任何東西會說。

  ```sh
  sudo install -o root -g wheel -m 644 \
    launchd/online.rcsl.reconcile-port-bindings.plist /Library/LaunchDaemons/
  sudo launchctl load -w /Library/LaunchDaemons/online.rcsl.reconcile-port-bindings.plist
  ```

  它等 `utun0` 有位址、docker 有回應（最多十分鐘），然後只對「要求了 binding 卻沒拿到」
  的容器跑 `--force-recreate`，跑完再驗一次。**一定要 `--force-recreate`：** forward 是
  容器*建立*時產生的，`docker compose up -d` 對已在跑且設定相符的容器是 no-op，
  `docker compose restart` 沿用同一個容器、不會動到後端的轉發表。這兩個在這台機器上都
  試過，都沒有恢復任何一個 binding。

  對帳結果看這裡（它刻意不無限重試，修不好的東西要人看，不是一直重建）：

  ```sh
  tail -20 /opt/homebrew/var/log/nexus-reconcile.log
  ```

- [ ] **裝健康監測的 LaunchDaemon（狀態變了會寄信）。** 上面那個 daemon 修的是開機那一
  刻。它修不好、或者它自己沒跑的時候，狀態會跟 2026-07-26 那次一模一樣：容器 running、
  gateway healthy、平台從 tailnet 打不到，而**沒有任何東西會說**。那次是靠人坐下來讀四份
  log 才發現的，那不是可以依賴的偵測方式。

  先準備寄件帳號。**建議另開一個專用 Gmail 帳號當寄件者，不要用你自己的那個。** app
  password 會以明文放在 `secrets/` 底下，而這台機器的 FileVault 是關的（security.md
  §15.6）；用自己的帳號等於把「收所有服務密碼重設信」的信箱鑰匙放進去，而
  `leolove3very@gmail.com` 同時還是平台的第一個管理員。專用帳號被拿走，最多是有人能冒名
  寄信。收件位址不是 secret，寫在腳本的 `ALERT_TO`，放著讓人 review。

  在**寄件**帳號上：Google 帳號 → 安全性 → 兩步驟驗證（必須先開）→ 應用程式密碼，產生
  一組 16 碼。然後：

  ```sh
  printf '%s' 'nexus-alerts@gmail.com' > secrets/alert_smtp_account
  printf '%s' 'xxxxxxxxxxxxxxxx'       > secrets/alert_smtp_password
  chmod 600 secrets/alert_smtp_account secrets/alert_smtp_password
  bash launchd/check-platform-health.sh     # 先手動跑，確認信真的寄得出去
  ```

  ```sh
  sudo install -o root -g wheel -m 644 \
    launchd/online.rcsl.health-check.plist /Library/LaunchDaemons/
  sudo launchctl load -w /Library/LaunchDaemons/online.rcsl.health-check.plist
  ```

  **改 plist 之後一定要重裝＋重載，改腳本不用。** plist 上的 `ProgramArguments` 指向工作樹
  裡的 `.sh`，所以腳本一存檔下次執行就是新的；但 `/Library/LaunchDaemons/` 裡那份 plist 是
  **複本**，repo 裡改了不會自動生效。這三個 daemon 都一樣。確認的方式是比對，不是相信：

  ```sh
  diff <(plutil -p /Library/LaunchDaemons/online.rcsl.health-check.plist) \
       <(plutil -p launchd/online.rcsl.health-check.plist)
  ```

  重裝並重載：

  ```sh
  sudo install -o root -g wheel -m 644 \
    launchd/online.rcsl.health-check.plist /Library/LaunchDaemons/
  sudo launchctl bootout system/online.rcsl.health-check 2>/dev/null
  sudo launchctl bootstrap system /Library/LaunchDaemons/online.rcsl.health-check.plist
  ```

  **這份 repo 裡還有兩個故障注入工具，都不是平台的一部分，不要當成部署步驟。**
  `online.rcsl.delay-tailscaled-once.plist`（配 `delay-tailscaled-once.sh`）是 §1.1a 的，
  會在開機時把機器踢下 tailnet 90 秒，**刻意不在上面這個安裝清單裡**。
  `stop-stack-once.sh` 是 §1.1b 的，它**沒有 plist**（故障在重開之前就設好了，不需要開機時
  的零件），平常不執行。

  每五分鐘查七件事：`.env` 讀得到 `TAILNET_IP`、位址在介面上、docker 有回應、**預期清單裡
  的九個服務都在跑**、每個要求了 host binding 的容器真的拿到了、六個入口都答得出來、Ollama
  在 loopback 上而且**沒有**在 tailnet 位址上答話。第四項是跟一份寫死的清單比對而不是列舉
  現有容器——不然整個消失的容器不會出現在列舉裡，掃過去會回報「一切正常」。那正是
  reconciler 第三個前置條件在防的錯，也是 `tailscale status --json` 那次的錯。

  **第四項問的是 `docker compose ps --services --status running`，那個 `--status` 是必要
  的。** 不加的話 `docker compose ps` 只排除「stopped」（`--all` 的說明就是「多顯示停掉
  的」），所以 paused、restarting、created 都會被算成「在跑」。這在這台機器上不是假想：
  Docker Desktop 的 Resource Saver 會把容器 pause 掉（19:04:18 關機時那條 `/unpause` 就是
  它做過的證據）。而 `postgres`、`redis`、`prometheus` 在第六項裡沒有任何 probe，第四項是
  它們唯一的覆蓋——被 pause 的話，唯一該說話的地方會是沉默的。2026-07-26 實測：把
  `prometheus` pause 起來，舊版腳本 exit 0、state 檔還是 `OK`、一封信都不寄；改過的版本
  `failing: services,` 並在三秒後寄出。

  只有狀態**改變**才寄信：壞了寄一封、同樣的壞法不再重複寄、修好寄一封。另外每天一封
  heartbeat。

  **它看得到什麼、看不到什麼。** 它跑在被它監測的機器上，所以它報得出「機器活著但服務不
  通」——也就是實際發生過的那種故障——但報不出「機器關機了」。每天那封 heartbeat 就是補這
  個：**信停了就是有事，即使一封告警都沒收到。** 這是唯一能讓沉默變成訊號的辦法。

  第一次跑會寄一封 `monitoring started`，那封信本身就是在測 mail path，而 mail path 是整套
  裡唯一沒辦法靠「看它有沒有動」來驗證的部分。

  ```sh
  tail -20 /opt/homebrew/var/log/nexus-health.log   # 只記事件，平常是空的
  ls -l /opt/homebrew/var/nexus-health.state        # mtime 就是上次執行時間
  ```

  log 平常空著是正常的，所以「它到底有沒有在跑」不要從 log 判斷，看 state 檔的 mtime。

  **手動跑的那一次不會出現在 log 裡。** 輸出的重導向寫在 plist 上，不在腳本裡，所以你在
  終端機跑它，訊息就只出現在終端機。手動跑的紀錄是 state 檔和那封信，不是
  `nexus-health.log`。`reconcile-port-bindings.sh` 也一樣。

  **重開機之後不要太早下結論——但 state 檔的 mtime 現在任何時候都可讀。** 開機那一刻
  （`RunAtLoad`）會跑一次，那一次被 boot grace 擋掉、什麼都不檢查，只把 state 檔原封不動
  重寫；第一次**真正檢查**是開機後五分鐘的排程觸發。所以「重開後八分鐘沒收到信」仍然不能
  當成任何證據（前五分鐘歸 reconciler，在那段時間告警等於寄出一個即將被修好的故障），但
  **mtime 從開機那幾秒起就是新的**，不會再出現「機器好好的、判準卻說 daemon 死了」。

  grace 是 240 秒而 `StartInterval` 是 300 秒，兩者不一樣是刻意的：一樣的話，開機後第一次
  排程觸發剛好落在邊界上，要不要評估取決於 launchd 花了幾秒載入 job。這兩個數字在
  2026-07-26 之前都是 300，而且 grace 本身因為一個貪婪的 `sed` 從來沒有生效過（§1.1 有完整
  的說明）。**2026-07-26 21:02 那次開機量到第一次排程觸發在 uptime 307 秒**——距離 300 只有
  7 秒，所以那個邊界是真的，不是紙上談兵。

  **這整套在真實開機上證實過了，而證據不是 mtime。** `RunAtLoad` 那一次的 mtime 五分鐘後
  就被蓋掉，而且 `RunAtLoad=false` 會產生一模一樣的 mtime，兩種設定分不出來。要分辨看
  統一日誌的 spawn／exit 配對（`xpcproxy` 那行是 spawn，`service inactive` 是結束）：

  ```sh
  /usr/bin/log show --last 30m \
    --predicate '(process == "xpcproxy" OR process == "launchd") AND eventMessage CONTAINS "online.rcsl.health-check"' \
    --style compact
  ```

  開機那一次會是 uptime 個位數秒、**執行時間一百毫秒出頭**；走完整檢查的那幾次是 500～600
  毫秒（六個 curl 加十次 `docker inspect`）。差五倍，一眼就分得出來。**不要用
  `launchctl print` 的 `runs`**：它沒有附時間，`runs = 3` 分不出「`RunAtLoad` 加兩次排程」
  還是「三次排程」。§1.1 有完整的實測表。

- [ ] 首次建立管理員：用**另一台你自己的裝置**（筆電或手機，加入同一個 tailnet）瀏覽
  tailnet 入口 `https://<你的主機>.ts.net`。第一次登入會用你的 Tailscale 身分自動把你
  bootstrap 成第一個 admin（前提是 `BOOTSTRAP_ADMIN_LOGIN` 設成你的 Tailscale 身分，且
  users 表還是空的）。

  **不能用伺服器自己測，這一步一定會失敗，而且看起來像壞掉。** 第 4 部分給這台打了
  `tag:ai-server`，而 tagged 節點沒有使用者身分（`tailscale whois <ip>` 只會列出 Tags，
  沒有 User 區塊）。`tailscale serve` 注入的 `Tailscale-User-Login` 是從連線來源節點的
  擁有者取得的，所以從伺服器連自己，那個標頭根本不存在，入口回 401。這是設計的必然
  結果，不是設定錯誤。要驗證後端本身沒問題，可以在伺服器上繞過 serve 直接打，手動補
  上標頭：

  ```sh
  curl -H "Tailscale-User-Login: 你的@email" http://127.0.0.1:8001/admin/me
  ```

  順帶一提，這行指令能成功本身就說明了為什麼 tailnet 入口只綁 `127.0.0.1`：它對這個
  標頭是無條件信任的，任何能連上那個 socket 的東西都能偽造管理員身分（security.md
  §5.1）。

- [ ] **幫自己補上公開入口的憑證。** 從 tailnet 身分 bootstrap 出來的第一個管理員，
  `password_hash` 和 `totp_secret` 都是空的——tailnet 入口不需要它們，身分由
  `tailscale serve` 提供。但公開入口要的是本地帳號加強制 TOTP，`can_use_public_entrance`
  兩者都要。所以**不補的話，nginx 架好了你也登不進公開入口**，而那時候通常已經沒有人
  記得這回事了。

  做法：在 tailnet 入口的 Users 頁面幫自己發一張邀請，用那個連結設定密碼並掃 TOTP QR。
  這件事不用等 nginx，現在就能做。確認方式：

  ```sh
  docker compose exec -T postgres psql -U nexus -d nexus -Ac \
    "SELECT login, (password_hash IS NOT NULL) AS pw, (totp_secret IS NOT NULL) AS totp FROM users;"
  ```

  兩欄都要是 `t`。（`users` 上有 check constraint 要求這兩者同時存在或同時不存在，所以
  不會出現只補一半的狀態。）

- [ ] 登入後在管理 UI 裡：註冊一個模型、綁一條 routing policy、發一把 API key，確認
  gateway 真的能服務推論。

  兩個呼叫端會踩到、但目前沒有文件的地方：

  - **OpenAI 請求裡的 `model` 欄位放的是 capability，不是模型別名。** 送
    `"model": "chat"`，不是 `"model": "qwen7b"`。`RouteChatRequest` 用 capability 查
    routing policy，policy 才決定用哪顆模型。填模型別名會得到 `no_available_model`，
    而那個訊息不會告訴你原因。
  - **Production 下 gateway 拒絕沒有經過 proxy 的請求。** nginx 還沒架好時要自己模擬：

    ```sh
    curl -H "Authorization: Bearer <key>" \
         -H "X-Nexus-Proxy: $(cat secrets/proxy_shared_secret)" \
         -H "X-Forwarded-For: <一個台灣 IP>" \
         -H "Content-Type: application/json" \
         -d '{"model":"chat","messages":[{"role":"user","content":"hi"}],"stream":false}' \
         http://<TAILNET_IP>:8000/v1/chat/completions
    ```

    少了 `X-Nexus-Proxy` 會得到 `untrusted_proxy`；少了 `X-Forwarded-For` 也一樣，因為
    絕不退回連線來源位址是刻意的（否則每個呼叫端看起來都同一個來源，每把金鑰的 IP
    允許清單就形同虛設）。

---

## 8. 外部協調：NTNU proxy 管理員的四件事（可並行）

照 [deployment.md](../architecture/deployment.md) §5。請對方：

1. 安裝 Tailscale 加入 tailnet，打上 `tag:ntnu-proxy`（ACL 靠這個把它限制在它需要的
   三個埠）。
2. 加兩個 nginx server block（`ai.nexus.rcsl.online` 與 `api.nexus.rcsl.online`），
   外加 HTTP 轉 HTTPS。設定範本在 deployment.md §5。
3. 簽 Let's Encrypt 憑證（port 80 已開，HTTP-01 可直接驗）。
4. 確認：`proxy_buffering off`、`proxy_read_timeout` 夠長、**不記錄 request body**、
   `X-Forwarded-For` 用「覆寫」(`$remote_addr`) 而非附加、並送出 `X-Nexus-Proxy` 共享
   密鑰（等於你的 `proxy_shared_secret`）。

另外請他們為兩個名稱給**明確的 A record**，不要只靠 wildcard 合成（見 security.md
§15.4：一旦有人在 zone 裡新增 `nexus.rcsl.online` 節點，wildcard 合成會失效）。

---

## 9. 上線前安全檢查（要測，不要猜）

完整清單在 [security.md](../architecture/security.md) §14。以下是最關鍵、且一定要**實測**
的幾項：

- [ ] 對公開入口送一個偽造的 `Tailscale-User-Login` 標頭：應被剝除，沒有拿到任何權限
- [ ] 從不受信任來源偽造 `X-Forwarded-For`：應被拒
- [ ] 把 `AUTH_MODE=dev` 配 `ENV=production`：應**拒絕啟動**（改一下確認起不來，再改回）
- [ ] 用一個 `user` 角色帳號登入：admin 功能應該真的用不了
- [ ] 同一組 TOTP 碼用兩次：第二次應被拒
- [ ] gateway 不提供 `/docs` 或 `/openapi.json`
- [ ] 串流沒有被 nginx 緩衝（`proxy_buffering off` 生效，回應是逐字吐出而非等全部）
- [ ] 資料庫帳號切分：gateway 帳號寫不了 `api_keys`/`users`（已有自動化整合測試佐證，
  見 `backend/tests/integration/test_db_role_grants.py`）
- [ ] secrets 都是檔案掛載、`.env` 裡沒有機密、gitleaks pre-commit 有開
- [ ] `/metrics` 沒帶 token 直接打應回 404；Prometheus 沒有對外埠、也沒被 nginx 轉發。
  `metrics_scrape_token` 與 `grafana_admin_password` 都是真值，不是範本佔位字串

---

## 10. AGPL 義務（別忘）

兩個公開網址都會觸發 AGPL §13：任何連上 `ai.nexus.rcsl.online` 或
`api.nexus.rcsl.online` 的人，有權取得「正在運行的那個版本」的原始碼，包含在地修改。
這是持續性的營運義務，不是一次性手續。保持部署版本可識別、原始碼可取得。見
[deployment.md](../architecture/deployment.md) §8.1。

---

## 附錄：新手常見卡點

### `docker pull` / `docker compose build` 完全沒有輸出就卡住

**症狀**：`docker pull hello-world` 連 `Pulling from` 都印不出來，`docker compose build`
以 `DeadlineExceeded: context deadline exceeded` 失敗在 `load metadata`。但 `docker ps`
正常、容器都在跑，容器內 `wget https://ghcr.io/v2/` 也通。

**原因不在 Docker。** Docker CLI 在送出請求前會先解析 registry 憑證，而
`~/.docker/config.json` 的 `credsStore: desktop` 會讓它去讀 macOS 鑰匙圈。這台機器是
無頭運作的（螢幕關閉、從 SSH 進來），鑰匙圈需要一個能回應提示的 GUI 工作階段：

```
$ security show-keychain-info ~/Library/Keychains/login.keychain-db
security: ... User interaction is not allowed.
```

沒有人能按那個對話框，所以 helper 永遠等下去。buildkit 的憑證也是由 CLI 端經 session
提供的，所以 build 會用同樣的方式卡住。**重啟 Docker Desktop 沒有用**，壞的不是 Docker。

**處理**：把 `credsStore` 從 `~/.docker/config.json` 拿掉。這個專案用到的映像全部是公開
的，`auths` 本來就是空的，那個 helper 是在為了取得沒有東西而卡死。代價是：日後若
`docker login` 到私有 registry，憑證會以 base64 存在該檔案而非鑰匙圈——但在這台機器上
鑰匙圈那條路本來就不能用。

**這是一類問題而不是單一問題。** 任何在這台機器上從非 GUI 情境碰鑰匙圈的工具，都會用
同樣的方式卡住。遇到「某個指令莫名沒有輸出就停住」時，先想到這一條。


- **`migrate` 沒有 `exited (0)`**：`docker compose logs migrate`。多半是 secrets 缺檔、
  帳號名不是小寫、或 `postgres_password` 跟 owner URL 裡的密碼不一致。
- **`docker compose up` 起不來、抱怨 secret 檔不存在**：`./secrets` 底下每個檔都要建好
  （第 6 部分）。這是刻意的，缺就不啟動。
- **服務起不來、log 提到 GeoLite2**：`data/GeoLite2-Country.mmdb` 沒放好（第 5 部分）。
- **Docker Desktop 沒在跑**：macOS 上 `docker compose` 需要 Docker Desktop 開著（設成
  登入自動啟動）。
- **重開機後服務沒回來**：先分清楚是「容器沒回來」還是「容器回來了但 port 沒綁」，
  這兩者的症狀完全不同，而後者比較常見也比較難認。

  容器沒回來 → 確認自動登入、Docker Desktop 自動啟動、Ollama 的 launchd 服務有起、
  容器是 `restart: unless-stopped`（已預設）。

  **容器回來了但打不到** → 這是 2026-07-26 實際發生的那一種。`docker compose ps` 顯示
  九個 running、gateway 標 healthy，而 `curl http://<TAILNET_IP>:8000/readyz` 沒有回應。
  `restart: unless-stopped` 對這種情況**完全無效**——綁定失敗不會讓容器退出，沒有東西
  退出就沒有東西重啟。查法：

  ```sh
  tail -30 /opt/homebrew/var/log/nexus-reconcile.log   # 對帳 daemon 說了什麼
  sudo launchctl list | grep reconcile                 # 它有沒有註冊、上次結束狀態
  docker inspect <容器> --format '{{json .NetworkSettings.Ports}}'   # [] 就是掉了
  ```

  手動補救(注意**一定要 `--force-recreate`**，`up -d` 和 `restart` 都無效，原因見
  第 7 部分)：

  ```sh
  docker compose up -d --force-recreate gateway admin-public frontend-public
  ```
- **Mac 上容器碰不到 GPU**：所以 Ollama 一定要原生跑，別想放進 Docker。

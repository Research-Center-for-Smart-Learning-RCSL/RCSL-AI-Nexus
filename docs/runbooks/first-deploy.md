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
| `all expected services running` → `OK: all bindings restored` | 競態發生了，reconciler 補回來了。**這是最有價值的結果**——binding 修復路徑被真的走過一次 |
| `docker did not restore the stack; bringing it up` → `stack up: all expected services running` | Docker 沒還原容器，reconciler 自己把整套拉起來了。**這也是有價值的結果**——2026-07-26 19:10 那次開機就是這個情況，而當時的 reconciler 還不會做這件事 |
| `STILL UNBOUND after recreate: <服務>` | 有東西壞在 `--force-recreate` 修不了的地方（internal 網路、port 被佔）。看那個服務的 `docker inspect` 和 Docker backend log |
| `FATAL: still not running after up -d: <服務>` | 容器起不來，不是沒被叫起來。`docker compose logs <服務>` 才是要看的地方，重跑 reconciler 不會有幫助 |
| log 不存在或是空的 | daemon 根本沒跑。`sudo launchctl list \| grep reconcile` 看有沒有註冊，第二欄是上次結束狀態 |

第一種結果要當心：它是運氣，不是證明。真要確認 binding 修復路徑有效，得重開到出現第二種
為止——而下面「快取不會接續」那段說明了怎麼提高機率：**連續重開兩次，盯第二次**。

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

**五次開機了，六種結果裡最有價值的那兩種還是空白。**

它贏得有多險，五次開機的 log 對得出來：

| 開機 | `tailscaled` 起 | 位址可用 | Docker `exposer.Add` | 餘裕 |
|---|---|---|---|---|
| 16:45（失敗） | 16:45:15 | 16:45:32（+17 秒） | 16:45:29 | **−3 秒** |
| 17:21（通過） | 17:21:48 | 17:21:48（+0 秒） | 17:21:59 | **+11 秒** |
| 18:08（通過） | 18:08:14 | 18:08:23（+9 秒） | 18:08:25 | **+2 秒** |
| 19:09（失敗，別的原因） | 19:09:59 | 19:10:00（+1 秒） | *（從來沒有）* | *（沒有競態可言）* |
| 19:43（通過） | 19:43:28 | 19:43:37（+9 秒） | 19:43:39.7 | **+2.7 秒** |

Docker 那一側在有出場的四次裡都是穩定的：都在 `tailscaled` 起來後 11～14 秒綁定。**全部的
變數都在「位址多久上來」**——0、1、9、17 秒。預算大約十一秒。

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

**預測對了，而且連續對了兩次。** 19:09:59 那次開機讀到了快取，位址 +1 秒就上來，是快的
那一種；它讀了就沒重寫，所以預測「再下一次是慢的那種」——19:43:28 果然是
`netmap cache is not available`，位址等了 9 秒，然後在 19:43:38 重新寫了一份。**「讀了不
重寫」現在有兩次觀察撐著，不是一次**，而且第二次是先寫下預測才發生的。依同一條規則，
**下一次開機會是快的那種**。

**它同時第一次告訴你怎麼把驗收真正想要的那個結果逼出來——但這個槓桿比看起來弱。**
`OK: all bindings restored` 需要一次**輸掉**競態的開機，而輸的那些都是沒有快取的——也就是
「剛讀過快取的那次開機的下一次」。所以要驗修復路徑，**連續重開兩次、盯第二次**，比一直
重開碰運氣有效得多。但要知道它有多弱：目前兩次沒有快取的開機（18:08、19:43）都還是
**+2 秒左右通過**，只有 16:45 那次位址等了 17 秒才真的輸掉，而那個 17 秒至今沒有再出現。
「慢的那種」現在的實測意思是「贏 2 秒」，不是「會輸」。

**狀態現在是：第一輪通過四次，第二輪跑了一次、失敗。** 第二輪的失敗不是第一輪的失敗，
第一輪的四次通過仍然成立；但「兩輪都過」還沒有發生，所以下面那句「兩輪都過才代表這台
機器真的能自己復原」仍然是未達成的。兩條修復路徑也都還沒有被任何一次開機真的走過：
binding 修復路徑一次都沒觸發，容器拉起路徑是在 19:09 那次失敗之後才寫的——19:09 那次的
復原是**人手跑的** `docker compose up -d`（`migrate` 的 `StartedAt` 是 19:28:26，那就是
證據），不是 reconciler。

**兩條路徑各有一次手測，記在這裡，因為手測和開機測不是同一件事。** 停掉 `grafana` 再手跑
reconciler：`not running: grafana` → `docker did not restore the stack; bringing it up` →
`stack up: all expected services running` → `all published bindings intact`，16 秒、exit 0，
之後 `127.0.0.1:3002` requested 與 actual 相符、`/login` 200。**注意它沒有重建容器就把
binding 帶回來了**——這和「必須 `--force-recreate`」不衝突，是兩種不同的壞法：容器**還在跑**
但轉發表是空的，`up -d` 是 no-op，只能重建；容器**是停的**，`up -d` 會把它起來，轉發是那時
候才建立的。腳本兩條都有，是因為要修的是兩件事。

手測補不上的正是開機才有的東西：所有東西同時在動。所以這兩種結果在 §1.1 的表上仍然算
空白。

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

**兩輪都過，才代表這台機器經歷過真實的重開與系統更新並自己完整復原。** 目前是第一輪過了
三次、第二輪失敗一次，所以這句話還沒有成立。在它成立之前不要遠端做系統更新——更新失敗
停在互動畫面時，遠端修不了。

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

- [ ] 斷電後自動重新啟動：系統設定 > 節能。跳電恢復後機器要自己開機。

- [ ] 遠端登入 (SSH)：系統設定 > 一般 > 共享 > 遠端登入。**拔掉螢幕之前一定要先開**，否則
  沒有救援管道。金鑰限定、禁 root、只聽 tailscale 介面等硬化要求見 security.md §11，可以
  等第 4 部分 Tailscale 起來之後再套。

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

  **重開機之後不要太早下結論。** boot grace 和 `StartInterval` 都是 300 秒，開機時第一次觸發
  剛好落在邊界上，所以第一次真正有效的檢查可能是第二次觸發、也就是開機後約十分鐘。這是刻意
  的——前五分鐘歸 reconciler，在那段時間告警等於寄出一個即將被修好的故障——但代價是「重開後
  八分鐘沒收到信」還不能當成任何證據。看 state 檔的 mtime，不要看信箱。

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

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
                                       health-check、host-metrics）
           → Docker Desktop 自啟 → 11 個容器 restart: unless-stopped 回來
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

移到 [`boot-recovery-acceptance.md`](./boot-recovery-acceptance.md)，編號不變。那份
文件同時收著 §1.1a 與 §1.1b 兩個故障注入程序，以及「為什麼人一定要在現場」。

**它不是可選的。** 在 §1.1 通過之前，你沒有證據說這台機器能無人復原——你只有一串看
起來正確的設定。等第 7 部分整套跑起來之後再回來做。

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

  需要 **v2.17 以上**。backend image 透過具名 build context（`client_tools`，
  指向 `./scripts`）把 Windows 操作工具複製進去，`GET /admin/client-tools/windows-codex-app`
  才能提供這個 deployment 正在跑的版本，而不是 GitHub 上的某個分支。舊版 Compose
  會回報 `additional_contexts` 不支援，而不是回報缺檔案。

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
  用 repo 裡的 [`launchd/online.rcsl.ollama.plist`](../../launchd/online.rcsl.ollama.plist)
  ——**但不要在這裡手動安裝它**。那份 plist 的 `UserName` 是 `_rcslollama`，那個帳號此刻
  還不存在，現在 bootstrap 只會得到一個起不來的 daemon。安裝與載入都由下一步的
  `adopt-ollama-service-account.sh` 負責，它自己會做 `cp`、`chown root:wheel`、
  `chmod 644`、`plutil -lint`，最後才 `launchctl bootstrap`。

  Homebrew 的做法在這台機器上有兩個問題，其中一個是靜默的安全失效：

  - **`launchctl setenv OLLAMA_HOST 127.0.0.1` 不會跨重開機存活。** 它寫的是
    launchd 的 boot session domain。重開機後變數消失，而 Homebrew 的 plist 裡
    沒有 `OLLAMA_HOST`，Ollama 就退回預設的 `0.0.0.0:11434`——推論端點對整個
    區網敞開，而且沒有任何跡象。security.md §7.1 要求的 loopback 綁定必須自己
    能撐過重開機，所以值要寫死在 plist 裡。
  - **不加 sudo 的 `brew services` 是 LaunchAgent，要登入才啟動。** 這台無頭
    運作，跳電重開後不會有人登入（FileVault 開著時更不可能），Ollama 就不會
    回來，gateway 只會一直回「no available model」。所以是 LaunchDaemon。

  plist 裡 `UserName` 是專用服務帳號 `_rcslollama`，既不是 root 也不是操作者帳號。
  root 不行是因為 daemon 預設以 root 執行，會去找 `/var/root/.ollama` 而看不到已經拉好
  的模型；操作者帳號不行是因為它在 `admin` 裡、能 sudo，而這個 process 載入的是從網路
  抓下來的權重（[security.md](../architecture/security.md) §7.1(d)）。2026-08-18 以前
  它確實是操作者帳號，那是在還沒有辦法把模型目錄搬出家目錄之前的權宜之計。

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

- [ ] **把 Ollama 移到專用服務帳號。這一步是必須的，而且必須在 §5.1 設
  `OLLAMA_MODELS_HOST_PATH`、§7 `docker compose up -d` 之前做完**：

  ```sh
  sudo sh launchd/adopt-ollama-service-account.sh
  ```

  它會建 `_rcslollama`（uid 470、無 shell、不在 `admin`、密碼 `*`）、停掉 daemon、把
  `~/.ollama` 搬到 `/Users/Shared/ollama`、改擁有權為 `_rcslollama:staff`（目錄 750）、
  把 `/opt/homebrew/var/log/ollama.log` 一起改擁有者（**漏掉這步 daemon 開不了自己的
  log 就不會啟動**），然後安裝並載入 plist、驗證 API 有回應。每一步都先檢查再動，任何
  一項不成立就整個拒絕；出事用 `--rollback`。

  **為什麼一定要搬目錄，而不是只改 `UserName`**：`/Users/<operator>` 是 750，不在
  `staff` 的帳號無法 traverse，所以權重只要還留在家目錄裡，任何服務帳號都讀不到。這一
  個八進位數字就是這件事擱置數月的全部原因。`/Users/Shared` 和家目錄在同一個 volume，
  所以那 214 GB 是 rename 不是複製，中斷只有兩秒。群組給 `staff` 而不是服務帳號自己的
  群組，是因為 Docker Desktop 以操作者身分分享該路徑，而三個後端容器要唯讀掛載它來讀
  tokenizer——寫的權限歸 runtime 一個帳號，讀的權限給 `staff`。

  **這一步不能延後。** 腳本看到 `/Users/Shared/ollama` 已經存在就會
  `REFUSING: /Users/Shared/ollama already exists` 而什麼都不做；而 §5.1 會叫你把
  `.env` 指向那個路徑，一旦先跑了 `docker compose up -d`，Docker 就會替那個 bind mount
  自己建出一個空目錄，把這條路堵死。

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

（Tailscale SSH 在 macOS 上可以當伺服器用。判斷它「有沒有啟動」不要去看
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

這一步只發生一次，之後不會有任何東西告訴你這份資料庫該更新了。排程更新在 **§7**，跟其他
LaunchDaemon 放在一起——它要跑得起來，得先有 repo、有 `secrets/`，而且 stack 已經在跑。

---

## 5.1 Ollama 的模型倉庫（不掛會退回估算）

平台從模型 `ref` 對應到的那個 GGUF 檔裡讀出字彙表與 chat template，用它精確計算 prompt
的 token 數，取代原本用字元寬度估的做法。只讀 metadata header（`qwen3.6:35b-a3b-q8_0`
是 38.7 GB 權重前面的 11.9 MiB），每個模型每個 process 一次。

**掛好了也不保證每個模型都能精確計數，這一節的標題只講了兩個失敗原因裡的一個。**
字彙表只會為 pre-tokenizer 在 `KNOWN_PRE_TOKENIZERS` 裡的模型建起來（目前是 `qwen2`
和 `qwen35`）；不在清單裡的，`prepare` 會拒絕，那個模型就退回字元估算，倉庫掛得再對也一樣。
2026-09-02 對實機量測：`gemma4:31b-it-q8_0` 宣告 `gemma4`，**不在清單裡**，而它從
2026-08-21 起就是 `chat` 和 `code` 的模型——所以這台目前這兩個 capability 都是估算的；
`qwen2.5:7b`、`qwen3.6:35b-a3b-q8_0`、`qwen3.8:27b-q4_K_M` 都可以。MLX 格式的模型
（safetensors，manifest 沒有 `image.model` 層）一樣不行。要判斷實際狀況，看回應裡的
`tokenizer` / `estimate` / `lower_bound` 標記，不要看這一步有沒有打勾。

- [ ] 確認 Ollama 的模型倉庫位置。**這台是 `/Users/Shared/ollama/models`，不是任何人的
  家目錄底下**——2026-08-18 把 runtime 移到專用服務帳號 `_rcslollama` 時一起搬的，因為
  `/Users/rcslmac1` 是 750，服務帳號連進都進不去（見上面 §3 的服務帳號那一步）。全新安裝
  若還沒做那一步，位置是執行 Ollama 那個帳號的 `~/.ollama/models`。
- [ ] 在 `.env` 設 `OLLAMA_MODELS_HOST_PATH=/Users/Shared/ollama/models`。
  compose 會把它**唯讀**掛成容器裡的 `/ollama-models`。唯讀是有原因的：那個目錄的擁有者
  是 Ollama，能寫它的容器就能換掉主機正在服務的權重。

**不掛也能跑，而且是支援的狀態**：`OLLAMA_MODELS_PATH` 留空就關掉精確計數，每個請求退回
字元估算——也就是 2026-08-18 之前的行為——並且每個模型會留一行 log 說明。只服務 MLX 的
主機沒有 GGUF 可讀，就是這種情況。

估算錯得有多離譜值得寫下來，因為它決定了這一步該不該做：對照 runtime 量過，散文、原始碼與
tool schema 高估 1.34x-1.48x，uuid 清單低估到 0.36x。高估會拒掉硬體本來服務得了的請求
（2026-08-17 就發生過一次，140,059 估算、實際約 99,000）；低估則是 runtime 默默截斷提示詞
的前奏。沒有任何單一常數落在那個區間裡。

**這組比例在 repo 裡有兩份、對不起來，2026-08-18 量了第三次才知道為什麼。**
[`PROGRESS.md`](../PROGRESS.md) 2026-08-17 的六列量測是 1.34x-1.48x 與 uuid 的 **0.36x**
（上面那一行就是引它的），`RouteChatRequest` 的 module docstring 裡那份十列表是
1.22x-1.47x 與 uuid 的 **0.34x**。第三次量測用新寫的樣本、對同一個 tokenizer：散文
1.61x、Python 1.47x、TypeScript 1.25x、Markdown 1.22x、JSON tool schema 1.24x、
uuid 0.37x —— **和前兩份都不完全一致**。

原因不是哪一份量錯了：**這個比例是樣本的性質，不是內容類別的常數**，散文的擺盪最大，
因為結果幾乎由「常見短字佔多少」決定。所以兩份表寫到小數第二位都是假精確，三份放在一起
唯一誠實的讀法是一個區間：**自然語言與原始碼約 1.2x-1.6x 高估，dense identifier 約
0.34x-0.40x 低估**。這一步的結論不變（沒有任何單一常數落在那個區間裡），但**不要引用
任何一份的單一數字當作某類內容的定值**。完整說明在 `RouteChatRequest` 的 module
docstring 裡，那是估算器本身所在的地方。

---

## 6. 取得專案並設定

- [ ] 取得程式碼（用你的 git 遠端位址）：

  ```sh
  git clone <repo-url>
  cd RCSL-AI-Nexus
  ```

- [ ] **要能 push 的話，用 SSH deploy key，不要用 HTTPS。** 讀取不需要憑證（repo 是
  公開的），但寫入需要，而 macOS 的 `osxkeychain` helper 在這台機器上**兩個方向都不能
  用**：非 GUI session 的 keychain 搜尋清單裡只有 System keychain，login keychain 雖然
  檔案在、卻不在清單內。`get` 回空、`store` 回 `-61`。跟 §Docker 那個 `credsStore` 是
  同一個根因（[PROGRESS.md](../PROGRESS.md) 2026-07-27、2026-07-29）。

  沒設好的話 push 會靠一個連著的編輯器現場供應憑證，看起來能動——直到你從純 SSH
  session 推，或是想讓排程去推。

  ```sh
  # 1. 產金鑰。刻意不設密語：密語要 ssh-agent，解鎖 agent 要有人在機器旁，
  #    那正是這一步在解決的問題往下一層。
  ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_rcsl_nexus -N "" \
    -C "RCSL-AI-Nexus deploy key (Mac Studio, headless)"

  # 2. 釘住 GitHub 的主機金鑰，比對官方公布的指紋，不要靠第一次連線就信任
  ssh-keyscan -t ed25519 github.com > /tmp/gh_hostkey
  ssh-keygen -lf /tmp/gh_hostkey    # 必須是 SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU
  cat /tmp/gh_hostkey >> ~/.ssh/known_hosts

  # 3. 停用那個沒有用的 helper，否則每次 push 都噴一行看起來像失敗的 fatal
  git config --global credential.helper ""
  ```

  把 `~/.ssh/id_ed25519_rcsl_nexus.pub` 貼到 repo 的 Settings → Deploy keys，
  **要勾 Allow write access**。用 deploy key 而不是 PAT，是因為 PAT 在這台機器上只能明文
  躺在 `~/.git-credentials`；deploy key 只對這一個 repo 有效，也能單獨撤銷。

  然後把 remote 換成 SSH 並驗證。判準是**拿掉 `GIT_ASKPASS` 之後仍然可用**——否則你驗
  到的只是編輯器還連著：

  ```sh
  git remote set-url origin git@github.com:<org>/<repo>.git
  env -u GIT_ASKPASS git fetch origin
  env -u GIT_ASKPASS git push origin main
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
  | `PROXY_HOSTNAME` | `llmapi.rcsl.online` |
  | `ADMIN_BASE_URL` | `https://llm.rcsl.online` |
  | `GATEWAY_BASE_URL` | 留空（見下方註）|
  | `NODE_TOTAL_MEMORY_GB` | `64`（要對上這台的實際記憶體）|
  | `ALLOWED_COUNTRIES` | `TW,AU` |
  | `BOOTSTRAP_ADMIN_LOGIN` | 你的 Tailscale 登入身分（通常是 email）|

  `COOKIE_SECURE` 保持 `true`、`CACHE_BACKEND` 保持 `redis`。

  註：`GATEWAY_BASE_URL` 是發卡畫面與 `/api-docs` 頁面上顯示給使用者複製的推論
  端點。留空會從 `PROXY_HOSTNAME` 推導成 `https://llmapi.rcsl.online`，這正是
  本部署要的值，所以不用填。只有在對外 origin 與 `PROXY_HOSTNAME` 不同時才設它。
  它不能從請求讀出來——渲染那段程式碼片段的請求打的是管理入口，不是被描述的那個
  主機。填錯的後果是使用者拿到一段貼上去連不到的範例，而錯誤會出現在別人的終端機裡。

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
  - `secrets/qdrant_api_key` 與 `secrets/qdrant_read_only_api_key`：知識庫向量庫的
    金鑰，**兩個必須是不同的值**（各跑一次 `openssl rand -base64 32`）。Qdrant 預設
    完全沒有認證，所以這不是加強而是唯一的控制；read-only 那把掛給 gateway，讓它
    只能讀不能寫（security.md §6）。這兩個檔在 production 一定要是真值，沒有像
    `metrics_scrape_token` 那樣的關閉開關

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

  必須用 `docker compose build`，不能用 `docker build ./backend`：後者解析不到具名
  build context，會停在 `COPY --from=client_tools` 那一行。

- [ ] 確認 `migrate` 顯示 `exited (0)`。它依序做三件事：`alembic upgrade head` 套用全部
  migration、`db_roles` 建立三個資料庫帳號並套用授權、`provision` 寫入單一節點那一列並把
  重啟中斷的 transient 狀態收斂成 `error`。若不是 0，
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
  `127.0.0.1:3002`。postgres／redis／prometheus／qdrant／parser 顯示 `null` 是對的，
  它們本來就不發布——`null`（沒要求）和 `[]`（要求了、沒拿到）是兩件事，掉的是後者。

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

- [ ] **裝 GeoLite2 更新的 LaunchDaemon。** §5 那份資料庫放進去之後就停在那天了。MaxMind
  一週發布兩次，IP 段會在國家之間搬家，所以一份不動的副本**越放越錯，而且兩個方向都
  錯**：該放行的被擋、該擋的被放行。而且它是安靜的——country filter 照常運作，只是依據過
  期的事實。保持更新也是 MaxMind 授權條款的要求，不是偏好。

  先到 MaxMind 帳號頁建立**永久 License Key**（不是第一次下載用的臨時 token；排程工作要
  的是長效那一種）：

  ```sh
  printf '%s' 'YOUR_MAXMIND_LICENSE_KEY' > secrets/maxmind_license_key
  chmod 600 secrets/maxmind_license_key
  bash launchd/refresh-geolite2.sh     # 先手動跑，確認金鑰真的能下載
  ```

  沒有金鑰時腳本會 `FATAL` 並保留舊資料庫不動，所以這一步真正驗證的是金鑰能用、下載得
  到、檔案通過格式與大小檢查。**這一步要在 stack 起來之後跑**：資料庫有換的話腳本會
  `docker compose restart gateway admin-public`——geoip2 只在啟動時開一次檔，不重啟等於沒
  換——容器不存在時那行會回非零，讓一次正確的設定看起來像失敗。這裡是 restart 不是
  recreate，所以不會重建 port binding，§1.1 那個開機競態不會從這裡被重新引入。上游沒有新
  版時它會說 `database unchanged upstream` 然後什麼都不做。

  ```sh
  sudo install -o root -g wheel -m 644 \
    launchd/online.rcsl.refresh-geolite2.plist /Library/LaunchDaemons/
  sudo launchctl load -w /Library/LaunchDaemons/online.rcsl.refresh-geolite2.plist
  ```

  每週三 05:30。**失敗現在有人會說了**：health-check 的第十二項從外面 `stat` 那個
  `.mmdb` 的 mtime，超過 10 天（它每週更新，所以那是至少兩次失敗）就進每日摘要——Tier 2，
  不會單獨寄信，一份舊掉的資料庫有的是前置時間。這一行到 2026-08-18 為止都還寫著「失敗不會
  有人通知你（health-check daemon 不看這個）」，而那句話正是 2026-08-04 加上第十二項的理由：
  這個 script 自己的 STALENESS 檢查只在它有跑的時候才出聲，而「它沒跑」正是要偵測的那件事。
  它自己的檢查仍然在，檔案超過 30 天時會在下一次執行開頭大聲抱怨，log 在
  `/opt/homebrew/var/log/nexus-geolite2.log`。

- [ ] **裝主機指標的 LaunchDaemon（`host-metrics`）。** 容器在 macOS 上讀到的記憶體和磁碟
  是那個 Linux VM 的，不是這台 Mac 的——數字看起來完全合理而且是錯的，比沒有更糟。所以這支
  只用標準函式庫的 script 原生跑、綁 `127.0.0.1:9101`，後端從
  `host.docker.internal:9101/host` 讀它（`host_metrics_url`）。

  ```sh
  sudo install -o root -g wheel -m 644 \
    launchd/online.rcsl.host-metrics.plist /Library/LaunchDaemons/
  sudo launchctl bootstrap system /Library/LaunchDaemons/online.rcsl.host-metrics.plist
  curl -s http://127.0.0.1:9101/host    # 應該回一段 JSON
  ```

  plist 裡的路徑寫死成 `/Users/rcslmac1/dev/RCSL-AI-Nexus/launchd/host-metrics.py`，
  repo 放在別的地方就要改；`UserName` 跟另外三個主機側 job 一樣是操作者帳號（只有 ollama 那個是 `_rcslollama`），因為 `vm_stat`、
  `sysctl`、`statfs` 誰都讀得到，不需要 root。

  **這一步在 2026-08-18 之前不在這份清單裡，而下一步裝的健康監測會因為它而失敗。**
  健康監測的第八項就是打這個 endpoint：它同時是這個 daemon 的存活檢查，也是第九項之外
  那組磁碟／記憶體數字的唯一來源。沒裝的話第一次真的執行就會寄一封 `host-metrics` 失敗
  的信，而那封信說的是真的——前端的主機面板同時也是瞎的。log 在
  `/opt/homebrew/var/log/nexus-host-metrics.log`，`Address already in use` 那種是
  KeepAlive 重啟得比舊 socket 釋放快，它自己會好。

- [ ] **裝健康監測的 LaunchDaemon（狀態變了會寄信）。** 開機對帳那個 daemon 修的是開機那一
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

  # 先空跑：每一項檢查都會跑，但信只印在終端機、不寄出，state 檔也不寫。
  # 兩者都重要——空跑如果寫了 state，就會把當天的摘要日期用掉，真正的那次反而不寄了。
  NEXUS_HEALTH_DRY_RUN=1 bash launchd/check-platform-health.sh

  bash launchd/check-platform-health.sh     # 再真的跑一次，確認信真的寄得出去
  ```

  ```sh
  sudo install -o root -g wheel -m 644 \
    launchd/online.rcsl.health-check.plist /Library/LaunchDaemons/
  sudo launchctl load -w /Library/LaunchDaemons/online.rcsl.health-check.plist
  ```

- [ ] **複驗 Ollama 的服務帳號**。移轉本身在 §3 就做完了
  （`adopt-ollama-service-account.sh`），這裡只確認它還在：

  ```sh
  ps -axo user,command | grep '[o]llama serve'   # 要顯示 _rcslollama
  ```

  `.env` 的 `OLLAMA_MODELS_HOST_PATH` 必須指向 `/Users/Shared/ollama/models`，掛載它的三個容器
  （`gateway`、`admin-tailnet`、`admin-public`），否則 tokenizer 會安靜地退回字元估算 ——
  `/readyz` 仍然是綠的，這是這個變更唯一會無聲壞掉的地方。確認方式：

  ```sh
  docker exec rcsl-ai-nexus-gateway-1 ls /ollama-models/blobs | head -3
  ```

  **改 plist 之後一定要重裝＋重載，改腳本不用。** plist 上的 `ProgramArguments` 指向工作樹
  裡的 `.sh`，所以腳本一存檔下次執行就是新的；但 `/Library/LaunchDaemons/` 裡那份 plist 是
  **複本**，repo 裡改了不會自動生效。這五個 daemon 都一樣（ollama、reconcile-port-bindings、
  health-check、refresh-geolite2、host-metrics）。確認的方式是比對，不是相信：

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

  每五分鐘跑**十四項**檢查，編號跟腳本裡的段落標題一致：1 `.env` 讀得到 `TAILNET_IP`、
  2 位址在介面上、3 docker 有回應、**4 預期清單裡的十一個服務都在跑**、5 每個容器一次
  `docker inspect`（要求了 host binding 的有沒有真的拿到、有沒有東西發布在不該發布的位址
  上、healthcheck 有沒有在失敗、重啟次數有沒有往上跳）、6 六個入口都答得出來、7 Ollama
  在 loopback 上而且**沒有**在 tailnet 位址上答話、8 host-metrics daemon 答不答得出來
  （以及它報的記憶體與磁碟）、9 容器真正寫進去的那顆磁碟（Docker VM 的那顆，不是 Mac 的）、
  10 Docker 可回收的空間、11 Prometheus 有沒有真的抓到每一個 target、12 GeoLite2 資料庫的
  新舊、13 tailscale node key 的到期、14 資料庫自己回答的四件事（快到期的金鑰、還開著的
  debug window、保留政策、最舊的一列有沒有超過政策）。8 到 14 這七項是 2026-08-04 加的，
  第五項也是那天重寫的；在那之前只有前七項。第四項是跟一份寫死的清單比對而不是列舉
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

  **兩級，而且這個分法就是設計本身（2026-08-04）。** Tier 1 是「現在就壞了」：進 signature，
  一變就立刻寄。Tier 2 是「快壞了、正在惡化」——到期、過期、成長——**不進 signature、也永遠
  不會自己寄信**，一天一次在摘要信裡講。理由是把「金鑰十四天後到期」放進 signature，subject
  就會連續十四天寫著 FAILING，而一個沒有意義的 subject 比沒有 subject 更糟。有前置時間的東西
  等摘要，沒有前置時間的東西才吵醒人。

  所以總共只有兩種信：

  - **狀態變化信**（事件觸發，每五分鐘評估）：壞了寄一封、同樣的壞法不再重複寄、修好寄一封。
    穩態下是 0 封。
  - **每日摘要**（每天 08:00 起，一天一封，好壞都寄）：目前狀態、Tier 2 警告、「檢查過而且沒
    問題」的數字、過去 24 小時的應用層統計（取自 Prometheus）、過去 24 小時的狀態變化。

  摘要的時間是**固定的 08:00**，不是「距上一封滿 24 小時」。舊版是後者，而且任何一封信都會重設
  它的計時器，所以送達時間會在一天之中漂移，「今天那封還沒來」根本不是一句講得出口的話。固定
  時刻才讓「沒來」變成可讀的訊號，而那正是摘要唯一的存在理由。

  **它看得到什麼、看不到什麼。** 它跑在被它監測的機器上，所以它報得出「機器活著但服務不
  通」——也就是實際發生過的那種故障——但報不出「機器關機了」。每天那封摘要就是補這
  個：**信停了就是有事，即使一封告警都沒收到。** 但這一句要誠實：它需要有人注意到一封信**沒
  有**來，而人不擅長這件事。真正的解法是外部的 dead man's switch（健康時往外 ping，對方超時
  才寄信），目前**刻意還沒做**，所以這仍然是整套裡最弱的一個關節。

  第一次跑會寄一封 `monitoring started`，那封信本身就是在測 mail path，而 mail path 是整套
  裡唯一沒辦法靠「看它有沒有動」來驗證的部分。

  ```sh
  tail -20 /opt/homebrew/var/log/nexus-health.log   # 只記事件，平常是空的
  ls -l /opt/homebrew/var/nexus-health.state        # mtime 就是上次執行時間
  cat /opt/homebrew/var/nexus-health.state          # 三行：signature／上次摘要日期／重啟次數
  ```

  log 平常空著是正常的，所以「它到底有沒有在跑」不要從 log 判斷，看 state 檔的 mtime。

  **state 檔是三行的**（2026-08-04 從兩行擴充）：第一行 tier 1 signature，第二行上一封摘要的
  日期 `YYYY-MM-DD`，第三行上次看到的各容器重啟次數。每一條寫入路徑都必須寫滿三行——包含開機
  寬限期那條提早離開的路徑。只寫兩行的話重啟基準每次開機都會被吃掉，而重啟檢查會就這樣安靜地
  停止工作。第二行在 2026-08-04 之前放的是 Unix 時間戳（那時摘要還是滾動式的 heartbeat）；舊值
  不會被當成日期解析，會被讀成「還沒寄過摘要」，於是下一次執行就補寄一封，這是刻意的升級路徑。

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

  這行指令能成功本身就說明了為什麼 tailnet 入口只綁 `127.0.0.1`：它對這個
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

  兩個呼叫端最常踩到的地方（兩者現在 `/api-docs` 和
  [connect-an-agent-client.md](./connect-an-agent-client.md) 都有寫，這裡是部署當下的速查）：

  - **OpenAI 請求裡的 `model` 欄位放的是 capability，不是模型別名。** 送
    `"model": "chat"`，不是 `"model": "qwen7b"`。`RouteChatRequest` 用 capability 查
    routing policy，policy 才決定用哪顆模型。填模型別名會得到 `403 capability_not_issued`，
    而那個訊息**會**告訴你原因：它把送出去的那個名字唸出來、列出這把金鑰可以用的清單
    （和 `GET /v1/models` 同一份），並且明說這個平台的 `model` 欄位收的是 capability
    而不是模型名。（金鑰若帶了 `default_capability`，這個請求會改由那個 capability 服務
    而不是被拒絕，回應的 `X-Capability-Defaulted` 會說是哪一個。）
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

- [ ] **給 `assist` 綁一條 routing policy，否則管理助手不會動。** 側邊那個助手抽屜走的
  是 `assist` 這個 capability，不是 `chat`。沒有策略的話它會回
  `assistant_unavailable`，訊息本身就寫了修法。

  **要指向一顆不會思考的模型。** 會思考的模型在設定表單旁邊產生的不是慢的答案，而是
  沒有答案——實測 16,384 tokens、10 分 53 秒、零個答案 token（[PROGRESS.md](../PROGRESS.md)
  2026-07-27）。先問 Ollama 誰不會思考：

  ```sh
  curl -s http://127.0.0.1:11434/api/tags | \
    python3 -c "import json,sys; [print(m['name'], m.get('capabilities')) for m in json.load(sys.stdin)['models']]"
  ```

  `capabilities` 裡沒有 `thinking` 的那顆就是。在 **Routing policies** 頁面替 `assist` 建一條策略指
  向它即可（別名，不是模型檔名）。

  確認方式有兩個，第二個比第一個重要：

  ```sh
  # 1. 助手真的會回話
  # 在管理 UI 右下角打開抽屜問一句，幾秒內要有回應。

  # 2. assist 沒有外洩到可簽發清單
  curl -H "Tailscale-User-Login: 你的@email" http://127.0.0.1:8001/admin/gateway
  ```

  第二個回的是一個物件，`capabilities` 欄位要是 `["chat"]` 之類、**不含 `assist`** 的清單
  （另一個欄位是 `base_url`）。`assist` 可路由但不可簽發——
  對外簽出去的金鑰不該買到內部管理介面的入場券。這一步之所以要驗，是因為
  `ListCapabilities` 是從「現存的 routing policy」推導清單的，不是讀常數，所以它是整個
  可簽發／可路由拆分裡唯一要手動套過濾的地方（[security.md](../architecture/security.md)
  §7.5.1）。建了策略卻在這裡看到 `assist`，就是那道過濾掉了。

- [ ] 確認新增的兩個容器也起來了：`docker compose ps` 裡 `qdrant` 與 `parser` 都應該
  是 `(healthy)`。

- [ ] **要用知識庫的話**，還需要一個 `embedding` 模型與一條對應的 routing policy，
  而且**啟動時沒有任何東西會檢查這件事**：沒設的話上傳成功、文件狀態停在 `error`、
  搜尋安靜回空。步驟與驗證見
  [upgrade-knowledge-base.md](./upgrade-knowledge-base.md) 第 4、5 部分（那份是為
  既有部署寫的升級流程，但第 4 部分之後的內容首次部署一樣適用）。

---

## 8. 外部協調：NTNU proxy 管理員的四件事（可並行）

照 [deployment.md](../architecture/deployment.md) §5。請對方：

1. 安裝 Tailscale 加入 tailnet，打上 `tag:ntnu-proxy`（ACL 靠這個把它限制在它需要的
   三個埠）。
2. 加兩個 nginx server block（`llm.rcsl.online` 與 `llmapi.rcsl.online`），
   外加 HTTP 轉 HTTPS。設定範本在 deployment.md §5。
3. 兩個名稱各要有憑證。兩者都是單層名字，現有的 `*.rcsl.online` wildcard 憑證
   直接涵蓋，通常把 server block 指過去就好、不必另簽。真的沒有可用的 wildcard
   才簽 Let's Encrypt（port 80 已開，HTTP-01 可直接驗）。
4. 確認：`proxy_buffering off`、`proxy_read_timeout` 夠長、**不記錄 request body**、
   `X-Forwarded-For` 用「覆寫」(`$remote_addr`) 而非附加、並送出 `X-Nexus-Proxy` 共享
   密鑰（等於你的 `proxy_shared_secret`）。

另外可以請他們為兩個名稱給**明確的 A record**，不要只靠 wildcard。這在 2026-08-04
改名之後從「會壞」降級為「比較乾淨」：舊的 `ai.nexus`／`api.nexus` 是兩層名字，靠
wildcard 多層合成才解得出來，任何人在 zone 裡新增一個 `nexus` 節點就會讓兩個入口
同時消失；`llm` 與 `llmapi` 是單層，沒有這個依賴。剩下的理由是 security.md §15.4
的另一半：wildcard 讓**任何**子網域都指向那台 proxy，明確的 A record 收掉的是那個。

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

## 10. AGPL 義務

兩個公開網址都會觸發 AGPL §13：任何連上 `llm.rcsl.online` 或
`llmapi.rcsl.online` 的人，有權取得「正在運行的那個版本」的原始碼，包含在地修改。
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
  容器全部 running、gateway 標 healthy，而 `curl http://<TAILNET_IP>:8000/readyz` 沒有回應。
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

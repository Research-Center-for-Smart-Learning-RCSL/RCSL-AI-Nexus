# 升級 Runbook：知識庫上線

**適用對象：已經在跑的 Mac Studio 部署。** 首次部署請看
[first-deploy.md](./first-deploy.md)，這份只講「從沒有知識庫的版本升到有的版本」
要做什麼、怎麼確認做成了。

這次變更帶進來的東西：

| 新增 | 是什麼 |
|---|---|
| 2 個容器 | `qdrant`（向量索引）、`parser`（隔離的文件解析器）|
| 2 個 volume | `documents`（上傳的檔案與解析出的文字）、`qdrant-data`（索引）|
| 1 個網路 | `parser-net`（internal，只有 parser 與兩個 admin 入口在上面）|
| 2 個 secret | `qdrant_api_key`、`qdrant_read_only_api_key` |
| 1 個 migration | `e5f2c8d71a43`，建 `knowledge_collections` 與 `knowledge_documents` |
| 3 個 Python 依賴 | `pypdf`、`python-docx`、`python-multipart` |

**預估停機時間：一次 `docker compose up -d` 的滾動重啟。** 資料庫 migration 只
新增資料表，不改動既有資料表，所以不需要停機視窗。

> **最容易踩到的一件事先講**：知識庫需要一條 `embedding` capability 的 routing
> policy，**啟動時沒有任何東西會檢查**。沒設的話上傳照樣成功、文件狀態會停在
> `error`、搜尋安靜回空。第 4 部分處理這件事，不要跳過。

---

## 0. 升級前

- [ ] 確認目前服務是健康的（升級失敗時才知道是不是本來就壞的）：

  ```sh
  cd ~/dev/RCSL-AI-Nexus      # 換成實際路徑
  docker compose ps
  ```

  預期：`migrate` 是 `exited (0)`，其餘 `Up`，`postgres`/`redis`/`gateway` 是
  `(healthy)`。

- [ ] 備份資料庫。這次 migration 只加表，但升級前備份是慣例：

  ```sh
  docker compose exec -T postgres pg_dump -U nexus nexus > ~/nexus-backup-$(date +%F).sql
  ls -lh ~/nexus-backup-*.sql
  ```

- [ ] 記下現在的版本，回滾要用：

  ```sh
  git rev-parse --short HEAD
  ```

---

## 1. 取得新程式碼

- [ ] 拉下來：

  ```sh
  git pull
  git log --oneline --grep='knowledge base' --grep='knowledge screen' -i --reverse | head -5
  ```

  應該看到這五個 commit（最舊在上）：

  ```
  Add knowledge base uploads, with the parser in its own container
  Index knowledge base documents and make them searchable
  Ground chat answers on the knowledge base, treating passages as data
  Add the knowledge screen, and a grounding toggle in the chat
  Record the knowledge base, and correct two documents it contradicted
  ```

  **這裡原本寫的是 `git log --oneline -6`，那是這份 runbook 寫出來的那天才成立的。**
  知識庫是 2026-07-29／30 上的，後面已經疊了一百四十幾個 commit，`-6` 現在只會印出最近六個、
  一個都對不上，而看到對不上的人會以為 `git pull` 沒成功。所以改成用訊息去找它們——
  它們在不在，才是這一步要問的事。

---

## 2. 兩把新的 Qdrant 金鑰

Qdrant **預設完全沒有認證**。這兩個檔沒建，`docker compose up` 會直接失敗（刻意
的 fail-closed），而且 `ENV=production` 下佔位字串會讓服務拒絕啟動。

- [ ] 產生兩個**不同**的值：

  ```sh
  printf '%s' "$(openssl rand -base64 32)" > secrets/qdrant_api_key
  printf '%s' "$(openssl rand -base64 32)" > secrets/qdrant_read_only_api_key
  ```

- [ ] 確認兩個檔存在、內容不同、且沒有尾端換行：

  ```sh
  wc -c secrets/qdrant_api_key secrets/qdrant_read_only_api_key
  cmp -s secrets/qdrant_api_key secrets/qdrant_read_only_api_key && echo "錯：兩把一樣" || echo "OK：兩把不同"
  ```

  `wc -c` 應該是 44（`openssl rand -base64 32` 的長度），不是 45。45 表示有尾端
  換行，值就錯了。

**為什麼是兩把而不是一把。** 這是 security.md §6 最小權限切分延伸到向量庫：
gateway 為了回答問題要讀段落，但永遠不該能寫。read-only 那把掛給 gateway，掛載
的目標檔名一樣，所以它的設定讀到的是一把「寫不動」的金鑰。這件事已經實測過：
read-only 金鑰對 `PUT /collections/...` 會被 Qdrant 回 **403**。

- [ ] `.env` 不需要改。新設定（`PARSER_BASE_URL`、`DOCUMENT_STORAGE_PATH`、
  `QDRANT_BASE_URL`）的預設值就是 Compose 裡的服務名，適用於這個部署。想核對可看
  `.env.example` 的 Knowledge base 段落。

---

## 3. 重新建置並啟動

- [ ] **必須重新 build**。這次加了三個 Python 依賴，沿用舊 image 會在 import
  `pypdf` 時掛掉：

  ```sh
  docker compose build
  ```

- [ ] 啟動（會建立兩個新容器、兩個 volume、一個網路，並重啟後端服務）：

  ```sh
  docker compose up -d
  ```

- [ ] 確認 migration 成功：

  ```sh
  docker compose logs migrate | grep 'Running upgrade'
  docker compose ps migrate
  ```

  預期 `exited (0)`，而 `Running upgrade d4e8f1a2b6c9 -> e5f2c8d71a43` 要出現在那串裡。
  **不要用 `tail -20`**：`migrate` 在 alembic 之後還會跑 `db_roles` 與 `provision`，而
  `e5f2c8d71a43` 後面現在還有十個 migration，那一行早就不在最後二十行裡了。

- [ ] 確認全部起來，特別是兩個新的：

  ```sh
  docker compose ps
  ```

  預期 `qdrant` 與 `parser` 都是 `Up ... (healthy)`。

- [ ] 確認新的資料表存在：

  ```sh
  docker compose exec -T postgres psql -U nexus -d nexus -c "\dt knowledge_*"
  ```

  應列出 `knowledge_collections` 與 `knowledge_documents`。

---

## 4. 設定 embedding 模型（**跳過這步知識庫就是壞的**）

沒有這步，上傳會成功、解析會成功、索引會失敗、搜尋回空。而且不會有任何啟動錯誤
告訴你。

- [ ] 在 Mac 上（原生 Ollama，不是容器裡）拉一個 embedding 模型：

  ```sh
  ollama pull nomic-embed-text
  ollama list | grep nomic
  ```

  `nomic-embed-text` 體積小、品質夠用。要換別的也可以，重點是它必須是
  **embedding 模型**，不是 chat 模型：chat 模型對 `/api/embed` 會回 200 但沒有
  `embeddings` 欄位，而 adapter 會拒絕它（這是刻意的，否則索引會填進一堆無意義
  的值而沒人發現）。

- [ ] 確認 Ollama 真的能對它做 embedding：

  ```sh
  curl -s http://127.0.0.1:11434/api/embed \
    -d '{"model":"nomic-embed-text","input":["測試"]}' | head -c 120
  ```

  要看到 `{"model":...,"embeddings":[[...` 。如果沒有 `embeddings` 欄位，換一個
  模型。

- [ ] 在管理 UI（tailnet 入口）**Models** 頁註冊它：

  | 欄位 | 值 |
  |---|---|
  | Alias | `embedder`（自己取，routing policy 要對得上）|
  | Reference | `nomic-embed-text` |
  | Runtime | Ollama |
  | Node | 這台 |
  | Capabilities | 勾 **embedding** |

  註冊後按 **Load**，確認狀態變成 `loaded`。

- [ ] 在 **Routing policies** 頁新增一條 capability = `embedding` 的 policy，候選指向
  `embedder`，requirement 勾 node status `online` + model state `loaded`。

  這條 policy 就是知識庫找 embedding 模型的唯一途徑 —— 系統裡沒有第二個「指定
  模型」的機制，這是刻意的設計。

---

## 5. 驗證（分層做，壞了才知道壞在哪）

按順序，每層失敗就停在那層看第 7 部分。

### 5.1 Qdrant 的認證與權限切分

- [ ] 沒有金鑰應該被拒（從 admin 容器裡打，Qdrant 沒有對外埠）：

  ```sh
  docker compose exec -T admin-tailnet python - <<'PY'
  import httpx
  r = httpx.get("http://qdrant:6333/collections")
  print("no key ->", r.status_code, "(want 401)")
  PY
  ```

- [ ] gateway 的金鑰能讀、不能寫。**這是這次最重要的一項安全驗證**：

  ```sh
  docker compose exec -T gateway python - <<'PY'
  import httpx
  from app.infrastructure.config import get_settings
  key = get_settings().qdrant_api_key
  h = {"api-key": key}
  print("gateway read  ->", httpx.get("http://qdrant:6333/collections", headers=h).status_code, "(want 200)")
  print("gateway write ->", httpx.put("http://qdrant:6333/collections/probe",
        headers=h, json={"vectors":{"size":4,"distance":"Cosine"}}).status_code, "(want 403)")
  PY
  ```

  **write 一定要是 403。** 如果是 200，表示 gateway 拿到了完整金鑰 —— 檢查兩個
  secret 檔是不是填了一樣的值。

### 5.2 Parser 的隔離

- [ ] 它能解析：

  ```sh
  docker compose exec -T admin-tailnet python - <<'PY'
  import httpx
  r = httpx.post("http://parser:8000/extract", content=b"hello",
                 headers={"Content-Type":"application/octet-stream","X-Document-Type":"text/plain"})
  print(r.status_code, r.json())
  PY
  ```

- [ ] 它出不去。**這是 parser 隔離的核心，一定要實測**：

  ```sh
  docker compose exec -T parser python -c "import socket; socket.setdefaulttimeout(5); socket.create_connection(('1.1.1.1',443)); print('失敗：parser 連得到外網')" || echo "OK：parser 沒有外網出口"
  ```

  ```sh
  docker compose exec -T parser python -c "import socket; socket.setdefaulttimeout(5); socket.create_connection(('postgres',5432)); print('失敗：parser 連得到資料庫')" || echo "OK：parser 碰不到 postgres"
  ```

  兩個都必須是 OK。

- [ ] 它沒有憑證可偷：

  ```sh
  docker compose exec -T parser ls /run/secrets 2>&1 || echo "OK：parser 沒有掛任何 secret"
  ```

### 5.3 網路隔離不變式（每次動 compose 都該重驗）

- [ ] gateway 與兩個 admin 入口、以及 parser，不能共用任何網路：

  ```sh
  docker compose config --format json | python3 -c "
  import json,sys
  c=json.load(sys.stdin)['services']
  g=set(c['gateway'].get('networks') or {})
  for s in ('admin-tailnet','admin-public','parser'):
      inter = g & set(c[s].get('networks') or {})
      print(f'gateway ∩ {s} = {sorted(inter) or \"[] OK\"}')
  "
  ```

  三行都必須是空集合。

### 5.4 端到端：上傳一份文件

- [ ] 管理 UI 左側導覽應出現 **Knowledge**。進去，新增一個 collection。
- [ ] 上傳一個小的 PDF 或 txt。
- [ ] 盯著狀態欄，應該依序走過
      `uploaded → extracting → extracted → indexing → indexed`，
      並顯示段落數。表格在有文件處理中時會每 2 秒自動更新。
- [ ] 切到 **Search** 分頁，用文件裡確實有的字句搜尋，應該回傳段落。

### 5.5 端到端：RAG

- [ ] 到 **Chat** 頁，勾選「Answer from the knowledge base」，問一個只有那份文件
      才答得出來的問題。回答應該用到文件內容。
- [ ] 不勾的時候，行為應該跟升級前完全一樣。

---

## 6. 升級後的安全檢查

沿用 security.md §14 的精神：要測，不要猜。

- [ ] Qdrant 沒有對外埠：`docker compose port qdrant 6333` 應該沒有輸出。
- [ ] Parser 沒有對外埠：`docker compose port parser 8000` 應該沒有輸出。
- [ ] gateway 的資料庫帳號寫不了知識庫資料表（自動化測試已涵蓋，
      `backend/tests/integration/test_db_role_grants.py`）。
- [ ] 兩把 Qdrant 金鑰是真值，不是 `.example` 的佔位字串。
- [ ] `documents` volume 要納入你的備份程序 —— **它裝的是團隊未發表的研究資料**，
      是最需要加密備份的那個 volume（security.md §9.1、§9.4）：

  ```sh
  docker run --rm -v rcsl-ai-nexus_documents:/d -v ~:/out alpine \
    tar czf /out/documents-$(date +%F).tar.gz -C /d .
  ```

  `qdrant-data` 不必備份：它可以由 `documents` 重新索引出來（雖然要重跑一次
  embedding）。

---

## 7. 出問題時

| 症狀 | 幾乎都是這個原因 |
|---|---|
| `docker compose up` 抱怨 secret 檔不存在 | 第 2 部分的兩個檔沒建 |
| 服務啟動時報 `Placeholder secrets present in production` | `qdrant_api_key` 還是 `.example` 的內容 |
| 容器 import `pypdf` 失敗 | 沒有重新 `docker compose build`（第 3 部分）|
| `qdrant` 一直 unhealthy | 看 `docker compose logs qdrant`；金鑰檔有尾端換行是常見原因 |
| **文件卡在 `error`，錯誤是 `NoAvailableModelError`** | **第 4 部分沒做**：沒有 `embedding` 的 routing policy |
| 文件卡在 `error`，錯誤是 `RuntimeCapabilityError` | routing policy 指到了 MLX 模型。MLX 不支援 embedding，要指向 Ollama 模型 |
| 文件卡在 `error`，錯誤是 `DocumentParseError` | 那個檔真的解不開（掃描版 PDF 無文字層會是 `indexed` 但 0 段落，不是 error）|
| 搜尋永遠回空，但文件是 `indexed` | 檢查 5.1：gateway 或 admin 的 Qdrant 金鑰不對 |
| 上傳回 413 | 超過 32 MiB 上限，或 nginx 的 `client_max_body_size` 比它小 |
| 文件永遠停在 `extracting` | parser 沒起來或連不到；看 `docker compose logs parser` 與 5.2 |
| 重啟後有文件卡在 `extracting`/`indexing` | 正常：背景工作不跨重啟。下次 `migrate` 跑的時候會把它們改成 `error`，刪掉重傳即可 |

**回滾。** 這次 migration 只新增資料表，舊版程式碼不會碰它們，所以回滾不需要
downgrade 資料庫：

```sh
git checkout <升級前的 commit>
docker compose build
docker compose up -d
docker compose stop qdrant parser
```

新的資料表和 volume 留著不影響舊版運作，之後要重新升級也還在。

**不要用 `alembic downgrade d4e8f1a2b6c9` 來「只清掉知識庫」。** 這份 runbook 寫的時候
`e5f2c8d71a43` 還是 head，現在它後面又疊了十個 migration——model observations
（`f7a9d24c8b16`）、usage prompt tokens（`a1b4e6c2d873`）、retention policies
（`a1b2c3d4e5f6`）、routing policy thinking（`b8c3e5f10d47`）、prompt templates
（`c2f7b90e4a15`）、prompt logs（`a1d6e93c7f52`）、model evaluations
（`d3f5b81a04c7`）、refusals 兩個（`e7b41c9d0a26`、`f3c8a15d27be`）、capability
defaulting（`a4c1e07f2b9d`，目前的 head）。降到 `d4e8f1a2b6c9` 會把這十個連同知識庫
一起往回拆，連同它們的資料。

真的只要清掉知識庫那兩張表，先確認 `alembic current`，再用
`alembic downgrade e5f2c8d71a43`——它只退一步——或者直接 DROP
`knowledge_collections` 與 `knowledge_documents`。

---

## 附錄：這份 runbook 裡哪些是實測過的

寫這份文件時在 Windows 開發機上實際跑過的（不是只看設定檔）：

- Qdrant 容器用 compose 裡的 command 啟動，healthcheck 顯示 `(healthy)`
- 三把金鑰的行為：無金鑰 401、錯金鑰 401、read-only 讀 200 / 寫 **403**、完整
  金鑰寫 200
- Parser 容器在 `read_only` + `cap_drop: ALL` + `mem_limit` 下正常啟動與服務，
  pypdf 與 python-docx 在唯讀檔案系統下都能載入
- Parser 對壞 PDF 回 422、未知類型回 415、不提供 `/openapi.json`

**沒有**、也只能在 Mac Studio 上驗的：真實的 GPU embedding、檢索品質、以及
`parser` 與 `qdrant` 在 macOS 版 Docker Desktop 上的行為（Linux 容器語意相同，
但 Docker Desktop 的網路實作不同）。第 5 部分的每一項就是為了在那台上補齊這些。

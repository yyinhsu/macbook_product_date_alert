# MacBook Pro M5 台灣官網上市通知工具

自動監控 Apple 台灣官網，當 MacBook Pro M5 公布銷售日期時，立即寄 Email 通知你。

---

## 方案一：GitHub Actions（免費、免伺服器）

### 步驟 1：Fork 或 push 到你的 GitHub repo

### 步驟 2：設定 GitHub Secrets

進入你的 repo → **Settings → Secrets and variables → Actions → New repository secret**，新增以下三個 Secrets：

| Secret 名稱 | 說明 |
|------------|------|
| `SMTP_USER` | Gmail 帳號（例如 `yourname@gmail.com`） |
| `SMTP_PASS` | Gmail **應用程式密碼**（非登入密碼，見下方說明） |
| `NOTIFY_TO` | 收件信箱（可填和 SMTP_USER 相同） |

> **如何取得 Gmail 應用程式密碼：**
> 1. 開啟 [Google 帳戶安全性設定](https://myaccount.google.com/security)
> 2. 啟用「兩步驟驗證」
> 3. 搜尋「應用程式密碼」→ 選擇應用程式：郵件 → 產生
> 4. 複製產生的 16 位密碼填入 `SMTP_PASS`

### 步驟 3：啟用 Actions

- 進入 repo 的 **Actions** 頁面
- 若看到提示，點擊「I understand my workflows, go ahead and enable them」

完成！每 30 分鐘自動檢查一次。偵測到 M5 上市後：
1. 寄信通知你
2. 自動在 repo 建立 `notified.flag` 檔案（防止重複寄信）
3. 之後所有執行都會略過

### 手動觸發測試

Actions → **MacBook Pro M5 Monitor** → **Run workflow**

---

## 方案二：本地 / VPS 執行

### 安裝依賴

```bash
pip install -r requirements.txt
```

### 設定 Email

```bash
cp .env.example .env
# 編輯 .env，填入 Gmail 帳號與應用程式密碼
```

### 執行

```bash
# 前景執行
python monitor.py

# 背景執行
nohup python monitor.py &
```

---

## 運作邏輯

1. 每 30 分鐘抓取 Apple 台灣 MacBook Pro 頁面
2. 同時出現 **M5 關鍵字** + **銷售關鍵字**（如「立即購買」）才觸發
3. 觸發後寄送 Email，並寫入 `notified.flag` 防止重複通知

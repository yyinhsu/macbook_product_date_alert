# MacBook Pro M5 台灣官網上市通知工具

自動監控 Apple 台灣官網，當 MacBook Pro M5 公布銷售日期時，立即寄 Email 通知你。

## 快速開始

### 1. 安裝依賴

```bash
pip install -r requirements.txt
```

### 2. 設定 Email

複製範本並填入你的資訊：

```bash
cp .env.example .env
```

編輯 `.env`：

```env
SMTP_USER=your_gmail@gmail.com
SMTP_PASS=your_app_password   # Google 應用程式密碼
NOTIFY_TO=your_email@example.com
CHECK_INTERVAL_SECONDS=3600   # 每小時檢查一次
```

> **Gmail 應用程式密碼設定**：Google 帳戶 → 安全性 → 兩步驟驗證 → 應用程式密碼

### 3. 執行

```bash
python monitor.py
```

程式會持續在背景執行，偵測到上市資訊後寄信並自動停止。

## 背景執行（建議）

```bash
# Linux / macOS
nohup python monitor.py &

# 或使用 screen
screen -S m5-monitor
python monitor.py
# Ctrl+A, D 退出 screen
```

## 運作邏輯

1. 每隔 `CHECK_INTERVAL_SECONDS` 秒抓取 Apple 台灣官網
2. 偵測頁面是否同時出現 **M5 關鍵字** 與 **銷售關鍵字**（如「立即購買」、「加入購物車」）
3. 頁面內容有變化時才進行關鍵字分析（避免重複判斷）
4. 觸發條件成立 → 寄送 Email → 程式結束

## 監控網址

- `https://www.apple.com/tw/shop/buy-mac/macbook-pro`
- `https://www.apple.com/tw/macbook-pro/`

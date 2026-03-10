#!/usr/bin/env python3
"""
MacBook Pro M5 台灣官網上市日期監控工具
當 Apple 台灣官網公布 MacBook Pro M5 銷售日期時，自動寄信通知。

執行模式：
  python monitor.py          → 本地 loop 模式（每 30 分鐘檢查一次）
  python monitor.py --once   → 單次執行（GitHub Actions 用）
"""

import os
import sys
import time
import smtplib
import logging
import hashlib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

# GitHub Actions 環境下不寫 log 檔（stdout 即是 Actions log）
IS_ACTIONS = os.getenv("GITHUB_ACTIONS") == "true"
ONCE_MODE = "--once" in sys.argv or IS_ACTIONS

handlers: list[logging.Handler] = [logging.StreamHandler()]
if not IS_ACTIONS:
    handlers.append(logging.FileHandler("monitor.log", encoding="utf-8"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=handlers,
)
log = logging.getLogger(__name__)

# ── 監控目標 ─────────────────────────────────────────────────────────────────
WATCH_URLS = [
    "https://www.apple.com/tw/shop/buy-mac/macbook-pro",
    "https://www.apple.com/tw/macbook-pro/",
]

# 判斷「已公布銷售日期」的關鍵字（只要頁面出現其中一個就觸發通知）
SALE_KEYWORDS = [
    "立即購買",       # 上架後出現購買按鈕
    "加入購物車",
    "選擇",          # 選擇規格按鈕
    "預購",
    "預訂",
    "現在訂購",
    "即日起",
    "發售",
    "開始銷售",
]

# M5 相關關鍵字（確認是 M5 機型，避免誤報）
M5_KEYWORDS = ["M5", "m5"]

# 「即將推出」文字（若此文字消失，表示可能已開放購買）
COMING_SOON_TEXT = "推出日期，敬請期待：全新機型。"

CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", 1800))  # 預設每 30 分鐘

# 已通知的 flag 檔（存在代表已寄信，避免重複通知）
NOTIFIED_FLAG = Path("notified.flag")

# ── Email 設定（從 .env 或環境變數讀取）──────────────────────────────────────
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
NOTIFY_TO = os.getenv("NOTIFY_TO", "")


def fetch_page(url: str, timeout: int = 15) -> str | None:
    """抓取頁面 HTML，失敗回傳 None。"""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        log.warning("抓取 %s 失敗：%s", url, e)
        return None


def page_fingerprint(html: str) -> str:
    """計算頁面 hash，用來偵測內容是否有變化。"""
    return hashlib.md5(html.encode()).hexdigest()


def check_m5_sale(html: str, url: str) -> tuple[bool, str]:
    """
    回傳 (已上市, 摘要文字)。
    觸發條件（任一）：
      1. 頁面同時含有 M5 關鍵字 + 銷售關鍵字
      2. 頁面含有 M5 關鍵字 + 「推出日期，敬請期待」文字消失
      3. 「推出日期，敬請期待」文字消失（不論是否含 M5 關鍵字）
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)

    has_m5 = any(kw in text for kw in M5_KEYWORDS)
    sale_kw_found = [kw for kw in SALE_KEYWORDS if kw in text]
    coming_soon_gone = COMING_SOON_TEXT not in text

    # 條件 1：有 M5 + 有銷售關鍵字
    if has_m5 and sale_kw_found:
        snippet = _extract_snippet(text, sale_kw_found[0])
        summary = (
            f"頁面：{url}\n"
            f"偵測到 M5 關鍵字：✓\n"
            f"偵測到銷售關鍵字：{sale_kw_found}\n"
            f"相關段落：\n{snippet}"
        )
        return True, summary

    # 條件 2：有 M5 + 「即將推出」文字消失
    if has_m5 and coming_soon_gone:
        summary = (
            f"頁面：{url}\n"
            f"偵測到 M5 關鍵字：✓\n"
            f"「{COMING_SOON_TEXT}」文字已消失！\n"
            f"這可能表示產品即將或已經開放購買，請立即查看官網。"
        )
        return True, summary

    # 條件 3：「即將推出」文字消失（保守通知）
    if coming_soon_gone:
        summary = (
            f"頁面：{url}\n"
            f"「{COMING_SOON_TEXT}」文字已從頁面消失。\n"
            f"\n"
            f"注意：此次偵測未發現 M5 關鍵字或明確銷售資訊，\n"
            f"頁面變動原因不確定，可能是網站改版或其他調整。\n"
            f"建議手動前往官網確認實際狀況，勿直接視為上市通知。"
        )
        return True, summary

    return False, ""


def _extract_snippet(text: str, keyword: str, window: int = 200) -> str:
    """擷取關鍵字前後各 window 個字元作為摘要。"""
    idx = text.find(keyword)
    if idx == -1:
        return ""
    start = max(0, idx - window)
    end = min(len(text), idx + len(keyword) + window)
    return f"...{text[start:end]}..."


def send_email(subject: str, body: str) -> bool:
    """寄送通知信，成功回傳 True。"""
    if not all([SMTP_USER, SMTP_PASS, NOTIFY_TO]):
        log.error("Email 設定不完整，請檢查 .env（SMTP_USER / SMTP_PASS / NOTIFY_TO）")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = NOTIFY_TO

    html_body = f"""
    <html><body>
    <h2 style="color:#1d1d1f;">🍎 MacBook Pro M5 上市通知</h2>
    <pre style="background:#f5f5f7;padding:16px;border-radius:8px;font-size:14px;">{body}</pre>
    <p>請立即前往 <a href="https://www.apple.com/tw/shop/buy-mac/macbook-pro">Apple 台灣官網</a> 查看！</p>
    </body></html>
    """

    msg.attach(MIMEText(body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, NOTIFY_TO, msg.as_string())
        log.info("通知信已寄送至 %s", NOTIFY_TO)
        return True
    except smtplib.SMTPException as e:
        log.error("寄信失敗：%s", e)
        return False


def check_once() -> bool:
    """單次執行：檢查各頁面，回傳是否已寄出通知。"""
    for url in WATCH_URLS:
        log.info("檢查：%s", url)
        html = fetch_page(url)
        if html is None:
            continue

        found, summary = check_m5_sale(html, url)
        if found:
            log.info("偵測到 MacBook Pro M5 上市資訊！")
            subject = "[通知] MacBook Pro M5 已在 Apple 台灣官網上市！"
            if send_email(subject, summary):
                NOTIFIED_FLAG.write_text(datetime.now().isoformat())
                return True
        else:
            log.info("  ↳ 尚未偵測到 M5 銷售資訊")

    return False


def run_loop():
    """本地持續執行模式。"""
    log.info("═" * 60)
    log.info("MacBook Pro M5 監控啟動（loop 模式）")
    log.info("監控網址：%s", WATCH_URLS)
    log.info("檢查間隔：%d 秒", CHECK_INTERVAL_SECONDS)
    log.info("通知信箱：%s", NOTIFY_TO or "（未設定）")
    log.info("═" * 60)

    prev_fingerprints: dict[str, str] = {}

    while True:
        log.info("[%s] 開始檢查...", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        for url in WATCH_URLS:
            html = fetch_page(url)
            if html is None:
                continue

            fp = page_fingerprint(html)
            if prev_fingerprints.get(url) == fp:
                log.info("  ↳ %s 無變化", url)
                continue

            log.info("  ↳ %s 內容有變化，分析中...", url)
            prev_fingerprints[url] = fp

            found, summary = check_m5_sale(html, url)
            if found:
                log.info("偵測到 MacBook Pro M5 上市資訊！")
                subject = "[通知] MacBook Pro M5 已在 Apple 台灣官網上市！"
                if send_email(subject, summary):
                    log.info("通知已送出，程式結束。")
                    return
            else:
                log.info("  ↳ 尚未偵測到 M5 銷售資訊")

        log.info("等待 %d 秒後再次檢查...\n", CHECK_INTERVAL_SECONDS)
        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    if ONCE_MODE:
        # GitHub Actions 單次模式
        if NOTIFIED_FLAG.exists():
            log.info("已於 %s 寄出通知，略過本次檢查。", NOTIFIED_FLAG.read_text())
            sys.exit(0)
        check_once()
    else:
        run_loop()

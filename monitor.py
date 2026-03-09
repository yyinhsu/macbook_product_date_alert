#!/usr/bin/env python3
"""
MacBook Pro M5 台灣官網上市日期監控工具
當 Apple 台灣官網公布 MacBook Pro M5 銷售日期時，自動寄信通知。
"""

import os
import re
import time
import smtplib
import logging
import hashlib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("monitor.log", encoding="utf-8"),
    ],
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

CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", 3600))  # 預設每小時

# ── Email 設定（從 .env 讀取）────────────────────────────────────────────────
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
    條件：頁面同時含有 M5 關鍵字 + 銷售關鍵字。
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)

    has_m5 = any(kw in text for kw in M5_KEYWORDS)
    sale_kw_found = [kw for kw in SALE_KEYWORDS if kw in text]

    if has_m5 and sale_kw_found:
        snippet = _extract_snippet(text, sale_kw_found[0])
        summary = (
            f"頁面：{url}\n"
            f"偵測到 M5 關鍵字：✓\n"
            f"偵測到銷售關鍵字：{sale_kw_found}\n"
            f"相關段落：\n{snippet}"
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


def run():
    log.info("═" * 60)
    log.info("MacBook Pro M5 監控啟動")
    log.info("監控網址：%s", WATCH_URLS)
    log.info("檢查間隔：%d 秒", CHECK_INTERVAL_SECONDS)
    log.info("通知信箱：%s", NOTIFY_TO or "（未設定）")
    log.info("═" * 60)

    notified = False
    prev_fingerprints: dict[str, str] = {}

    while not notified:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log.info("[%s] 開始檢查...", now)

        for url in WATCH_URLS:
            html = fetch_page(url)
            if html is None:
                continue

            fp = page_fingerprint(html)
            if prev_fingerprints.get(url) != fp:
                log.info("  ↳ %s 內容有變化，分析中...", url)
                prev_fingerprints[url] = fp
            else:
                log.info("  ↳ %s 無變化", url)
                continue

            found, summary = check_m5_sale(html, url)
            if found:
                log.info("🎉 偵測到 MacBook Pro M5 上市資訊！")
                log.info(summary)
                subject = f"[通知] MacBook Pro M5 已在 Apple 台灣官網上市！"
                sent = send_email(subject, summary)
                if sent:
                    notified = True
                    break
            else:
                log.info("  ↳ 尚未偵測到 M5 銷售資訊")

        if notified:
            log.info("通知已送出，程式結束。")
            break

        log.info("等待 %d 秒後再次檢查...\n", CHECK_INTERVAL_SECONDS)
        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    run()

"""
monitor.py 的單元測試
使用 unittest.mock 避免真實網路請求與 SMTP 連線。
"""

import smtplib
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# 確保可以 import monitor（不觸發 load_dotenv 副作用）
sys.path.insert(0, str(Path(__file__).parent.parent))
import monitor


# ── check_m5_sale ─────────────────────────────────────────────────────────────

URL = "https://www.apple.com/tw/macbook-pro/"


def _html(body: str) -> str:
    return f"<html><body>{body}</body></html>"


class TestCheckM5Sale(unittest.TestCase):

    def test_no_m5_keyword_returns_false(self):
        html = _html("<p>立即購買 MacBook Air</p>")
        found, _ = monitor.check_m5_sale(html, URL)
        self.assertFalse(found)

    def test_m5_with_sale_keyword_triggers(self):
        html = _html("<p>全新 MacBook Pro M5 立即購買</p>")
        found, summary = monitor.check_m5_sale(html, URL)
        self.assertTrue(found)
        self.assertIn("立即購買", summary)
        self.assertIn(URL, summary)

    def test_m5_with_coming_soon_present_no_trigger(self):
        """有 M5 但「推出日期，敬請期待」仍存在 → 不觸發"""
        html = _html(f"<p>MacBook Pro M5 {monitor.COMING_SOON_TEXT}</p>")
        found, _ = monitor.check_m5_sale(html, URL)
        self.assertFalse(found)

    def test_m5_with_coming_soon_gone_triggers(self):
        """有 M5 且「推出日期，敬請期待」已消失 → 觸發"""
        html = _html("<p>MacBook Pro M5 全新登場</p>")
        found, summary = monitor.check_m5_sale(html, URL)
        self.assertTrue(found)
        self.assertIn("文字已消失", summary)

    def test_all_sale_keywords_trigger(self):
        for kw in monitor.SALE_KEYWORDS:
            with self.subTest(keyword=kw):
                html = _html(f"<p>M5 {kw}</p>")
                found, _ = monitor.check_m5_sale(html, URL)
                self.assertTrue(found, f"關鍵字「{kw}」應觸發但未觸發")

    def test_empty_page_returns_false(self):
        found, _ = monitor.check_m5_sale(_html(""), URL)
        self.assertFalse(found)


# ── page_fingerprint ──────────────────────────────────────────────────────────

class TestPageFingerprint(unittest.TestCase):

    def test_same_content_same_hash(self):
        self.assertEqual(
            monitor.page_fingerprint("hello"),
            monitor.page_fingerprint("hello"),
        )

    def test_different_content_different_hash(self):
        self.assertNotEqual(
            monitor.page_fingerprint("hello"),
            monitor.page_fingerprint("world"),
        )


# ── fetch_page ────────────────────────────────────────────────────────────────

class TestFetchPage(unittest.TestCase):

    @patch("monitor.requests.get")
    def test_success_returns_html(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = "<html>ok</html>"
        mock_get.return_value = mock_resp
        result = monitor.fetch_page("https://example.com")
        self.assertEqual(result, "<html>ok</html>")

    @patch("monitor.requests.get", side_effect=monitor.requests.RequestException("timeout"))
    def test_failure_returns_none(self, _):
        result = monitor.fetch_page("https://example.com")
        self.assertIsNone(result)


# ── send_email ────────────────────────────────────────────────────────────────

class TestSendEmail(unittest.TestCase):

    def test_missing_config_returns_false(self):
        with patch.multiple(monitor, SMTP_USER="", SMTP_PASS="", NOTIFY_TO=""):
            result = monitor.send_email("subject", "body")
        self.assertFalse(result)

    @patch("monitor.smtplib.SMTP")
    def test_successful_send_returns_true(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__ = lambda s: mock_server
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        with patch.multiple(
            monitor,
            SMTP_USER="sender@gmail.com",
            SMTP_PASS="password",
            NOTIFY_TO="recv@gmail.com",
        ):
            result = monitor.send_email("subject", "body")

        self.assertTrue(result)
        mock_server.sendmail.assert_called_once()

    @patch("monitor.smtplib.SMTP")
    def test_smtp_exception_returns_false(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_server.sendmail.side_effect = smtplib.SMTPException("error")
        mock_smtp_cls.return_value.__enter__ = lambda s: mock_server
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        with patch.multiple(
            monitor,
            SMTP_USER="sender@gmail.com",
            SMTP_PASS="password",
            NOTIFY_TO="recv@gmail.com",
        ):
            result = monitor.send_email("subject", "body")

        self.assertFalse(result)


# ── check_once ────────────────────────────────────────────────────────────────

class TestCheckOnce(unittest.TestCase):

    @patch("monitor.send_email", return_value=True)
    @patch("monitor.fetch_page", return_value="<p>M5 立即購買</p>")
    def test_sends_email_and_writes_flag(self, _fetch, _send):
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmp:
            flag = Path(tmp) / "notified.flag"
            with patch.object(monitor, "NOTIFIED_FLAG", flag):
                result = monitor.check_once()
            self.assertTrue(result)
            self.assertTrue(flag.exists())

    @patch("monitor.send_email", return_value=True)
    @patch("monitor.fetch_page", return_value=None)
    def test_all_pages_fail_returns_false(self, _fetch, _send):
        result = monitor.check_once()
        self.assertFalse(result)
        _send.assert_not_called()


if __name__ == "__main__":
    unittest.main()

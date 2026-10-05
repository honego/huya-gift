import json
import os
import unittest
import urllib.error
from unittest.mock import patch

from core.common import push_telegram_message, push_wecom_message


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200):
        self.body = body
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self) -> bytes:
        return self.body

    def getcode(self) -> int:
        return self.status


@patch.dict(
    os.environ,
    {
        "TELEGRAM_BOT_TOKEN": "test-token",
        "TELEGRAM_CHAT_ID": "123456",
        "TELEGRAM_MESSAGE_THREAD_ID": "",
    },
)
class TestTelegramPush(unittest.TestCase):
    @patch("core.common.urllib.request.urlopen")
    def test_missing_token_or_chat_id_skips_request(self, mock_urlopen):
        for token, chat_id in (("", ""), ("test-token", ""), ("", "123456")):
            with self.subTest(token=bool(token), chat_id=bool(chat_id)):
                with patch.dict(
                    os.environ,
                    {
                        "TELEGRAM_BOT_TOKEN": token,
                        "TELEGRAM_CHAT_ID": chat_id,
                    },
                ):
                    self.assertFalse(push_telegram_message("报告"))

        mock_urlopen.assert_not_called()

    @patch("core.common.urllib.request.urlopen")
    def test_success_sends_expected_json_payload(self, mock_urlopen):
        mock_urlopen.return_value = FakeResponse(b'{"ok": true}')

        self.assertTrue(push_telegram_message("虎牙运行报告"))

        request = mock_urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "https://api.telegram.org/bottest-token/sendMessage",
        )
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(
            json.loads(request.data.decode("utf-8")),
            {"chat_id": "123456", "text": "虎牙运行报告"},
        )

    @patch("core.common.urllib.request.urlopen")
    def test_message_thread_id_is_sent_as_integer(self, mock_urlopen):
        os.environ["TELEGRAM_CHAT_ID"] = "-100123456"
        os.environ["TELEGRAM_MESSAGE_THREAD_ID"] = "42"
        mock_urlopen.return_value = FakeResponse(b'{"ok": true}')

        self.assertTrue(push_telegram_message("话题报告"))

        request = mock_urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["message_thread_id"], 42)

    @patch("core.common.log")
    @patch("core.common.urllib.request.urlopen")
    def test_invalid_message_thread_id_is_ignored(self, mock_urlopen, mock_log):
        os.environ["TELEGRAM_MESSAGE_THREAD_ID"] = "not-an-integer"
        mock_urlopen.return_value = FakeResponse(b'{"ok": true}')

        self.assertTrue(push_telegram_message("报告"))

        request = mock_urlopen.call_args.args[0]
        self.assertNotIn(
            "message_thread_id",
            json.loads(request.data.decode("utf-8")),
        )
        self.assertIn("已忽略", str(mock_log.call_args_list))

    @patch("core.common.log")
    @patch("core.common.urllib.request.urlopen")
    def test_api_ok_false_only_reports_failure(self, mock_urlopen, mock_log):
        mock_urlopen.return_value = FakeResponse(
            b'{"ok": false, "error_code": 400, "description": "bad request"}'
        )

        self.assertFalse(push_telegram_message("报告"))
        self.assertIn("ok=false", str(mock_log.call_args))

    @patch("core.common.log")
    @patch("core.common.urllib.request.urlopen")
    def test_url_errors_do_not_raise_or_log_token(self, mock_urlopen, mock_log):
        token = "secret-token-must-not-leak"
        os.environ["TELEGRAM_BOT_TOKEN"] = token
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        errors = (
            urllib.error.URLError(url),
            urllib.error.HTTPError(url, 401, "Unauthorized", None, None),
        )

        for error in errors:
            with self.subTest(error=type(error).__name__):
                mock_urlopen.side_effect = error
                mock_log.reset_mock()

                self.assertFalse(push_telegram_message("报告"))
                self.assertNotIn(token, str(mock_log.call_args_list))

    @patch("core.common.log")
    @patch("core.common.urllib.request.urlopen")
    def test_http_error_only_reports_failure(self, mock_urlopen, mock_log):
        mock_urlopen.return_value = FakeResponse(b"server error", status=500)

        self.assertFalse(push_telegram_message("报告"))
        self.assertIn("HTTP 500", str(mock_log.call_args))

    @patch("core.common.log")
    @patch("core.common.urllib.request.urlopen")
    def test_invalid_json_only_reports_failure(self, mock_urlopen, mock_log):
        mock_urlopen.return_value = FakeResponse(b"not-json")

        self.assertFalse(push_telegram_message("报告"))
        self.assertIn("有效 JSON", str(mock_log.call_args))

    @patch("core.common.push_telegram_message")
    @patch("core.common.write_github_summary")
    @patch("core.common.urllib.request.urlopen")
    def test_wechat_switch_does_not_disable_summary_or_telegram(
        self, mock_urlopen, mock_summary, mock_telegram
    ):
        push_wecom_message(
            {"all_success": True},
            {
                "WECHAT_PUSH": False,
                "WX_WEBHOOK": "https://example.invalid/wecom",
            },
        )

        mock_urlopen.assert_not_called()
        mock_summary.assert_called_once()
        mock_telegram.assert_called_once_with(mock_summary.call_args.args[1])


if __name__ == "__main__":
    unittest.main()

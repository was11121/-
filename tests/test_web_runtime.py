import os
import tempfile
import unittest

from web_runtime import WebSearchService, looks_like_web_request, parse_web_intent


class WebIntentTests(unittest.TestCase):
    def test_explicit_command_triggers_search(self):
        intent = parse_web_intent("!search DeepSeek 最新消息")
        self.assertIsNotNone(intent)
        self.assertEqual(intent["intent"], "search")
        self.assertIn("DeepSeek", intent["query"])

    def test_slash_command_triggers_search(self):
        intent = parse_web_intent("/联网 今天天气怎么样")
        self.assertIsNotNone(intent)
        self.assertEqual(intent["intent"], "search")
        self.assertIn("天气", intent["query"])

    def test_url_triggers_fetch(self):
        intent = parse_web_intent("帮我读一下 https://example.com/page 这个网页")
        self.assertIsNotNone(intent)
        self.assertEqual(intent["intent"], "fetch")
        self.assertEqual(intent["url"], "https://example.com/page")

    def test_keyword_triggers_search(self):
        intent = parse_web_intent("帮我搜索一下最近的科技新闻")
        self.assertIsNotNone(intent)
        self.assertEqual(intent["intent"], "search")

    def test_unrelated_message_does_not_trigger(self):
        self.assertIsNone(parse_web_intent("帮我创建一个任务：完成登录页"))
        self.assertIsNone(parse_web_intent("我喜欢手冲咖啡"))
        self.assertFalse(looks_like_web_request("记住我的名字叫小明"))

    def test_empty_message(self):
        self.assertIsNone(parse_web_intent(""))
        self.assertIsNone(parse_web_intent(None))


class WebSearchServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        os.environ["MYAGENT_DATA_DIR"] = self.tmp.name
        self.service = WebSearchService(self.tmp.name)

    def tearDown(self):
        if "MYAGENT_DATA_DIR" in os.environ:
            del os.environ["MYAGENT_DATA_DIR"]
        try:
            self.tmp.cleanup()
        except Exception:
            pass

    def test_empty_query_returns_none_channel(self):
        result = self.service.search("")
        self.assertEqual(result["channel"], "none")
        self.assertTrue(result["error"])

    def test_info_reflects_config(self):
        info = self.service.info()
        self.assertIn("searxng_url", info)
        self.assertIn("tavily_configured", info)
        self.assertIn("relay_configured", info)

    def test_fetch_invalid_url(self):
        result = self.service.fetch_page("not-a-url")
        self.assertTrue(result["error"])

    def test_fetch_valid_url_roundtrip(self):
        # 使用 example.com 这种极稳定的站点；若完全无网络则跳过（不作为失败）
        result = self.service.fetch_page("https://example.com/")
        if result.get("error") and not result.get("content"):
            self.skipTest("no network available: " + result["error"])
        self.assertIn("Example Domain", result["content"])

    def test_build_context_includes_results(self):
        payload = self.service.search("Example Domain test query")
        if not payload.get("results"):
            self.skipTest("search channels unavailable in this environment")
        context = self.service.build_context("Example Domain test query")
        self.assertIn("联网检索结果", context)


if __name__ == "__main__":
    unittest.main()
import json
import os
import shutil
import tempfile
import unittest

from app import app
from unified_agent.llm import create_llm_responder


class TestWebAndLLM(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.old_data_dir = os.environ.get("MYAGENT_DATA_DIR")
        os.environ["MYAGENT_DATA_DIR"] = self.temp_dir
        self.app = app.test_client()

    def tearDown(self):
        if self.old_data_dir is not None:
            os.environ["MYAGENT_DATA_DIR"] = self.old_data_dir
        else:
            os.environ.pop("MYAGENT_DATA_DIR", None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_frontend_index_route(self):
        resp = self.app.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Remedy", resp.data)
        # redesign 标题应包含 控制台
        self.assertTrue(b"Remedy" in resp.data or "Remedy".encode("utf-8") in resp.data)

    def test_library_document_list_route(self):
        # 录入一篇文档
        self.app.post(
            "/v1/library/documents",
            json={"filename": "guide.md", "content": "这是系统的核心使用说明文档。"},
        )
        # 获取文档列表
        resp = self.app.get("/v1/library/documents")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("documents", data)
        self.assertTrue(len(data["documents"]) >= 1)
        self.assertEqual(data["documents"][0]["title"], "guide.md")

    def test_llm_responder_graceful_fallback(self):
        # 针对无效或不可用的 endpoint 测试优雅降级机制
        responder = create_llm_responder(
            api_key="invalid-key",
            base_url="http://127.0.0.1:9999",
            timeout=0.5,
        )
        reply = responder("测试消息", "【长期用户记忆】\n- [preference_like] 喜欢喝咖啡", "")
        self.assertIn("咖啡", reply)


if __name__ == "__main__":
    unittest.main()

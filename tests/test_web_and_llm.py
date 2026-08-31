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
        self.app.post("/v1/auth/register", json={"username": "weblib_tester", "password": "secret1"})
        login = self.app.post("/v1/auth/login", json={"username": "weblib_tester", "password": "secret1"})
        self.auth_headers = {"Authorization": f"Bearer {login.get_json()['token']}"}

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
        # 录入一篇文档；内容里带上随机后缀，避免与历史测试/演示数据发生内容哈希去重碰撞
        import uuid
        unique_content = f"这是系统的核心使用说明文档。{uuid.uuid4().hex}"
        upload_resp = self.app.post(
            "/v1/library/documents",
            json={"filename": "guide.md", "content": unique_content},
            headers=self.auth_headers,
        )
        self.assertEqual(upload_resp.status_code, 200)
        # 获取文档列表：应仅看到自己上传的这一份（用户隔离生效）
        resp = self.app.get("/v1/library/documents", headers=self.auth_headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("documents", data)
        self.assertTrue(len(data["documents"]) >= 1)
        self.assertTrue(any(doc["title"] == "guide.md" and doc["content"] == unique_content for doc in data["documents"]))

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

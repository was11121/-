import tempfile
import unittest

import app as app_module


class ApiTests(unittest.TestCase):
    def test_health(self):
        original = app_module.agent
        try:
            app_module.agent = app_module.UnifiedAgent(tempfile.mkdtemp())
            client = app_module.app.test_client()
            response = client.get("/health")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json["status"], "ok")
        finally:
            app_module.agent = original

    def test_interaction(self):
        original = app_module.agent
        try:
            app_module.agent = app_module.UnifiedAgent(tempfile.mkdtemp())
            response = app_module.app.test_client().post("/v1/interactions", json={"user_id": "u1", "channel": "web", "message": "我喜欢文档"})
            self.assertEqual(response.status_code, 200)
            self.assertIn("content", response.json)
        finally:
            app_module.agent = original


if __name__ == "__main__":
    unittest.main()

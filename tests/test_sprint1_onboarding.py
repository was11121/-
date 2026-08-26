"""Sprint 1 冷启动：Demo Workspace 注入 / 清空 / 状态查询。"""

import os
import tempfile
import unittest

import app as app_module
from auth_runtime import AuthService
from unified_agent import UnifiedAgent


class Sprint1OnboardingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.original_agent = app_module.agent
        self.original_auth = app_module.auth_service
        self.original_audit = app_module.admin_audit
        app_module.agent = UnifiedAgent(self.tmp)
        app_module.auth_service = AuthService(self.tmp)
        from secretary_runtime import AdminAuditService
        from onboarding_runtime import OnboardingService
        app_module.admin_audit = AdminAuditService(self.tmp)
        app_module.onboarding = OnboardingService(self.tmp)
        self.client = app_module.app.test_client()

    def tearDown(self):
        app_module.agent = self.original_agent
        app_module.auth_service = self.original_auth
        app_module.admin_audit = self.original_audit

    def _register_login(self, username, password):
        self.client.post("/v1/auth/register", json={"username": username, "password": password})
        resp = self.client.post("/v1/auth/login", json={"username": username, "password": password})
        self.assertEqual(resp.status_code, 200, resp.json)
        return {"Authorization": f"Bearer {resp.json['token']}"}, resp.json["user"]

    def test_onboarding_status_before_seed(self):
        headers, user = self._register_login("fresh_user", "secret1")
        resp = self.client.get("/v1/me/onboarding", headers=headers)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json["demo_seeded"])

    def test_seed_demo_creates_memories_task_patch_document(self):
        headers, user = self._register_login("seed_demo_user", "secret1")
        resp = self.client.post("/v1/me/onboarding/seed-demo", headers=headers)
        self.assertEqual(resp.status_code, 200, resp.json)
        summary = resp.json["summary"]
        # 至少：3 记忆 + 1 文档 + 3 任务 + 1 补丁（draft）
        self.assertEqual(summary["memories"], 3)
        self.assertEqual(summary["document"], 1)
        self.assertEqual(summary["tasks"], 3)
        self.assertEqual(summary["patches"], 1)

    def test_seed_demo_is_idempotent(self):
        headers, _ = self._register_login("idem_user", "secret1")
        first = self.client.post("/v1/me/onboarding/seed-demo", headers=headers)
        self.assertEqual(first.status_code, 200)
        self.assertFalse(first.json.get("already_seeded"))
        # 第二次：直接返回已存在
        second = self.client.post("/v1/me/onboarding/seed-demo", headers=headers)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.json["already_seeded"])

    def test_clear_demo_removes_seeded_data(self):
        headers, _ = self._register_login("clear_demo_user", "secret1")
        self.client.post("/v1/me/onboarding/seed-demo", headers=headers)
        # 验证确实有数据
        mem = self.client.get(f"/v1/users/clear_demo_user/memory", headers=headers).json["memories"]
        self.assertEqual(len(mem), 3)
        # 清空
        resp = self.client.post("/v1/me/onboarding/clear-demo", headers=headers)
        self.assertEqual(resp.status_code, 200, resp.json)
        self.assertTrue(resp.json["success"])
        # 验证无记忆
        mem = self.client.get(f"/v1/users/clear_demo_user/memory", headers=headers).json["memories"]
        self.assertEqual(len(mem), 0)
        # 状态回到 false
        status = self.client.get("/v1/me/onboarding", headers=headers).json
        self.assertFalse(status["demo_seeded"])

    def test_clear_demo_when_not_seeded_is_safe(self):
        headers, _ = self._register_login("never_seeded", "secret1")
        resp = self.client.post("/v1/me/onboarding/clear-demo", headers=headers)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json.get("already_cleared"))

    def test_onboarding_requires_auth(self):
        resp = self.client.get("/v1/me/onboarding")
        self.assertEqual(resp.status_code, 401)
        resp2 = self.client.post("/v1/me/onboarding/seed-demo")
        self.assertEqual(resp2.status_code, 401)

    def test_demo_data_includes_pending_patch(self):
        """demo 应该留一个 draft 补丁，让用户练习确认流程。"""
        headers, _ = self._register_login("patch_demo_user", "secret1")
        self.client.post("/v1/me/onboarding/seed-demo", headers=headers)
        resp = self.client.get("/v1/workspaces/default/dashboard", headers=headers)
        patches = resp.json.get("patches", [])
        drafts = [p for p in patches if p["status"] == "draft"]
        self.assertGreaterEqual(len(drafts), 1, "demo 应当留下至少一个 draft 补丁供用户练习")


if __name__ == "__main__":
    unittest.main()

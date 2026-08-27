"""Sprint 2 补丁体验：列表 / 创建工作区、看板补丁工作流、批量 confirm/rollback 流程。"""

import json
import tempfile
import unittest

import app as app_module
from auth_runtime import AuthService
from unified_agent import UnifiedAgent


class Sprint2PatchesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.original_agent = app_module.agent
        self.original_auth = app_module.auth_service
        self.original_audit = app_module.admin_audit
        self.original_onboarding = getattr(app_module, "onboarding", None)
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
        app_module.onboarding = self.original_onboarding

    def _register_login(self, username, password):
        self.client.post("/v1/auth/register", json={"username": username, "password": password})
        resp = self.client.post("/v1/auth/login", json={"username": username, "password": password})
        self.assertEqual(resp.status_code, 200, resp.json)
        return {"Authorization": f"Bearer {resp.json['token']}"}, resp.json["user"]

    # ---------- 2.5 工作区列表 / 创建 ----------

    def test_list_workspaces_includes_default(self):
        headers, user = self._register_login("ws_user_a", "secret1")
        resp = self.client.get("/v1/workspaces", headers=headers)
        self.assertEqual(resp.status_code, 200)
        ids = {w["id"] for w in resp.json["workspaces"]}
        # default 不再全局共享：用户可见的是自己的 default::<username> 工作区
        self.assertIn(f"default::{user['username']}", ids)
        self.assertNotIn("default", ids, "旧全局共享 default 不应再出现在普通用户列表中")

    def test_create_workspace_assigns_owner(self):
        headers, user = self._register_login("ws_owner_a", "secret1")
        resp = self.client.post("/v1/workspaces", headers=headers, json={"name": "英语学习"})
        self.assertEqual(resp.status_code, 200, resp.json)
        ws = resp.json["workspace"]
        self.assertEqual(ws["name"], "英语学习")
        self.assertEqual(ws["owner_user_id"], user["username"])
        # 列表中应能查到
        listing = self.client.get("/v1/workspaces", headers=headers).json["workspaces"]
        ids = {w["id"] for w in listing}
        self.assertIn(ws["id"], ids)

    def test_create_workspace_rejects_empty_name(self):
        headers, _ = self._register_login("ws_owner_b", "secret1")
        resp = self.client.post("/v1/workspaces", headers=headers, json={"name": "   "})
        self.assertEqual(resp.status_code, 400)

    def test_workspaces_require_auth(self):
        resp = self.client.get("/v1/workspaces")
        self.assertEqual(resp.status_code, 401)
        resp2 = self.client.post("/v1/workspaces", json={"name": "x"})
        self.assertEqual(resp2.status_code, 401)

    def test_user_b_cannot_see_user_a_workspaces(self):
        headers_a, _ = self._register_login("ws_isolation_a", "secret1")
        ws = self.client.post("/v1/workspaces", headers=headers_a, json={"name": "私密 A"}).json["workspace"]
        headers_b, _ = self._register_login("ws_isolation_b", "secret1")
        listing = self.client.get("/v1/workspaces", headers=headers_b).json["workspaces"]
        ids = {w["id"] for w in listing}
        self.assertNotIn(ws["id"], ids, "B 用户不应看到 A 的私有工作区")

    # ---------- 2.6 看板补丁工作流（基础，已存在但需验证） ----------

    def test_patch_confirm_and_rollback_cycle(self):
        headers, _ = self._register_login("patch_user_a", "secret1")
        # 通过 demo 注入会创建 patch draft
        self.client.post("/v1/me/onboarding/seed-demo", headers=headers)
        dashboard = self.client.get("/v1/workspaces/default/dashboard", headers=headers).json
        drafts = [p for p in dashboard["patches"] if p["status"] == "draft"]
        self.assertGreater(len(drafts), 0, "demo 至少应留下 1 个 draft patch")
        target = drafts[0]
        # 确认应用
        confirm = self.client.post(f"/v1/patches/{target['id']}/confirm", headers=headers)
        self.assertEqual(confirm.status_code, 200, confirm.json)
        # 验证已 applied
        after = self.client.get("/v1/workspaces/default/dashboard", headers=headers).json
        applied = [p for p in after["patches"] if p["id"] == target["id"]]
        self.assertEqual(applied[0]["status"], "applied")
        # 回滚
        rb = self.client.post(f"/v1/patches/{target['id']}/rollback", headers=headers)
        self.assertEqual(rb.status_code, 200, rb.json)
        after2 = self.client.get("/v1/workspaces/default/dashboard", headers=headers).json
        rolled = [p for p in after2["patches"] if p["id"] == target["id"]]
        self.assertEqual(rolled[0]["status"], "rolled_back")

    def test_double_confirm_returns_409(self):
        headers, _ = self._register_login("patch_user_b", "secret1")
        self.client.post("/v1/me/onboarding/seed-demo", headers=headers)
        target = [p for p in self.client.get("/v1/workspaces/default/dashboard", headers=headers).json["patches"] if p["status"] == "draft"][0]
        first = self.client.post(f"/v1/patches/{target['id']}/confirm", headers=headers)
        self.assertEqual(first.status_code, 200)
        second = self.client.post(f"/v1/patches/{target['id']}/confirm", headers=headers)
        self.assertEqual(second.status_code, 409)

    def test_rollback_non_applied_returns_409(self):
        headers, _ = self._register_login("patch_user_c", "secret1")
        self.client.post("/v1/me/onboarding/seed-demo", headers=headers)
        target = [p for p in self.client.get("/v1/workspaces/default/dashboard", headers=headers).json["patches"] if p["status"] == "draft"][0]
        rb = self.client.post(f"/v1/patches/{target['id']}/rollback", headers=headers)
        self.assertEqual(rb.status_code, 409)


if __name__ == "__main__":
    unittest.main()

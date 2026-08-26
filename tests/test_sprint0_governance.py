"""Sprint 0 基础治理：导出 / 删除账号 / 审计日志 / LLM 状态 / 401 拦截。"""

import json
import tempfile
import unittest

import app as app_module
from auth_runtime import AuthService
from unified_agent import UnifiedAgent


class Sprint0GovernanceTests(unittest.TestCase):
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
        self.original_onboarding = app_module.onboarding
        app_module.onboarding = OnboardingService(self.tmp)
        self.client = app_module.app.test_client()

    def tearDown(self):
        app_module.agent = self.original_agent
        app_module.auth_service = self.original_auth
        app_module.admin_audit = self.original_audit
        app_module.onboarding = self.original_onboarding

    def _register_login(self, username, password, role=None):
        payload = {"username": username, "password": password}
        if role:
            payload["role"] = role  # 即便传 admin 也应被服务端强制为 user
        self.client.post("/v1/auth/register", json=payload)
        resp = self.client.post(
            "/v1/auth/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(resp.status_code, 200, resp.json)
        token = resp.json["token"]
        return {"Authorization": f"Bearer {token}"}, resp.json["user"]

    # ---------- 0.3 /v1/me/export ----------

    def test_me_export_returns_user_payload(self):
        headers, user = self._register_login("alice_export", "secret1")
        # 触发一些数据
        self.client.post(
            "/v1/interactions",
            headers=headers,
            json={"user_id": user["username"], "message": "我喜欢喝拿铁咖啡"},
        )
        resp = self.client.get("/v1/me/export", headers=headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json
        self.assertEqual(data["user"]["username"], user["username"])
        self.assertGreaterEqual(len(data["memories"]), 1)
        self.assertGreaterEqual(len(data["interactions"]), 1)
        # Content-Disposition 应包含文件名
        cd = resp.headers.get("Content-Disposition", "")
        self.assertIn("attachment", cd)
        self.assertIn(".json", cd)

    def test_me_export_without_token_is_unauthorized(self):
        resp = self.client.get("/v1/me/export")
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json.get("code"), "UNAUTHORIZED")

    # ---------- 0.4 DELETE /v1/me ----------

    def test_delete_account_removes_user_and_data(self):
        headers, user = self._register_login("victim_user", "secret1")
        username = user["username"]
        # 先写点记忆 / 交互
        self.client.post(
            "/v1/interactions",
            headers=headers,
            json={"user_id": username, "message": "我喜欢骑自行车通勤"},
        )
        # 删账号
        resp = self.client.delete("/v1/me", headers=headers)
        self.assertEqual(resp.status_code, 200, resp.json)
        self.assertTrue(resp.json["success"])
        self.assertEqual(resp.json["username"], username)
        self.assertGreaterEqual(resp.json["data_counts"]["memories"], 1)
        # token 应失效
        after = self.client.get("/v1/auth/me", headers=headers)
        self.assertEqual(after.status_code, 401)
        # auth 表中用户不再存在
        self.assertIsNone(app_module.auth_service.get_user_by_id(username))

    def test_delete_account_clears_secretary_and_library_for_reregister(self):
        headers, user = self._register_login("reuse_user", "secret1")
        username = user["username"]
        seed = self.client.post("/v1/me/onboarding/seed-demo", headers=headers)
        self.assertEqual(seed.status_code, 200, seed.json)
        ws = self.client.post("/v1/workspaces", headers=headers, json={"name": "orphan-ws"})
        self.assertEqual(ws.status_code, 200, ws.json)
        del_resp = self.client.delete("/v1/me", headers=headers)
        self.assertEqual(del_resp.status_code, 200, del_resp.json)
        headers2, _ = self._register_login("reuse_user", "secret1")
        docs = self.client.get("/v1/library/documents", headers=headers2)
        self.assertEqual(docs.status_code, 200, docs.json)
        self.assertEqual(len(docs.json.get("documents") or []), 0)
        dash = self.client.get("/v1/workspaces/default/dashboard", headers=headers2)
        self.assertEqual(dash.status_code, 200, dash.json)
        self.assertEqual(dash.json.get("patches") or [], [])
        workspaces = self.client.get("/v1/workspaces", headers=headers2)
        self.assertEqual(workspaces.status_code, 200, workspaces.json)
        ids = [w.get("id") for w in (workspaces.json.get("workspaces") or [])]
        self.assertIn("default", ids)
        self.assertTrue(all(not str(i).startswith("ws-") for i in ids))

    def test_delete_account_requires_double_confirm_via_input(self):
        # 这条用例实际是 UI 行为；后端只保证删一次成功即可
        headers, user = self._register_login("charlie_del", "secret1")
        resp = self.client.delete("/v1/me", headers=headers)
        self.assertEqual(resp.status_code, 200)
        # 再次删应 404
        resp2 = self.client.delete("/v1/me", headers=headers)
        self.assertEqual(resp2.status_code, 401)  # token 已失效，按 401 处理

    def test_cannot_delete_only_admin(self):
        # 唯一管理员（remedy_admin）不能被删除
        headers, admin = self._register_login("remedy_admin", "Remedy@2025")
        resp = self.client.delete("/v1/me", headers=headers)
        # 必须拒绝
        self.assertIn(resp.status_code, (403, 400))
        self.assertIn("管理员", resp.json.get("error", ""))

    # ---------- 0.5 /v1/admin/audit ----------

    def test_admin_audit_records_view_profile(self):
        # 准备：alice2 用户 + 一些数据
        self.client.post("/v1/auth/register", json={"username": "alice_audited", "password": "secret1"})
        user_headers, _ = self._register_login("alice_audited", "secret1")
        self.client.post(
            "/v1/interactions",
            headers=user_headers,
            json={"user_id": "alice_audited", "message": "我喜欢拿铁"},
        )
        # 管理员查看画像
        admin_headers, _ = self._register_login("remedy_admin", "Remedy@2025")
        before_resp = self.client.get("/v1/admin/audit", headers=admin_headers)
        before_total = before_resp.json.get("total", 0) if before_resp.status_code == 200 else 0
        self.client.get("/v1/admin/users/alice_audited/profile", headers=admin_headers)
        # 再查审计
        resp = self.client.get("/v1/admin/audit?target_user=alice_audited", headers=admin_headers)
        self.assertEqual(resp.status_code, 200)
        items = resp.json.get("items", [])
        self.assertGreater(len(items), 0)
        actions = {it["action"] for it in items}
        self.assertIn("view_profile", actions)
        self.assertGreater(resp.json["total"], before_total)

    def test_admin_audit_search_interactions_creates_record(self):
        self._register_login("audited_chat", "secret1")
        user_headers, _ = self._register_login("audited_chat", "secret1")
        self.client.post("/v1/interactions", headers=user_headers, json={"user_id": "audited_chat", "message": "拿铁"})
        admin_headers, _ = self._register_login("remedy_admin", "Remedy@2025")
        self.client.get("/v1/admin/users/audited_chat/interactions?q=拿铁", headers=admin_headers)
        resp = self.client.get("/v1/admin/audit?action=search_interactions", headers=admin_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any(it["target_user"] == "audited_chat" for it in resp.json["items"]))

    def test_admin_audit_requires_admin(self):
        headers, _ = self._register_login("normal_audit_user", "secret1")
        resp = self.client.get("/v1/admin/audit", headers=headers)
        self.assertEqual(resp.status_code, 403)
        resp2 = self.client.get("/v1/admin/audit")
        self.assertEqual(resp2.status_code, 401)

    # ---------- 0.2 /health llm 字段 ----------

    def test_health_returns_llm_info(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json
        self.assertIn("llm", data)
        self.assertIn("configured", data["llm"])
        self.assertIn("mode", data["llm"])

    # ---------- 0.1 401 拦截链路（前后端合作点，服务端最少需确保鉴权码正确） ----------

    def test_invalid_token_returns_401_with_code(self):
        resp = self.client.get("/v1/auth/me", headers={"Authorization": "Bearer invalid_xxx"})
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json.get("code"), "UNAUTHORIZED")


if __name__ == "__main__":
    unittest.main()

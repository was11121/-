import tempfile
import unittest

import app as app_module
from auth_runtime import AuthService
from unified_agent import UnifiedAgent


class AuthAndIsolationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.original_agent = app_module.agent
        self.original_auth = app_module.auth_service
        app_module.agent = UnifiedAgent(self.tmp)
        app_module.auth_service = AuthService(self.tmp)
        self.client = app_module.app.test_client()

    def tearDown(self):
        app_module.agent = self.original_agent
        app_module.auth_service = self.original_auth

    def _login(self, username, password):
        response = self.client.post("/v1/auth/login", json={"username": username, "password": password})
        self.assertEqual(response.status_code, 200, response.json)
        token = response.json["token"]
        return {"Authorization": f"Bearer {token}"}, response.json["user"]

    def _register(self, username, password, nickname=None):
        payload = {"username": username, "password": password}
        if nickname:
            payload["nickname"] = nickname
        resp = self.client.post("/v1/auth/register", json=payload)
        return resp

    # --- 新品牌：仅 remedy_admin 为管理员，alice/bob 已彻底移除 ---

    def test_remedy_admin_exists_and_alice_bob_removed(self):
        # remedy_admin 可登录且为 admin
        headers, user = self._login("remedy_admin", "Remedy@2025")
        self.assertEqual(user["role"], "admin")
        self.assertEqual(user["username"], "remedy_admin")
        # alice / bob 登录必须失败
        for legacy in ("alice", "bob"):
            r = self.client.post("/v1/auth/login", json={"username": legacy, "password": "123456"})
            self.assertEqual(r.status_code, 400, r.json)
        # 通过 AuthService 直接查也为空
        svc = app_module.auth_service
        self.assertIsNone(svc.get_user_by_id("u_alice"))
        self.assertIsNone(svc.get_user_by_id("u_bob"))

    def test_register_forces_user_role(self):
        # 即使尝试传 role=admin 也会被强制为 user
        resp = self.client.post("/v1/auth/register", json={"username": "evil", "password": "secret1", "role": "admin"})
        # 后端忽略 role 字段，仍成功且为 user
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json["user"]["role"], "user")
        # 再尝试用 evil 登录验证
        headers, user = self._login("evil", "secret1")
        self.assertEqual(user["role"], "user")

    def test_login_issues_token_and_me(self):
        # 使用 remedy_admin 验证登录 /me 链路（原 alice 用例已迁移至 remedy_admin）
        headers, user = self._login("remedy_admin", "Remedy@2025")
        self.assertEqual(user["role"], "admin")
        me = self.client.get("/v1/auth/me", headers=headers)
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json["user"]["username"], "remedy_admin")

    def test_me_without_token_is_unauthorized(self):
        response = self.client.get("/v1/auth/me")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json["code"], "UNAUTHORIZED")

    def test_register_creates_standard_user(self):
        response = self._register("carol", "secret1", nickname="Carol")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["user"]["role"], "user")
        self.assertEqual(response.json["user"]["username"], "carol")

    def test_register_rejects_duplicate_username(self):
        # 先注册一次 carol，再重复注册应 400
        self._register("dupuser", "secret1")
        response = self.client.post("/v1/auth/register", json={"username": "dupuser", "password": "secret1"})
        self.assertEqual(response.status_code, 400)

    def test_wrong_password_rejected(self):
        # remedy_admin 错误密码
        response = self.client.post("/v1/auth/login", json={"username": "remedy_admin", "password": "badpass"})
        self.assertEqual(response.status_code, 400)

    def test_user_cannot_read_other_user_memory(self):
        self._register("alice2", "secret1")
        self._register("bob2", "secret1")
        alice_headers, _ = self._login("alice2", "secret1")
        self.client.post(
            "/v1/interactions",
            headers=alice_headers,
            json={"user_id": "spoofed", "message": "我喜欢喝拿铁咖啡"},
        )
        bob_headers, _ = self._login("bob2", "secret1")
        blocked = self.client.get("/v1/users/alice2/memory", headers=bob_headers)
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(blocked.json["code"], "FORBIDDEN")

    def test_user_cannot_forget_other_user_memory(self):
        self._register("alice3", "secret1")
        self._register("bob3", "secret1")
        alice_headers, _ = self._login("alice3", "secret1")
        self.client.post(
            "/v1/interactions",
            headers=alice_headers,
            json={"user_id": "alice3", "message": "我喜欢喝美式咖啡"},
        )
        memories = self.client.get("/v1/users/alice3/memory", headers=alice_headers).json["memories"]
        self.assertTrue(memories)
        bob_headers, _ = self._login("bob3", "secret1")
        blocked = self.client.post(
            f"/v1/users/alice3/memory/{memories[0]['id']}/forget",
            headers=bob_headers,
        )
        self.assertEqual(blocked.status_code, 403)

    def test_user_cannot_access_admin_routes(self):
        self._register("normal1", "secret1")
        headers, _ = self._login("normal1", "secret1")
        listing = self.client.get("/v1/admin/users", headers=headers)
        self.assertEqual(listing.status_code, 403)
        profile = self.client.get("/v1/admin/users/remedy_admin/profile", headers=headers)
        self.assertEqual(profile.status_code, 403)
        # 进一步：普通用户访问 admin interactions 也 403
        blocked = self.client.get("/v1/admin/users/normal1/interactions", headers=headers)
        self.assertEqual(blocked.status_code, 403)

    def test_admin_can_list_users_and_read_any_profile(self):
        self._register("alice4", "secret1")
        alice_headers, _ = self._login("alice4", "secret1")
        self.client.post(
            "/v1/interactions",
            headers=alice_headers,
            json={"user_id": "alice4", "message": "我喜欢喝拿铁咖啡"},
        )
        admin_headers, admin = self._login("remedy_admin", "Remedy@2025")
        self.assertEqual(admin["role"], "admin")
        listing = self.client.get("/v1/admin/users", headers=admin_headers)
        self.assertEqual(listing.status_code, 200)
        usernames = {item["username"] for item in listing.json["users"]}
        self.assertIn("alice4", usernames)
        self.assertIn("remedy_admin", usernames)
        # 人格雷达字段必须存在
        for u in listing.json["users"]:
            self.assertIn("personality", u)
            self.assertIn("scores", u["personality"])
        profile = self.client.get("/v1/admin/users/alice4/profile", headers=admin_headers)
        self.assertEqual(profile.status_code, 200)
        self.assertGreaterEqual(len(profile.json["memories"]), 1)
        cross = self.client.get("/v1/users/alice4/memory", headers=admin_headers)
        self.assertEqual(cross.status_code, 200)
        self.assertGreaterEqual(len(cross.json["memories"]), 1)

    def test_admin_interactions_search_delete_annotate(self):
        # 准备用户与两条对话
        self._register("chatuser", "secret1")
        user_headers, _ = self._login("chatuser", "secret1")
        self.client.post("/v1/interactions", headers=user_headers, json={"user_id": "chatuser", "message": "我喜欢拿铁"})
        self.client.post("/v1/interactions", headers=user_headers, json={"user_id": "chatuser", "message": "今天天气不错"})
        admin_headers, _ = self._login("remedy_admin", "Remedy@2025")
        # 检索分页
        resp = self.client.get("/v1/admin/users/chatuser/interactions?limit=20&offset=0", headers=admin_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(resp.json["total"], 2)
        self.assertIn("interactions", resp.json)
        # 关键词过滤
        resp2 = self.client.get("/v1/admin/users/chatuser/interactions?q=拿铁", headers=admin_headers)
        self.assertEqual(resp2.status_code, 200)
        self.assertTrue(any("拿铁" in (it["message"] or "") for it in resp2.json["interactions"]))
        # 删除
        iid = resp.json["interactions"][0]["id"]
        del_resp = self.client.delete(f"/v1/admin/interactions/{iid}", headers=admin_headers)
        self.assertEqual(del_resp.status_code, 200)
        self.assertTrue(del_resp.json.get("success"))
        # 标注（需指定 user_id）
        remaining = self.client.get("/v1/admin/users/chatuser/interactions", headers=admin_headers).json["interactions"]
        if remaining:
            ann = self.client.post(f"/v1/admin/interactions/{remaining[0]['id']}/annotate", headers=admin_headers, json={"user_id": "chatuser", "tag": "重要", "note": "需跟进"})
            self.assertEqual(ann.status_code, 200)
            self.assertTrue(ann.json.get("feedback_id") or ann.json.get("success"))

    def test_logged_in_interaction_locks_user_id(self):
        self._register("alice5", "secret1")
        self._register("bob5", "secret1")
        headers, _ = self._login("alice5", "secret1")
        self.client.post(
            "/v1/interactions",
            headers=headers,
            json={"user_id": "bob5", "message": "我喜欢喝拿铁咖啡"},
        )
        alice_mem = self.client.get("/v1/users/alice5/memory", headers=headers)
        self.assertEqual(alice_mem.status_code, 200)
        self.assertTrue(alice_mem.json["memories"])
        bob_headers, _ = self._login("bob5", "secret1")
        bob_mem = self.client.get("/v1/users/bob5/memory", headers=bob_headers)
        self.assertEqual(bob_mem.status_code, 200)
        self.assertEqual(bob_mem.json["memories"], [])

    def test_logout_invalidates_token(self):
        self._register("logoutuser", "secret1")
        headers, _ = self._login("logoutuser", "secret1")
        out = self.client.post("/v1/auth/logout", headers=headers)
        self.assertEqual(out.status_code, 200)
        me = self.client.get("/v1/auth/me", headers=headers)
        self.assertEqual(me.status_code, 401)

    def test_admin_route_without_token_is_unauthorized(self):
        response = self.client.get("/v1/admin/users")
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()

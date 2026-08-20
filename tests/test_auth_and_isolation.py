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

    def test_login_issues_token_and_me(self):
        headers, user = self._login("alice", "123456")
        self.assertEqual(user["role"], "user")
        me = self.client.get("/v1/auth/me", headers=headers)
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json["user"]["username"], "alice")

    def test_me_without_token_is_unauthorized(self):
        response = self.client.get("/v1/auth/me")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json["code"], "UNAUTHORIZED")

    def test_register_creates_standard_user(self):
        response = self.client.post(
            "/v1/auth/register",
            json={"username": "carol", "password": "secret1", "nickname": "Carol"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["user"]["role"], "user")
        self.assertEqual(response.json["user"]["username"], "carol")

    def test_register_rejects_duplicate_username(self):
        response = self.client.post("/v1/auth/register", json={"username": "alice", "password": "secret1"})
        self.assertEqual(response.status_code, 400)

    def test_wrong_password_rejected(self):
        response = self.client.post("/v1/auth/login", json={"username": "alice", "password": "badpass"})
        self.assertEqual(response.status_code, 400)

    def test_user_cannot_read_other_user_memory(self):
        alice_headers, _ = self._login("alice", "123456")
        self.client.post(
            "/v1/interactions",
            headers=alice_headers,
            json={"user_id": "spoofed", "message": "我喜欢喝拿铁咖啡"},
        )
        bob_headers, _ = self._login("bob", "123456")
        blocked = self.client.get("/v1/users/alice/memory", headers=bob_headers)
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(blocked.json["code"], "FORBIDDEN")

    def test_user_cannot_forget_other_user_memory(self):
        alice_headers, _ = self._login("alice", "123456")
        self.client.post(
            "/v1/interactions",
            headers=alice_headers,
            json={"user_id": "alice", "message": "我喜欢喝美式咖啡"},
        )
        memories = self.client.get("/v1/users/alice/memory", headers=alice_headers).json["memories"]
        self.assertTrue(memories)
        bob_headers, _ = self._login("bob", "123456")
        blocked = self.client.post(
            f"/v1/users/alice/memory/{memories[0]['id']}/forget",
            headers=bob_headers,
        )
        self.assertEqual(blocked.status_code, 403)

    def test_user_cannot_access_admin_routes(self):
        headers, _ = self._login("alice", "123456")
        listing = self.client.get("/v1/admin/users", headers=headers)
        self.assertEqual(listing.status_code, 403)
        profile = self.client.get("/v1/admin/users/bob/profile", headers=headers)
        self.assertEqual(profile.status_code, 403)

    def test_admin_can_list_users_and_read_any_profile(self):
        alice_headers, _ = self._login("alice", "123456")
        self.client.post(
            "/v1/interactions",
            headers=alice_headers,
            json={"user_id": "alice", "message": "我喜欢喝拿铁咖啡"},
        )
        admin_headers, admin = self._login("admin", "admin123")
        self.assertEqual(admin["role"], "admin")
        listing = self.client.get("/v1/admin/users", headers=admin_headers)
        self.assertEqual(listing.status_code, 200)
        usernames = {item["username"] for item in listing.json["users"]}
        self.assertIn("alice", usernames)
        self.assertIn("admin", usernames)
        profile = self.client.get("/v1/admin/users/alice/profile", headers=admin_headers)
        self.assertEqual(profile.status_code, 200)
        self.assertGreaterEqual(len(profile.json["memories"]), 1)
        cross = self.client.get("/v1/users/alice/memory", headers=admin_headers)
        self.assertEqual(cross.status_code, 200)
        self.assertGreaterEqual(len(cross.json["memories"]), 1)

    def test_logged_in_interaction_locks_user_id(self):
        headers, _ = self._login("alice", "123456")
        self.client.post(
            "/v1/interactions",
            headers=headers,
            json={"user_id": "bob", "message": "我喜欢喝拿铁咖啡"},
        )
        alice_mem = self.client.get("/v1/users/alice/memory", headers=headers)
        self.assertEqual(alice_mem.status_code, 200)
        self.assertTrue(alice_mem.json["memories"])
        bob_headers, _ = self._login("bob", "123456")
        bob_mem = self.client.get("/v1/users/bob/memory", headers=bob_headers)
        self.assertEqual(bob_mem.status_code, 200)
        self.assertEqual(bob_mem.json["memories"], [])

    def test_logout_invalidates_token(self):
        headers, _ = self._login("alice", "123456")
        out = self.client.post("/v1/auth/logout", headers=headers)
        self.assertEqual(out.status_code, 200)
        me = self.client.get("/v1/auth/me", headers=headers)
        self.assertEqual(me.status_code, 401)

    def test_admin_route_without_token_is_unauthorized(self):
        response = self.client.get("/v1/admin/users")
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()

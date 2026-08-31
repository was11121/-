import json
import os
import shutil
import tempfile
import unittest

from app import app
from memory_runtime import MemoryService
from secretary_runtime import SecretaryService


class TestBugFixes(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.old_data_dir = os.environ.get("MYAGENT_DATA_DIR")
        os.environ["MYAGENT_DATA_DIR"] = self.temp_dir
        self.app = app.test_client()
        self.app.post("/v1/auth/register", json={"username": "fixes_tester", "password": "secret1"})
        login = self.app.post("/v1/auth/login", json={"username": "fixes_tester", "password": "secret1"})
        self.auth_headers = {"Authorization": f"Bearer {login.get_json()['token']}"}

    def tearDown(self):
        if self.old_data_dir is not None:
            os.environ["MYAGENT_DATA_DIR"] = self.old_data_dir
        else:
            os.environ.pop("MYAGENT_DATA_DIR", None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_bug1_upload_unsupported_file_returns_400_not_500(self):
        # 上传不支持的二进制文件扩展名
        response = self.app.post(
            "/v1/library/documents",
            data={"file": (b"dummy binary", "invalid_file.exe")},
            content_type="multipart/form-data",
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertIn("error", data)

    def test_bug2_patch_confirm_creates_actual_task_and_rollback_removes_it(self):
        sec = SecretaryService(self.temp_dir)
        project_id = "test_proj"
        sec.ensure_project(project_id)

        # 初始看板任务数为0
        dash_before = sec.dashboard(project_id)
        self.assertEqual(len(dash_before["tasks"]), 0)

        # 创建一个新建任务补丁
        patch = sec.create_patch(
            project_id,
            target_type="task",
            target_id="new",
            operation="create",
            proposed_change="完成架构文档编写",
            evidence="用户要求",
            created_by="tester",
        )
        self.assertEqual(patch["status"], "draft")

        # 确认补丁
        confirmed = sec.confirm_patch(patch["id"], actor="admin")
        self.assertEqual(confirmed["status"], "applied")

        # 确认后看板中应真实存在该任务
        dash_after = sec.dashboard(project_id)
        self.assertEqual(len(dash_after["tasks"]), 1)
        self.assertEqual(dash_after["tasks"][0]["title"], "完成架构文档编写")
        self.assertEqual(dash_after["counts"]["todo"], 1)

        # 回滚补丁
        rolled_back = sec.rollback_patch(patch["id"], actor="admin")
        self.assertEqual(rolled_back["status"], "rolled_back")

        # 回滚后看板中的任务应被清除
        dash_rollback = sec.dashboard(project_id)
        self.assertEqual(len(dash_rollback["tasks"]), 0)

    def test_bug3_memory_search_filters_irrelevant_results(self):
        mem = MemoryService(self.temp_dir)
        user_id = "user_coffee_test"
        
        # 记录不相关记忆
        mem.record_interaction(user_id, "我最喜欢的颜色是蓝色", "好的，记住了")
        mem.record_interaction(user_id, "我平时喜欢喝拿铁咖啡", "好的，已记录您的饮食习惯")

        # 搜索“咖啡”
        coffee_results = mem.search_user_memory(user_id, query="咖啡", limit=10)
        self.assertTrue(len(coffee_results) >= 1)
        for item in coffee_results:
            self.assertIn("咖啡", item["content"])
            self.assertNotIn("蓝色", item["content"])

        # 搜索“蓝色”
        color_results = mem.search_user_memory(user_id, query="蓝色", limit=10)
        self.assertTrue(len(color_results) >= 1)
        for item in color_results:
            self.assertIn("蓝色", item["content"])
            self.assertNotIn("咖啡", item["content"])


if __name__ == "__main__":
    unittest.main()

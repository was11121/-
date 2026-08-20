import tempfile
import unittest
from pathlib import Path

from unified_agent import InteractionEnvelope, UnifiedAgent


class UnifiedAgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.agent = UnifiedAgent(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_memory_isolated_by_user(self):
        self.agent.handle_interaction(InteractionEnvelope(user_id="alice", channel="web", message="我喜欢手冲咖啡"))
        self.assertTrue(self.agent.search_user_memory("alice", "咖啡"))
        self.assertEqual(self.agent.search_user_memory("bob", "咖啡"), [])

    def test_feedback_and_forget(self):
        result = self.agent.handle_interaction(InteractionEnvelope(user_id="alice", channel="web", message="记住我喜欢蓝色"))
        memory_id = result.memory_events[0].memory_id
        self.agent.apply_feedback("alice", "confirm", memory_id)
        self.assertTrue(self.agent.forget_memory("alice", memory_id))
        self.assertEqual(self.agent.search_user_memory("alice", "蓝色"), [])

    def test_library_deduplicates_and_cites(self):
        first = self.agent.ingest_document("notes.txt", "Python 是一种编程语言。", source="notes")
        duplicate = self.agent.ingest_document("copy.txt", "Python 是一种编程语言。", source="copy")
        self.assertEqual(first["status"], "indexed")
        self.assertEqual(duplicate["status"], "duplicate")
        results = self.agent.search_library("Python")
        self.assertEqual(results[0]["source"], "notes")

    def test_secretary_patch_requires_confirmation(self):
        result = self.agent.handle_interaction(InteractionEnvelope(user_id="alice", channel="web", workspace_id="p1", message="创建一个任务：完成登录页"))
        self.assertTrue(result.requires_confirmation)
        patch = result.secretary_events[0]["data"]
        self.assertEqual(patch["status"], "draft")
        applied = self.agent.confirm_patch(patch["id"], "alice")
        self.assertEqual(applied["status"], "applied")
        rolled_back = self.agent.rollback_patch(patch["id"], "alice")
        self.assertEqual(rolled_back["status"], "rolled_back")


if __name__ == "__main__":
    unittest.main()

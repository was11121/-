import os
import tempfile
import unittest

os.environ["PERSONALITY_DISABLE_BERT"] = "1"

from personality_runtime.heuristic import heuristic_scores
from personality_runtime.traits import derive_work_style
from unified_agent import InteractionEnvelope, UnifiedAgent


class PersonalityCoachingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.agent = UnifiedAgent(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_five_traits_are_listed(self):
        profile = self.agent.get_personality_profile("alice")
        names = [item["id"] for item in profile["traits"]]
        self.assertEqual(
            names,
            ["openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"],
        )

    def test_delay_language_marks_procrastination(self):
        text = "我又在拖延了，明天再说吧，先不管截止日期，好焦虑不想动，完美主义让我开工不了。"
        scores = heuristic_scores(text)
        self.assertLess(scores["conscientiousness"], 0.5)
        self.assertGreater(scores["neuroticism"], 0.5)
        work = derive_work_style(scores)
        self.assertIn(work["execution_style"], {"procrastinator", "mixed"})
        self.assertIn(work["thinking_style"], {"affective", "balanced"})

    def test_plan_language_marks_execution(self):
        text = "我今天就把清单做完，立刻执行计划，守住截止时间，保持冷静自律。"
        scores = heuristic_scores(text)
        self.assertGreater(scores["conscientiousness"], 0.55)
        work = derive_work_style(scores)
        self.assertIn(work["execution_style"], {"executor", "mixed"})

    def test_interaction_returns_coaching_not_persona_play(self):
        result = self.agent.handle_interaction(
            InteractionEnvelope(
                user_id="alice",
                channel="web",
                message="我又在拖延了，明天再说，先不管这件事，心里很焦虑。",
            )
        )
        coaching = [tip for tip in result.tips if tip.type == "coaching"]
        self.assertTrue(coaching)
        personality = result.metadata["personality"]
        self.assertIn("conscientiousness", personality["scores"])
        self.assertTrue(personality["playbook"]["today_focus"])
        self.assertNotIn("扮演", result.content)

    def test_personality_route_isolated(self):
        self.agent.handle_interaction(
            InteractionEnvelope(user_id="alice", channel="web", message="我喜欢马上把计划做完，今天就执行。")
        )
        alice = self.agent.get_personality_profile("alice")
        bob = self.agent.get_personality_profile("bob")
        self.assertGreaterEqual(alice["samples"], 1)
        self.assertEqual(bob["samples"], 0)


if __name__ == "__main__":
    unittest.main()

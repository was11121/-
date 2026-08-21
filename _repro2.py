# -*- coding: utf-8 -*-
"""Minimal repro: does UnifiedAgent leave a locked users.db handle?"""
import gc
import os
import tempfile

from unified_agent import InteractionEnvelope, UnifiedAgent

tmp = tempfile.TemporaryDirectory()
print("tmp:", tmp.name)
agent = UnifiedAgent(tmp.name)
print("agent created, db exists:", os.path.exists(os.path.join(tmp.name, "users.db")))
p = agent.get_personality_profile("alice")
print("profile ok samples:", p["samples"])
agent = None
gc.collect()
try:
    tmp.cleanup()
    print("cleanup OK")
except Exception as e:
    print("cleanup FAILED:", type(e).__name__, e)
finally:
    print("tmp still exists:", os.path.exists(tmp.name))
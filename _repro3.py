# -*- coding: utf-8 -*-
"""Repro2: does explicit engine dispose fix the lock?"""
import gc
import os
import tempfile

from unified_agent import InteractionEnvelope, UnifiedAgent
from storage.db import get_engine, reset_engine

tmp = tempfile.TemporaryDirectory()
print("tmp:", tmp.name)
agent = UnifiedAgent(tmp.name)
print("db exists:", os.path.exists(os.path.join(tmp.name, "users.db")))
p = agent.get_personality_profile("alice")
print("profile samples:", p["samples"])
agent = None
gc.collect()
reset_engine()
try:
    tmp.cleanup()
    print("cleanup OK after reset_engine")
except Exception as e:
    print("cleanup FAILED even after reset:", type(e).__name__, e)
finally:
    print("tmp exists now:", os.path.exists(tmp.name))
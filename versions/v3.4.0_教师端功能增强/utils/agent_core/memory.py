# -*- coding: utf-8 -*-
"""Agent 记忆兼容层：复用现有 agent_memory 表。"""
from __future__ import annotations
from utils import agent_memory_service as service

def remember(session, key, value, category="general", importance=5):
    return service.remember_preference(session, key, value, category, importance)

def recall(session, key, category=None):
    return service.recall_preference(session, key, category)

def forget(session, key, category=None):
    return service.forget_preference(session, key, category)

def list_memories(session, category=None):
    return service.get_all_preferences(session, category)

def allowed_preferences(session):
    return service.auto_applied_preferences(session)

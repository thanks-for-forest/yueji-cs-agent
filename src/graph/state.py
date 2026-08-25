"""LangGraph 编排：AgentState 定义（Supervisor-Worker 模式的状态载体）。

字段与 orchestrator.handle 的返回语义对齐，保证图路径与旧路径行为一致。
"""
from __future__ import annotations

from typing import TypedDict


class AgentState(TypedDict, total=False):
    # 输入
    session_id: str
    user_message: str
    session: dict  # sessions 表行（含 meta）

    # 预处理结果
    blocked: bool
    blocked_reason: str  # sensitive | injection
    emotion: str
    need_transfer: bool
    intent: str
    confidence: float
    route_method: str
    memory: list[dict]  # 历史（不含本轮用户消息）

    # Agent 执行结果
    retrieved: list | None
    result: dict  # AgentResult.to_dict()

    # 输出
    payload: dict  # 与旧 handle 返回结构一致

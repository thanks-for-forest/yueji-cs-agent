"""工具注册表：所有可被 LLM 调用的工具集中注册，统一导出 schema 与执行入口。"""
from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


class Tool:
    """一个可被 LLM 调用的工具。run 返回 JSON 字符串（供模型阅读）。

    user_context=True 的工具会在执行时注入当前会话的 user_id（来自注册表上下文，
    不出现在 LLM 的工具契约中），用于订单归属校验等数据隔离。
    """

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict,
        func: Callable[..., Awaitable[Any]],
        user_context: bool = False,
    ):
        self.name = name
        self.description = description
        self.parameters = parameters
        self._func = func
        self.user_context = user_context

    def schema(self) -> dict:
        return {"name": self.name, "description": self.description, "parameters": self.parameters}

    async def run(self, **kwargs: Any) -> str:
        ctx = kwargs.pop("_ctx", None) or {}
        if self.user_context and ctx.get("user_id"):
            kwargs.setdefault("user_id", ctx["user_id"])
        result = await self._func(**kwargs)
        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def schemas(self) -> list[dict]:
        return [t.schema() for t in self._tools.values()]

    def has(self, name: str) -> bool:
        return name in self._tools

    async def execute(self, name: str, arguments: dict, context: dict | None = None) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False)
        try:
            return await tool.run(**arguments, _ctx=context or {})
        except TypeError as e:
            logger.warning("工具 %s 参数错误: %s", name, e)
            return json.dumps({"error": f"参数错误: {e}"}, ensure_ascii=False)
        except Exception as e:  # noqa: BLE001
            logger.exception("工具 %s 执行失败", name)
            return json.dumps({"error": f"执行失败: {e}"}, ensure_ascii=False)


_registry: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    """懒加载单例：组装全部工具。"""
    global _registry
    if _registry is None:
        from src.tools.aftersale_tools import build_aftersale_tools
        from src.tools.order_tools import build_order_tools
        from src.tools.product_tools import build_product_tools

        _registry = ToolRegistry()
        for t in build_order_tools() + build_aftersale_tools() + build_product_tools():
            _registry.register(t)
    return _registry

"""统一的 OpenAI 兼容 LLM 调用器，支持提示词编排与优雅降级。"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
import urllib.error
from typing import Callable

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_API_KEY = ""


def create_llm_responder(
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    timeout: float = 30.0,
    fallback_responder: Callable[[str, str, str, str], str] | None = None,
) -> Callable[[str, str, str, str], str]:
    """创建统一的 LLM Responder 函数，兼容 OpenAI Chat Completions 规范。"""

    def responder(message: str, user_context: str, library_context: str, web_context: str = "摘要为空") -> str:
        # 优先从 runtime_settings 热读取（跨 gunicorn worker 生效），回退 os.environ
        try:
            from storage import runtime_settings as _rs
            _raw = _rs.load_raw()
        except Exception:
            _raw = {}
        key = api_key or _raw.get("MODEL_API_KEY") or os.getenv("MODEL_API_KEY") or DEFAULT_API_KEY
        url = (base_url or _raw.get("BASE_URL") or os.getenv("BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        m = model or _raw.get("CURRENT_MODEL") or os.getenv("CURRENT_MODEL") or DEFAULT_MODEL

        # 构建统一 System Prompt
        system_parts = [
            "你是一个具备长期用户画像记忆、本地权威知识库与项目秘书执行能力的统一现实补丁智能体（Unified Agent）。",
            "【行为准则】",
            "1. 语言亲切、专业、精炼，使用 Markdown 格式。",
            "2. 当提供【长期用户记忆】时，请自然结合用户的个人偏好、需求、习惯或身份进行个性化回应。",
            "3. 当提供【本地知识库参考】时，请以此为权威依据，严谨引用并回答，并在回答中说明依据来源。",
            "4. 如果用户提出了关于任务创建、项目进展同步等请求，请给予清晰正面的答复，并告知后台已生成待确认现实补丁或同步草稿。",
            "5. 若提供【秘书督促档案】：不要用某种人格口吻说话，不要扮演用户。根据短板督促、根据长处加码，给出今天可执行的下一步。",
            "6. 当提供【联网检索结果】时，说明这是实时检索到的信息，回答用户关于时事、搜索、网页内容、行情等问题时要基于这些结果，并标注信息检索时间；若联网结果为空或无关，如实说明无法实时确认，不要编造来源。",
        ]

        if user_context:
            system_parts.append(f"\n{user_context}")

        if library_context:
            system_parts.append(f"\n【本地知识库参考】\n{library_context}")

        if web_context and web_context != "摘要为空":
            system_parts.append(f"\n【联网检索结果】\n{web_context}")

        system_prompt = "\n".join(system_parts)

        # 构建 Chat Completions API 路径
        endpoint = f"{url}/v1/chat/completions" if not url.endswith("/v1") else f"{url}/chat/completions"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "User-Agent": "Remedy/1.0",
        }

        body = {
            "model": m,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message},
            ],
            "temperature": 0.7,
            "max_tokens": 2048,
        }

        req = urllib.request.Request(
            endpoint,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                choices = data.get("choices") or []
                if choices and "message" in choices[0]:
                    content = choices[0]["message"].get("content", "")
                    if content:
                        return content
        except Exception as exc:
            logger.warning("LLM call to %s failed (%s), falling back to rule-based responder", endpoint, exc)

        # 优雅降级
        if fallback_responder:
            return fallback_responder(message, user_context, library_context, web_context or "")

        # 默认降级格式
        if library_context:
            return f"我在知识库中为您检索到以下相关资料：\n\n{library_context}\n\n关于您的问题「{message}」，请参考上述内容。"
        if user_context:
            return f"已结合您的个性化偏好进行处理：\n{user_context}\n\n针对您的问题「{message}」，我已收到并处理完成。"
        return f"我已收到您的消息：{message}"

    return responder

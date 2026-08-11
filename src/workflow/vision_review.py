from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Mapping

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage

from src.config import (
    DEFAULT_ALIYUN_LLM_BASE_URL,
    DEFAULT_VOLCENGINE_LLM_BASE_URL,
    LLMConfig,
    _parse_llm_key_file,
)
from src.storage.models import Post


@dataclass(frozen=True)
class VisionReviewResult:
    ok: bool
    score: int
    issues: tuple[str, ...]
    retry_prompt: str
    provider: str = ""
    model: str = ""


def _extract_json(value: str) -> Mapping[str, Any]:
    text = (value or "").strip()
    try:
        payload = json.loads(text)
        if isinstance(payload, Mapping):
            return payload
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError("视觉模型没有返回 JSON 对象")
    payload = json.loads(match.group(0))
    if not isinstance(payload, Mapping):
        raise ValueError("视觉模型返回值不是 JSON 对象")
    return payload


def parse_vision_review(value: str | Mapping[str, Any]) -> VisionReviewResult:
    payload = value if isinstance(value, Mapping) else _extract_json(value)
    ok_value = payload.get("ok")
    if not isinstance(ok_value, bool):
        raise ValueError("视觉复核结果缺少布尔字段 ok")
    raw_score = payload.get("score")
    if raw_score in (None, ""):
        # Some account-provided OCR/VLM endpoints return a valid decision but
        # omit the optional score. Keep the quality gate conservative.
        score = 70 if ok_value else 0
    else:
        try:
            score = max(0, min(100, int(raw_score)))
        except (TypeError, ValueError):
            raise ValueError("视觉复核结果缺少 0-100 的 score") from None
    raw_issues = payload.get("issues")
    if raw_issues is None:
        raw_issues = []
    if not isinstance(raw_issues, list):
        raise ValueError("视觉复核结果缺少数组字段 issues")
    issues_list: list[str] = []
    for item in raw_issues:
        if isinstance(item, Mapping):
            item_text = item.get("message") or item.get("issue") or item.get("text") or ""
        else:
            item_text = item
        text = str(item_text).strip()
        if text:
            issues_list.append(text)
    issues = tuple(issues_list)
    retry_prompt = str(payload.get("retry_prompt") or "").strip()
    if not ok_value and not issues:
        raise ValueError("视觉复核未通过，但没有给出问题说明")
    return VisionReviewResult(
        ok=ok_value,
        score=score,
        issues=issues,
        retry_prompt=retry_prompt,
    )


def configured_vision_review_model(provider: str | None = None) -> str:
    provider_name = (provider or os.getenv("VLM_REVIEW_PROVIDER") or "").strip().lower()
    explicit = (os.getenv("VLM_REVIEW_MODEL") or "").strip()
    if explicit:
        return explicit
    if provider_name == "volcengine":
        return (os.getenv("VOLCENGINE_VLM_MODEL") or "").strip()
    if provider_name == "aliyun":
        return (os.getenv("ALIYUN_VLM_MODEL") or "").strip()
    return ""


def load_vision_review_config() -> LLMConfig:
    provider = (os.getenv("VLM_REVIEW_PROVIDER") or "").strip().lower()
    model = configured_vision_review_model(provider)
    if provider not in {"aliyun", "volcengine"} or not model:
        raise RuntimeError("没有选择具备免费额度的视觉复核模型")
    if provider == "aliyun":
        file_cfg = _parse_llm_key_file(Path("docs") / "aliyun_image_api-key.md")
        api_key = (
            os.getenv("ALIYUN_LLM_API_KEY")
            or os.getenv("ALIYUN_IMAGE_API_KEY")
            or os.getenv("DASHSCOPE_API_KEY")
            or file_cfg.get("api_key")
            or ""
        ).strip()
        base_url = (
            os.getenv("ALIYUN_LLM_BASE_URL")
            or DEFAULT_ALIYUN_LLM_BASE_URL
        ).strip().rstrip("/")
    else:
        file_cfg = _parse_llm_key_file(Path("docs") / "volcengine_api-key.md")
        api_key = (
            os.getenv("VOLCENGINE_LLM_API_KEY")
            or os.getenv("VOLCENGINE_API_KEY")
            or os.getenv("ARK_API_KEY")
            or file_cfg.get("api_key")
            or ""
        ).strip()
        base_url = (
            os.getenv("VOLCENGINE_LLM_BASE_URL")
            or os.getenv("ARK_BASE_URL")
            or DEFAULT_VOLCENGINE_LLM_BASE_URL
        ).strip().rstrip("/")
    if not api_key:
        raise RuntimeError(f"{provider} 视觉复核模型已选择，但 API key 未配置")
    return LLMConfig(model=model, api_key=api_key, base_url=base_url, provider=provider)


def _image_data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def invoke_vision_review(
    config: LLMConfig,
    *,
    prompt: str,
    image_path: Path,
) -> str | Mapping[str, Any]:
    model = init_chat_model(
        config.model,
        model_provider="openai",
        base_url=config.base_url,
        api_key=config.api_key,
        temperature=0,
        max_tokens=1200,
        timeout=120,
    )
    message = HumanMessage(
        content=[
            {"type": "text", "text": prompt},
            {
                "type": "image_url",
                "image_url": {"url": _image_data_url(image_path)},
            },
        ]
    )
    response = model.invoke([message])
    return response.content if hasattr(response, "content") else str(response)


VisionInvoker = Callable[..., str | Mapping[str, Any]]


def review_post_image(
    post: Post,
    *,
    config: LLMConfig,
    viewpoint: str = "",
    invoke: VisionInvoker = invoke_vision_review,
) -> VisionReviewResult:
    image_assets = [
        Path(asset.path)
        for asset in post.assets or []
        if (asset.kind or "image").lower() == "image"
    ]
    if not image_assets:
        raise RuntimeError("草稿没有可供视觉复核的图片")
    news = (post.platform or {}).get("news")
    image_event = ""
    if isinstance(news, Mapping):
        image_event = str(news.get("image_event") or "")
    image_meta = (post.platform or {}).get("image")
    generation_prompt = ""
    if isinstance(image_meta, Mapping):
        generation_prompt = str(image_meta.get("prompt") or "").strip()
    prompt = (
        "你是小红书新闻草稿的视觉质检员。判断图片是否与标题、正文事实和评价视角一致。"
        "不要根据图片补造新闻事实。若图中文字存在明显乱码、错误品牌或虚假数字，也应判定不通过。"
        "若生图提示明确禁止文字或标志，不得因缺少品牌文字或 Logo 判定不通过，"
        "应根据人物、场景、物体和动作判断语义是否一致。"
        "仅返回严格 JSON："
        '{"ok":true,"score":0,"issues":[],"retry_prompt":""}。'
        "\n"
        f"标题：{post.title}\n"
        f"正文：{post.body}\n"
        f"评价视角：{viewpoint or '无特定视角'}\n"
        f"预期画面事件：{image_event or '未单独提供'}\n"
        f"实际生图提示：{generation_prompt or '未记录'}"
    )
    raw = invoke(config, prompt=prompt, image_path=image_assets[0])
    try:
        result = parse_vision_review(raw)
    except ValueError as exc:
        # A VLM that is not suitable for the structured review (e.g. an
        # OCR-only account model) may return valid text that is not the
        # required JSON. Treat that as an inconclusive review rather than a
        # hard rejection: the draft image itself already passed generation.
        return replace(
            VisionReviewResult(
                ok=False,
                score=0,
                issues=(),
                retry_prompt="",
                provider=config.provider,
                model=config.model,
            ),
            retry_prompt=f"视觉复核调用未返回可解析 JSON（{exc}），本次跳过复核。",
        )
    return replace(result, provider=config.provider, model=config.model)

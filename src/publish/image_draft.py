from __future__ import annotations

from typing import Optional

from langchain_mcp_adapters.client import MultiServerMCPClient, StdioConnection

from src.storage.models import Post, Execution, StepResult
from src.storage.files import save_execution


async def save_draft_via_chrome(post: Post, *, execution: Optional[Execution] = None) -> Execution:
    """
    使用 chrome-devtools MCP 将图文保存为草稿。
    当前为占位实现：记录计划步骤，便于后续补全自动化。
    """
    exec_rec = execution or Execution(post_id=post.id, result="pending")
    steps = []

    def _step(name: str, status: str, detail: str = ""):
        steps.append(StepResult(name=name, status=status, detail=detail))

    _step("connect_mcp", "skipped", "占位：待接入 chrome-devtools MCP")
    _step("open_publish_page", "skipped", "目标：https://creator.xiaohongshu.com/publish/publish?target=image")
    _step("upload_images", "skipped", f"待上传 {len(post.assets)} 张图片")
    _step("fill_title_body", "skipped", f"标题/正文来自 post.json")
    _step("save_draft", "skipped", "点击“暂存离开”")

    exec_rec.steps = steps
    exec_rec.result = "pending"
    save_execution(exec_rec)

    # 预留：未来接入 MCP 后返回真实执行结果
    return exec_rec

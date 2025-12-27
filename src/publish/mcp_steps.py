from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import List, Optional

from langchain_core.tools import BaseTool

from src.publish.mcp_driver import chrome_client
from src.storage.files import evidence_dir, save_execution
from src.storage.models import Execution, Post, StepResult

TARGET_URL = "https://creator.xiaohongshu.com/publish/publish?target=image"


def _get_tool(tools: List[BaseTool], name: str) -> BaseTool:
    for t in tools:
        if t.name.endswith(name):
            return t
    raise KeyError(f"tool not found: {name}")


def _parse_uid(snapshot_text: str, keyword: str) -> Optional[str]:
    for line in snapshot_text.splitlines():
        if keyword in line and "uid=" in line:
            m = re.search(r"uid=([\\w_]+)", line)
            if m:
                return m.group(1)
    return None


def _js_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _extract_pages(resp: object) -> list[tuple[int, str, bool]]:
    texts: list[str] = []
    if isinstance(resp, list):
        for item in resp:
            if isinstance(item, dict):
                text = item.get("text")
                if text:
                    texts.append(text)
            elif isinstance(item, str):
                texts.append(item)
    elif isinstance(resp, dict):
        text = resp.get("text")
        if text:
            texts.append(text)
    pages: list[tuple[int, str, bool]] = []
    for text in texts:
        for line in text.splitlines():
            m = re.match(r"^(\d+):\s+(.*?)(\s+\[selected\])?$", line.strip())
            if m:
                pages.append((int(m.group(1)), m.group(2).strip(), bool(m.group(3))))
    return pages


def _pick_page_idx(
    pages: list[tuple[int, str, bool]], target_url: str
) -> Optional[int]:
    for idx, url, _ in pages:
        if target_url in url:
            return idx
    for idx, _, selected in pages:
        if selected:
            return idx
    if pages:
        return pages[-1][0]
    return None



async def run_save_draft(
    post: Post,
    *,
    assets: Optional[list[str]] = None,
    dry_run: bool = False,
    login_hold: int = 0,
) -> Execution:
    """
    通过 chrome-devtools MCP 完成：打开发布页 -> 上传图片 -> 填写标题/正文 -> 暂存离开（可 dry-run 跳过填/暂存）。
    """
    exec_rec = Execution(post_id=post.id, result="pending")
    steps: List[StepResult] = []

    def _step(name: str, status: str, detail: str = ""):
        steps.append(StepResult(name=name, status=status, detail=detail))

    client = chrome_client()
    tools = await client.get_tools(server_name="chrome")

    new_page = _get_tool(tools, "new_page")
    list_pages = _get_tool(tools, "list_pages")
    select_page = _get_tool(tools, "select_page")
    wait_for = _get_tool(tools, "wait_for")
    navigate_page = _get_tool(tools, "navigate_page")
    take_snapshot = _get_tool(tools, "take_snapshot")
    take_screenshot = _get_tool(tools, "take_screenshot")
    upload_file = _get_tool(tools, "upload_file")
    fill_tool = _get_tool(tools, "fill")
    evaluate_script = _get_tool(tools, "evaluate_script")

    try:
        _step("list_pages", "in_progress", "")
        pages_resp = await list_pages.ainvoke({})
        pages = _extract_pages(pages_resp)
        steps[-1].detail = f"pages={pages}"
        steps[-1].status = "success"

        page_idx = _pick_page_idx(pages, TARGET_URL)
        if page_idx is None:
            _step("open_page", "in_progress", TARGET_URL)
            res_new = await new_page.ainvoke({"url": TARGET_URL, "timeout": 30000})
            steps[-1].detail = str(res_new)
            steps[-1].status = "success"
            pages = _extract_pages(res_new)
            page_idx = _pick_page_idx(pages, TARGET_URL)

        if page_idx is not None:
            _step("select_page", "in_progress", "")
            try:
                await select_page.ainvoke({"pageIdx": int(page_idx), "bringToFront": True})
                steps[-1].detail = f"selected page {page_idx}; pages={pages}"
                steps[-1].status = "success"
            except Exception as e_sel:
                steps[-1].detail = f"select_page failed ({e_sel}); pages={pages}"
                steps[-1].status = "skipped"

        _step("navigate_page", "in_progress", TARGET_URL)
        nav_res = await navigate_page.ainvoke(
            {"type": "url", "url": TARGET_URL, "timeout": 30000}
        )
        steps[-1].detail = str(nav_res)
        steps[-1].status = "success"

        if login_hold > 0:
            _step("login_hold", "in_progress", f"\u7b49\u5f85\u624b\u52a8\u767b\u5f55 {login_hold}s")
            await asyncio.sleep(login_hold)
            steps[-1].status = "success"

        # 准备取证目录
        ev_dir = evidence_dir(post.id, exec_rec.id)
        ev_dir.mkdir(parents=True, exist_ok=True)

        _step("page_state", "in_progress", "")
        state = await evaluate_script.ainvoke({"function": "() => ({href: location.href, title: document.title, ready: document.readyState})"})
        steps[-1].detail = json.dumps(state, ensure_ascii=False)
        steps[-1].status = "success"

        _step("screenshot_before_wait", "in_progress", "")
        shot_path = ev_dir / "before_wait.png"
        await take_screenshot.ainvoke({"filePath": str(shot_path), "fullPage": True})
        steps[-1].detail = f"saved to {shot_path}"
        steps[-1].status = "success"

        _step("snapshot_before_wait", "in_progress", "")
        before_path = ev_dir / "before_wait.txt"
        snap_text = await take_snapshot.ainvoke({"filePath": str(before_path)})
        snap_text = snap_text if isinstance(snap_text, str) else json.dumps(snap_text)
        steps[-1].detail = f"saved to {before_path}"
        steps[-1].status = "success"

        _step("wait_for_publish_ui", "in_progress", "\u7b49\u5f85\u53d1\u5e03\u9875\u5173\u952e\u5b57")
        wait_texts = ["\u4e0a\u4f20\u56fe\u6587", "\u53d1\u5e03\u56fe\u6587", "\u53d1\u5e03\u7b14\u8bb0", "\u53d1\u5e03", "\u56fe\u6587"]
        ok = False
        for text in wait_texts:
            try:
                await wait_for.ainvoke({"text": text, "timeout": 30000})
                steps[-1].detail = f"matched {text}"
                ok = True
                break
            except Exception:
                continue
        if not ok:
            fail_path = ev_dir / "wait_failed.txt"
            await take_snapshot.ainvoke({"filePath": str(fail_path)})
            steps[-1].detail = f"wait_for failed, snapshot at {fail_path}"
            raise RuntimeError("wait_for publish ui timeout")
        steps[-1].status = "success"

        _step("snapshot", "in_progress", "")
        snap_path = ev_dir / "snapshot.txt"
        snap_text = await take_snapshot.ainvoke({"filePath": str(snap_path)})
        snap_text = snap_text if isinstance(snap_text, str) else json.dumps(snap_text)
        steps[-1].detail = f"saved to {snap_path}"
        steps[-1].status = "success"

        # 解析上传/标题/正文控件 uid
        upload_uid = _parse_uid(snap_text, "选择文件")
        title_uid = _parse_uid(snap_text, "填写标题")
        body_uid = _parse_uid(snap_text, "正文内容") or _parse_uid(snap_text, "text") or _parse_uid(snap_text, "textbox multiline")

        if dry_run:
            _step("upload_images", "skipped", "dry_run")
            _step("fill_title_body", "skipped", "dry_run")
            _step("save_draft", "skipped", "dry_run")
            exec_rec.result = "pending"
            return exec_rec

        if assets:
            if not upload_uid:
                raise RuntimeError("未找到上传按钮 uid")
            _step("upload_images", "in_progress", f"{len(assets)} files")
            for p in assets:
                await upload_file.ainvoke({"uid": upload_uid, "filePath": p})
            steps[-1].status = "success"
        else:
            _step("upload_images", "skipped", "无 assets")

        _step("fill_title_body", "in_progress", "")
        filled_ok = False
        try:
            if title_uid:
                await fill_tool.ainvoke({"uid": title_uid, "value": post.title})
                filled_ok = True
            if body_uid:
                await fill_tool.ainvoke({"uid": body_uid, "value": post.body})
                filled_ok = True
        except Exception:
            pass

        if not filled_ok:
            # 兜底用 JS 填写
            script = f"""
            () => {{
              const title = "{_js_escape(post.title)}";
              const body = "{_js_escape(post.body)}";
              const fillInput = (filterFn) => {{
                const els = Array.from(document.querySelectorAll('input,textarea'));
                for (const el of els) {{
                  if (filterFn(el)) {{
                    el.focus();
                    el.value = title;
                    el.dispatchEvent(new Event('input', {{bubbles:true}}));
                    return true;
                  }}
                }}
                return false;
              }};
              const fillBody = () => {{
                const candidates = Array.from(document.querySelectorAll('div[contenteditable="true"], textarea'));
                for (const el of candidates) {{
                  el.focus();
                  el.value = body;
                  el.innerText = body;
                  el.dispatchEvent(new Event('input', {{bubbles:true}}));
                  return true;
                }}
                return false;
              }};
              const okTitle = fillInput(el => (el.placeholder||'').includes('填写标题'));
              const okBody = fillBody();
              return {{okTitle, okBody}};
            }}
            """
            await evaluate_script.ainvoke({"function": script})
            steps[-1].detail = "filled via evaluate_script"
        steps[-1].status = "success"

        _step("save_draft", "in_progress", "点击暂存离开")
        click_script = """
        () => {
          const btns = Array.from(document.querySelectorAll('button,div'));
          const target = btns.find(b => (b.innerText||'').includes('暂存'));
          if (target) { target.click(); return true; }
          return false;
        }
        """
        await evaluate_script.ainvoke({"function": click_script})
        steps[-1].status = "success"

        exec_rec.result = "saved_draft"
    except Exception as e:  # pragma: no cover - runtime errors
        exec_rec.result = "failed"
        exec_rec.error = {"message": str(e)}
    finally:
        exec_rec.steps = steps
        save_execution(exec_rec)

    return exec_rec


def run_save_draft_sync(
    post: Post,
    *,
    assets: Optional[list[str]] = None,
    dry_run: bool = False,
    login_hold: int = 0,
) -> Execution:
    return asyncio.run(
        run_save_draft(post, assets=assets, dry_run=dry_run, login_hold=login_hold)
    )

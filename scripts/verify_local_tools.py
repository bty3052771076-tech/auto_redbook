"""Read-only installed-tool and retained-data checks; no generation or publishing."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


def verify(root: Path, runtime: Path) -> dict:
    if (root / "apps").is_dir():
        sys.path.insert(0, str(root.resolve()))
    from apps.gui import load_env_file, build_subprocess_env, build_xhs_creator_profile_dir
    from src.global_map.basemap import load_basemap
    from src.images.opencodex_images import package_code_hash, VERIFIED_CODE_HASHES, preflight
    import httpx
    from src.knowledge.store import KnowledgeStore
    import apps.cli
    import src

    project = root.resolve()
    runtime = runtime.resolve()
    env = build_subprocess_env(load_env_file(runtime / ".env.gui"))
    env["REDBOOK_RUNTIME_ROOT"] = str(runtime)
    env["KNOWLEDGE_DB_CREDENTIALS"] = str(runtime / "data/knowledge/postgresql-local/connection.json")
    os.environ.update(env)
    tools = project / "tools"
    manifest = json.loads((tools / "manifest.local.json").read_text(encoding="utf-8-sig"))
    paths = {
        "worldmonitor": "worldmonitor/public/data/countries.geojson",
        "RSSHub": "RSSHub/dist/index.mjs",
        "AIHOT": "AIHOT/apps/api/src/main.ts",
        "opencodex": "opencodex/bin/ocx.mjs",
        "postgresql": "postgresql/18.6/pgsql/bin/pg_ctl.exe",
    }
    for name, relative in paths.items():
        if not (tools / relative).is_file():
            raise RuntimeError(f"Missing local tool: {name}")
    if not Path(env["WORLDMONITOR_DIR"]).resolve().is_relative_to(tools):
        raise RuntimeError("World Monitor still points outside the project")
    if not Path(env["RSSHUB_DIR"]).resolve().is_relative_to(tools):
        raise RuntimeError("RSSHub still points outside the project")
    if not Path(src.__file__).resolve().is_relative_to(project):
        raise RuntimeError("Python imported external tool source")
    basemap = load_basemap(Path(env["WORLDMONITOR_DIR"]) / "public/data/countries.geojson")
    profile = build_xhs_creator_profile_dir(project_root=runtime, env=env).resolve()
    if not profile.is_relative_to(runtime / "data/browser") or not profile.is_dir():
        raise RuntimeError("Dedicated browser profile is missing or outside its data root")
    relay = tools / "opencodex"
    database = KnowledgeStore.from_env().status()
    if database.get("status") != "ready":
        raise RuntimeError("PostgreSQL is not ready")
    with httpx.Client() as client:
        image_connection = preflight(client)
    return {
        "project": str(project), "runtime": str(runtime),
        "cli": str(Path(apps.cli.__file__).resolve()),
        "tools": len(manifest["tools"]), "basemap_features": basemap.feature_count,
        "browser_profile": str(profile), "postgresql": database,
        "opencodex_version": json.loads((relay / "package.json").read_text(encoding="utf-8"))["version"],
        "opencodex_copy_verified": package_code_hash(relay) in VERIFIED_CODE_HASHES,
        "opencodex_live_billing": image_connection["billing"],
        "posts": len(list((runtime / "data/posts").glob("*/post.json"))),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    runtime = args.runtime_root or Path(os.getenv("REDBOOK_RUNTIME_ROOT") or root)
    print(json.dumps(verify(root, runtime), ensure_ascii=False, indent=2, default=str))

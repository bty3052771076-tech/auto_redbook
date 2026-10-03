from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.agent.skills import SkillCatalog


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="List, import, or progressively load reviewed Agent Skills")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("list")
    importing = sub.add_parser("import")
    importing.add_argument("source", help="Path below workspace .agents/skills")
    loading = sub.add_parser("load")
    loading.add_argument("name")
    loading.add_argument("--mode", choices=("off", "auto", "manual"), default="manual")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[2]
    catalog = SkillCatalog(root)
    if args.action == "list":
        payload = {"status": "ready", "skills": catalog.list()}
    elif args.action == "import":
        source = Path(args.source)
        if not source.is_absolute():
            source = root / source
        payload = {"status": "imported", "skill": catalog.import_development_skill(source)}
    else:
        payload = catalog.load(args.name, mode=args.mode, selected=True)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

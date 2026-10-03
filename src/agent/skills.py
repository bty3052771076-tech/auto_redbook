from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import os
from pathlib import Path
import re
import shutil
from typing import Any


_FRONTMATTER = re.compile(r"\A---\s*\r?\n(.*?)\r?\n---\s*\r?\n", re.S)
_SAFE_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
_MAX_SKILL_BYTES = 1024 * 1024
_MAX_RESOURCE_BYTES = 256 * 1024


@dataclass(frozen=True)
class SkillInfo:
    name: str
    description: str
    version_hash: str
    path: str
    source: str
    trusted: bool = False


def _frontmatter(text: str) -> tuple[dict[str, str], str]:
    match = _FRONTMATTER.match(text)
    if not match:
        raise ValueError("SKILL_FRONTMATTER_INVALID: expected UTF-8 YAML frontmatter")
    metadata: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise ValueError("SKILL_FRONTMATTER_INVALID: expected key: value")
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip("\"'")
    return metadata, text[match.end():]


class SkillCatalog:
    """Progressive SKILL.md loader. Skill text never grants tools or shell access."""

    def __init__(self, workspace_root: Path):
        self.root = workspace_root.resolve()
        self.runtime_roots = (
            self.root / "skills" / "runtime",
            self.root / "data" / "agent" / "skills",
        )
        self.import_root = self.root / ".agents" / "skills"
        self.destination_root = self.root / "data" / "agent" / "skills"

    def _read_info(self, skill_file: Path, source: str) -> SkillInfo:
        resolved = skill_file.resolve(strict=True)
        if not any(resolved.is_relative_to(root.resolve()) for root in self.runtime_roots):
            raise ValueError("SKILL_PATH_OUTSIDE_ALLOWED_ROOT")
        if skill_file.name != "SKILL.md" or resolved.stat().st_size > _MAX_SKILL_BYTES:
            raise ValueError("SKILL_FILE_INVALID_OR_TOO_LARGE")
        raw = resolved.read_text(encoding="utf-8")
        metadata, _ = _frontmatter(raw)
        name = metadata.get("name", "").strip()
        description = metadata.get("description", "").strip()
        if not _SAFE_NAME.fullmatch(name) or not description or len(description) > 2000:
            raise ValueError("SKILL_METADATA_INVALID")
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return SkillInfo(name, description, digest, str(resolved), source)

    def list(self) -> list[dict[str, Any]]:
        found: dict[str, SkillInfo] = {}
        for root in self.runtime_roots:
            if not root.is_dir():
                continue
            for skill_file in root.rglob("SKILL.md"):
                info = self._read_info(skill_file, "runtime" if root.name == "runtime" else "user_import")
                if info.name in found and found[info.name].version_hash != info.version_hash:
                    raise ValueError(f"SKILL_NAME_COLLISION: {info.name}")
                found[info.name] = info
        return [asdict(item) for item in sorted(found.values(), key=lambda value: value.name)]

    def load(self, name: str, *, mode: str = "manual", selected: bool = True) -> dict[str, Any]:
        mode = str(mode or "off").strip().lower()
        if mode not in {"off", "auto", "manual"}:
            raise ValueError("SKILL_MODE_INVALID")
        if mode == "off" or (mode == "manual" and not selected):
            return {"status": "not_loaded", "reason": "disabled_or_not_selected", "name": name}
        matches = [Path(item["path"]) for item in self.list() if item["name"] == name]
        if not matches:
            raise KeyError(name)
        skill_file = matches[0]
        raw = skill_file.read_text(encoding="utf-8")
        metadata, body = _frontmatter(raw)
        return {
            "status": "loaded",
            "name": name,
            "description": metadata["description"],
            "version_hash": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            "body": body,
            "trusted_instructions": False,
            "execution_allowed": False,
        }

    def select(self, query: str, *, mode: str = "auto", manual_names: tuple[str, ...] = (), limit: int = 3) -> list[dict[str, Any]]:
        mode = str(mode or "off").strip().lower()
        if mode == "off":
            return []
        if mode == "manual":
            return [self.load(name, mode=mode, selected=True) for name in manual_names[:max(0, min(5, limit))]]
        if mode != "auto":
            raise ValueError("SKILL_MODE_INVALID")
        terms = {term.casefold() for term in re.findall(r"[\w\u3400-\u9fff]+", str(query or "")) if len(term) > 1}
        ranked = []
        for item in self.list():
            text = f"{item['name']} {item['description']}".casefold()
            score = sum(1 for term in terms if term in text)
            if score:
                ranked.append((score, item["name"]))
        ranked.sort(key=lambda pair: (-pair[0], pair[1]))
        return [self.load(name, mode=mode) for _, name in ranked[:max(0, min(3, limit))]]

    def read_resource(self, name: str, relative_path: str) -> str:
        skill = next((Path(item["path"]) for item in self.list() if item["name"] == name), None)
        if skill is None:
            raise KeyError(name)
        base = skill.parent.resolve()
        candidate = (base / relative_path).resolve(strict=False)
        if not candidate.is_relative_to(base) or not candidate.is_file():
            raise ValueError("SKILL_RESOURCE_OUTSIDE_ROOT")
        if candidate.stat().st_size > _MAX_RESOURCE_BYTES:
            raise ValueError("SKILL_RESOURCE_TOO_LARGE")
        return candidate.read_text(encoding="utf-8")

    def import_development_skill(self, source: Path) -> dict[str, Any]:
        source = source.resolve(strict=True)
        if not source.is_relative_to(self.import_root.resolve()) or not source.is_dir():
            raise ValueError("SKILL_IMPORT_SOURCE_NOT_ALLOWED")
        skill_file = source / "SKILL.md"
        raw = skill_file.read_text(encoding="utf-8")
        metadata, _ = _frontmatter(raw)
        name = metadata.get("name", "").strip()
        if not _SAFE_NAME.fullmatch(name):
            raise ValueError("SKILL_METADATA_INVALID")
        target = self.destination_root / name
        if target.exists():
            raise FileExistsError(f"skill already imported: {name}")
        self.destination_root.mkdir(parents=True, exist_ok=True)
        for item in source.rglob("*"):
            if item.is_symlink():
                raise ValueError("SKILL_IMPORT_SYMLINK_REJECTED")
            if item.is_file() and item.stat().st_size > _MAX_SKILL_BYTES:
                raise ValueError("SKILL_IMPORT_FILE_TOO_LARGE")
        shutil.copytree(source, target)
        info = self._read_info(target / "SKILL.md", "user_import")
        return asdict(info)

"""Human-reviewed local composition references, separate from persona identity."""
from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
from functools import lru_cache
from io import BytesIO
import json
import os
from pathlib import Path
import re
from typing import Any

from PIL import Image

from src.images.opencodex_images import _file_lock, _write_json

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
PROVENANCE = ("post_id", "post_url", "source", "artist", "characters", "rating", "reference_style",
              "adult_evidence", "license_status", "retrieved_at")


def wool_asset_root(runtime_root: Path | None = None, env: dict | None = None) -> Path:
    values = os.environ if env is None else env
    runtime = Path(runtime_root or values.get("REDBOOK_RUNTIME_ROOT") or ".").resolve()
    root = Path(values.get("WOOL_ASSET_ROOT") or "assets/wool")
    return (root if root.is_absolute() else runtime / root).resolve()


@lru_cache(maxsize=512)
def _inspect_image(path: str, mtime_ns: int, size: int, ctime_ns: int) -> tuple[str, int, int]:
    del mtime_ns, size, ctime_ns
    content = Path(path).read_bytes()
    with Image.open(BytesIO(content)) as image:
        image.verify()
    with Image.open(BytesIO(content)) as image:
        width, height = image.size
    if min(width, height) < 64 or max(width, height) > 8192:
        raise ValueError("图片尺寸不适合参考图")
    return sha256(content).hexdigest(), width, height


def image_digest(path: Path) -> tuple[str, int, int]:
    stat = path.stat()
    if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES or stat.st_size > MAX_IMAGE_BYTES:
        raise ValueError("图片缺失、格式不支持或超过 10 MiB")
    return _inspect_image(str(path), stat.st_mtime_ns, stat.st_size, stat.st_ctime_ns)


class WoolReferenceLibrary:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.catalog = self.root / "reference-library.json"

    def _safe(self, path: Path, folder: str) -> Path:
        resolved = path.resolve()
        boundary = self.root / folder
        if not boundary.resolve().is_relative_to(self.root) or not resolved.is_relative_to(boundary.resolve()):
            raise ValueError("图片必须位于指定素材目录，不能越界")
        return resolved

    def _state(self) -> dict:
        if not self.catalog.exists():
            return {"version": 1, "selected_id": "", "records": {}}
        try:
            value = json.loads(self.catalog.read_text(encoding="utf-8"))
            if value.get("version") != 1 or not isinstance(value.get("records"), dict):
                raise ValueError()
            for identity, record in value["records"].items():
                if (not re.fullmatch(r"[a-f0-9]{64}", identity) or not isinstance(record, dict)
                        or record.get("status") not in {"approved", "rejected"}
                        or (record.get("status") == "approved" and not isinstance(record.get("reference_path"), str))):
                    raise ValueError()
            return value
        except (ValueError, AttributeError):
            raise RuntimeError("WOOL_LIBRARY_INVALID: 图库记录损坏，请检查 reference-library.json；不会忽略人工决定") from None

    def snapshot(self) -> dict[str, Any]:
        state = self._state()
        rows: dict[str, dict] = {}
        warnings = []
        for manifest in sorted((self.root / "候选原图").glob("*/manifest.json")):
            try:
                self._safe(manifest, "候选原图")
                entries = json.loads(manifest.read_text(encoding="utf-8-sig"))["images"]
                if not isinstance(entries, list):
                    raise ValueError()
            except (OSError, ValueError, KeyError, TypeError):
                warnings.append(f"无法读取候选批次：{manifest.parent.name}")
                continue
            for item in entries:
                try:
                    name = item["filename"]
                    if not isinstance(name, str) or Path(name).name != name or "/" in name or "\\" in name:
                        raise ValueError()
                    path = self._safe(manifest.parent / name, "候选原图")
                    identity, width, height = image_digest(path)
                    row = {key: item.get(key, "") for key in PROVENANCE}
                    row.update(id=identity, sha256=identity, filename=name, width=width, height=height,
                               path=path.relative_to(self.root).as_posix(), kind="candidate", status="pending",
                               batch=manifest.parent.name)
                    rows.setdefault(identity, row)
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    warnings.append(f"候选图片不可用：{manifest.parent.name}/{item.get('filename', '?') if isinstance(item, dict) else '?'}；原因：{exc}")
        for folder, kind in (("参考原图", "reference"), ("人设图", "persona")):
            for path in sorted((self.root / folder).glob("*")):
                if path.suffix.lower() not in IMAGE_SUFFIXES:
                    continue
                try:
                    path = self._safe(path, folder)
                    digest, width, height = image_digest(path)
                    identity = "persona-" + digest if kind == "persona" else digest
                    rows.setdefault(identity, {"id": identity, "sha256": digest, "filename": path.name,
                                               "path": path.relative_to(self.root).as_posix(), "kind": kind,
                                               "status": "persona" if kind == "persona" else "legacy",
                                               "width": width, "height": height, "license_status": "unverified"})
                except (OSError, ValueError) as exc:
                    warnings.append(f"素材不可用：{folder}/{path.name}；原因：{exc}")
        for identity, row in rows.items():
            record = state["records"].get(identity)
            if record and row["kind"] != "persona":
                row.update(record)
                row["id"] = identity
                row["kind"] = "reference" if record["status"] == "approved" else "candidate"
            row["image_url"] = f"/api/wool-library/images/{identity}"
        return {"rows": list(rows.values()), "selected_id": state.get("selected_id", ""),
                "root": str(self.root), "warnings": warnings}

    def image(self, identity: str) -> Path:
        row = next((x for x in self.snapshot()["rows"] if x["id"] == identity), None)
        if row is None:
            raise ValueError("图片已变化或不存在，请刷新图库")
        path = self.root / row["path"]
        folder = "人设图" if row["kind"] == "persona" else ("候选原图" if row["path"].startswith("候选原图/") else "参考原图")
        return self._safe(path, folder)

    def review(self, identity: str, *, decision: str, adult_confirmed: bool = False,
               rights_confirmed: bool = False, non_explicit_confirmed: bool = False, note: str = "") -> dict:
        if decision not in {"approve", "reject"} or len(str(note)) > 1000:
            raise ValueError("筛选决定或备注无效")
        if decision == "approve" and not all(x is True for x in (adult_confirmed, rights_confirmed, non_explicit_confirmed)):
            raise ValueError("请确认人物成年、非露骨，并拥有相应使用权限")
        with _file_lock(self.root / "reference-library.lock"):
            state = self._state()
            row = next((x for x in self.snapshot()["rows"] if x["id"] == identity), None)
            if not row or row["kind"] == "persona":
                raise ValueError("待筛选图片已变化、不存在或是人设图，请刷新图库")
            if decision == "approve" and row.get("rating") in {"q", "e"}:
                raise ValueError("露骨分级图片不能入选此参考池")
            source = self.image(identity)
            digest, _, _ = image_digest(source)
            if digest != identity:
                raise ValueError("图片已变化，请重新查看")
            record = {key: row.get(key, "") for key in PROVENANCE}
            record.update(status="approved" if decision == "approve" else "rejected", note=str(note),
                          adult_confirmed=adult_confirmed is True, rights_confirmed=rights_confirmed is True,
                          non_explicit_confirmed=non_explicit_confirmed is True,
                          reviewed_at=datetime.now(timezone.utc).isoformat())
            if decision == "approve":
                reference = source if source.parent == self.root / "参考原图" else self.root / "参考原图" / f"approved-{identity}{source.suffix.lower()}"
                reference = self._safe(reference, "参考原图")
                reference.parent.mkdir(parents=True, exist_ok=True)
                content = source.read_bytes()
                if sha256(content).hexdigest() != identity:
                    raise ValueError("图片在筛选期间变化，请重新查看")
                if reference.exists() and sha256(reference.read_bytes()).hexdigest() != identity:
                    raise RuntimeError("WOOL_APPROVED_REFERENCE_CHANGED: 入选副本变化，请检查后重新入选，禁止覆盖")
                if not reference.exists():
                    with reference.open("xb") as stream:
                        stream.write(content)
                record["reference_path"] = reference.relative_to(self.root).as_posix()
            elif state.get("selected_id") == identity:
                state["selected_id"] = ""
            state["records"][identity] = record
            _write_json(self.catalog, state)
            return {"id": identity, **record}

    def set_selection(self, identity: str = "") -> dict:
        with _file_lock(self.root / "reference-library.lock"):
            state = self._state()
            if identity and state["records"].get(identity, {}).get("status") != "approved":
                raise ValueError("只能指定人工入选的参考原图")
            state["selected_id"] = identity
            _write_json(self.catalog, state)
        return {"selected_id": identity}

    def select_reference(self, *, issue_date: str, provider: str, override: Path | None = None) -> tuple[Path, dict]:
        day = date.fromisoformat(issue_date).isoformat()
        state = self._state()
        approved = {key: value for key, value in state["records"].items() if value["status"] == "approved"}
        if override:
            path = override.resolve()
            if not path.is_relative_to((self.root / "参考原图").resolve()):
                raise ValueError("WOOL_REFERENCE_IMAGE 必须指向参考原图，不能绕过候选筛选")
        elif approved:
            identity = state.get("selected_id")
            if not identity:
                identities = sorted(approved)
                identity = identities[int(sha256(f"{day}:{provider}".encode()).hexdigest(), 16) % len(identities)]
            if identity not in approved:
                raise RuntimeError("WOOL_SELECTED_REFERENCE_NOT_APPROVED: 请重新指定参考图")
            record = approved[identity]
            path = self._safe(self.root / record["reference_path"], "参考原图")
            if not path.is_file() or sha256(path.read_bytes()).hexdigest() != identity:
                raise RuntimeError("WOOL_APPROVED_REFERENCE_CHANGED: 入选副本缺失或变化，请重新筛选")
        else:
            path = self.root / "参考原图/HJKRyImbkAANc_Q.jpg"
        path = self._safe(path, "参考原图")
        if not path.is_file():
            raise RuntimeError(f"WOOL_IMAGE_RESOURCE_MISSING: 请人工入选参考图，或恢复原有素材 {path}")
        identity = sha256(path.read_bytes()).hexdigest()
        record = state["records"].get(identity, {})
        if record.get("status") == "rejected":
            raise RuntimeError("WOOL_REFERENCE_REJECTED: 此参考图已被人工排除")
        return path, {"reference_id": identity, "reference_sha256": identity,
                      "reference_status": record.get("status", "legacy"),
                      "reference_source": {key: record.get(key, "") for key in PROVENANCE},
                      "artist": record.get("artist", ""),
                      "rights_confirmed": record.get("rights_confirmed", False),
                      "reference_review": record}

    def has_approved_references(self) -> bool:
        return any(record.get("status") == "approved" for record in self._state()["records"].values())

from pathlib import Path

import pytest

from src.agent.skills import SkillCatalog


def make_skill(root: Path, name="news-check") -> Path:
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Check news sources and dates\n---\n\nUse approved source tools only.\n",
        encoding="utf-8",
    )
    (folder / "reference.md").write_text("Evidence checklist", encoding="utf-8")
    return folder


def test_skill_modes_progressively_load_and_never_grant_execution(tmp_path):
    catalog = SkillCatalog(tmp_path)
    imported = make_skill(catalog.import_root)
    record = catalog.import_development_skill(imported)
    assert record["name"] == "news-check"
    assert catalog.select("news source date", mode="off") == []
    selected = catalog.select("news source date", mode="auto")
    assert len(selected) == 1
    assert selected[0]["execution_allowed"] is False
    assert selected[0]["trusted_instructions"] is False
    assert "Use approved source tools" in selected[0]["body"]
    assert catalog.read_resource("news-check", "reference.md") == "Evidence checklist"


def test_manual_skill_selection_does_not_auto_add_other_skills(tmp_path):
    catalog = SkillCatalog(tmp_path)
    catalog.import_development_skill(make_skill(catalog.import_root, "news-check"))
    catalog.import_development_skill(make_skill(catalog.import_root, "image-review"))
    selected = catalog.select("news source image", mode="manual", manual_names=("image-review",))
    assert [item["name"] for item in selected] == ["image-review"]


def test_skill_import_rejects_outside_workspace_source(tmp_path):
    catalog = SkillCatalog(tmp_path)
    outside = make_skill(tmp_path / "outside")
    with pytest.raises(ValueError, match="NOT_ALLOWED"):
        catalog.import_development_skill(outside)


def test_skill_resource_path_traversal_is_rejected(tmp_path):
    catalog = SkillCatalog(tmp_path)
    catalog.import_development_skill(make_skill(catalog.import_root))
    with pytest.raises(ValueError, match="OUTSIDE_ROOT"):
        catalog.read_resource("news-check", "../../../../outside.txt")

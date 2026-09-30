import json
import subprocess
from pathlib import Path

import pytest

from career_autofill.adapters.outbound.json_repository import JsonCareerRepository
from career_autofill.adapters.outbound.private_markdown import PrivateMarkdownRepository
from career_autofill.application.context import ContextService
from career_autofill.domain.context import build_context
from career_autofill.domain.models import Fact
from career_autofill.domain.policies import now


def service_at(path, profile):
    profiles = JsonCareerRepository(path / "data")
    profiles.save_profile(profile)
    documents = PrivateMarkdownRepository(path / "data" / "context")
    return ContextService(profiles, documents), profiles


def test_matching_context_omits_contacts_and_autofill_retains_unknown_status(profile):
    profile.basic["birth_date"] = Fact(value="미확인", source="user:pending", status="unverified")
    profile.experiences[0].title = "표 | 셀\n<script>"
    matching = build_context(profile, "matching", now()).markdown
    assert "test@example.com" not in matching
    assert "010-0000-0000" not in matching
    assert "테스트지원자" not in matching
    assert "Flask" in matching and "https://example.notion.site/portfolio" in matching
    assert "표 \\| 셀<br>&lt;script&gt;" in matching
    autofill = build_context(profile, "autofill", now()).markdown
    assert "test@example.com" in autofill
    assert "basic.birth_date | 미확인 | unverified | user:pending" in autofill
    assert "Flask API" not in autofill


def test_context_is_reused_and_rebuilt_after_profile_change_or_markdown_edit(tmp_path, profile):
    service, profiles = service_at(tmp_path, profile)
    first = service.get_reusable_context()
    path = Path(first["path"])
    original_mtime = path.stat().st_mtime_ns
    second = service.get_reusable_context()
    assert not first["cache_hit"] and second["cache_hit"]
    assert first["context"] == second["context"]
    assert path.stat().st_mtime_ns == original_mtime
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    profile.skills.append("Rust")
    profiles.save_profile(profile)
    updated = service.get_reusable_context()
    assert not updated["cache_hit"] and "Rust" in updated["context"]
    assert updated["profile_fingerprint"] != first["profile_fingerprint"]
    path.write_text("수동으로 변경한 값", encoding="utf-8")
    restored = service.get_reusable_context()
    assert not restored["cache_hit"]
    assert restored["profile_fingerprint"] == updated["profile_fingerprint"]
    assert "Rust" in restored["context"] and "수동으로 변경한 값" not in restored["context"]
    assert not service.get_reusable_context(refresh=True)["cache_hit"]


def test_corrupt_context_metadata_is_rebuilt_and_local_guide_is_not_overwritten(tmp_path, profile):
    service, _ = service_at(tmp_path, profile)
    result = service.get_reusable_context()
    metadata = Path(result["path"]).with_suffix(".json")
    metadata.write_text(json.dumps([]))
    assert not service.get_reusable_context()["cache_hit"]
    guide = Path(service.initialize_notes()["path"])
    guide.write_text("사용자가 직접 정리한 내용", encoding="utf-8")
    service.initialize_notes()
    assert guide.read_text(encoding="utf-8") == "사용자가 직접 정리한 내용"


def git(path, *arguments):
    return subprocess.run(
        ["git", "-C", str(path), *arguments], capture_output=True, text=True, check=True
    )


def test_git_must_ignore_private_outputs_and_force_tracked_path_is_rejected(tmp_path, profile):
    git(tmp_path, "init", "--quiet")
    service, _ = service_at(tmp_path, profile)
    with pytest.raises(ValueError, match="ignored"):
        service.get_reusable_context()
    (tmp_path / ".gitignore").write_text("*.private.md\n")
    with pytest.raises(ValueError, match="ignored"):
        service.get_reusable_context(refresh=True)
    assert not (tmp_path / "data" / "context").exists()
    (tmp_path / ".gitignore").write_text("*.private.md\n*.private.json\n")
    result = service.get_reusable_context()
    path = Path(result["path"])
    git(tmp_path, "add", "--force", "--", str(path.relative_to(tmp_path)))
    original = path.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="tracked"):
        service.get_reusable_context()
    with pytest.raises(ValueError, match="tracked"):
        service.get_reusable_context(refresh=True)
    assert path.read_text(encoding="utf-8") == original


def test_symlink_cannot_redirect_context_into_another_file(tmp_path, profile):
    service, _ = service_at(tmp_path, profile)
    result = service.get_reusable_context()
    path = Path(result["path"])
    public = tmp_path / "public.md"
    public.write_text("keep this document")
    path.unlink()
    path.symlink_to(public)
    with pytest.raises(ValueError, match="symlink"):
        service.get_reusable_context(refresh=True)
    assert public.read_text() == "keep this document"


def test_failed_git_check_does_not_allow_private_write(tmp_path, profile, monkeypatch):
    service, _ = service_at(tmp_path, profile)

    def failed_git(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 128, stdout="", stderr="Permission denied")

    monkeypatch.setattr(subprocess, "run", failed_git)
    with pytest.raises(ValueError, match="verify the Git worktree"):
        service.get_reusable_context()
    assert not (tmp_path / "data" / "context").exists()

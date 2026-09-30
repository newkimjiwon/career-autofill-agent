"""Private Markdown storage with Git checks, atomic writes and integrity validation."""

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

from pydantic import ValidationError

from ...domain.context import ContextDocument, ContextSection


class PrivateMarkdownRepository:
    def __init__(self, root: Path):
        if root.is_symlink():
            raise ValueError("Private context directory must not be a symlink.")
        self.root = root.resolve()

    def _paths(self, *names: str) -> tuple[Path, ...]:
        if self.root.resolve() != self.root or self.root.is_symlink():
            raise ValueError("Private context directory must not be a symlink.")
        paths = tuple(self.root / name for name in names)
        if any(path.is_symlink() for path in paths):
            raise ValueError("Private context files must not be symlinks.")
        ancestor = self.root
        while not ancestor.exists():
            ancestor = ancestor.parent
        repository = subprocess.run(
            ["git", "-C", str(ancestor), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "LC_ALL": "C"},
        )
        if repository.returncode:
            if "not a git repository" not in repository.stderr:
                raise ValueError("Cannot verify the Git worktree for private context.")
            # A data directory outside any worktree cannot be staged in this repository.
            return paths
        worktree = Path(repository.stdout.strip()).resolve()
        relatives = [str(path.relative_to(worktree)) for path in paths]
        tracked = subprocess.run(
            ["git", "-C", str(worktree), "ls-files", "-z", "--", *relatives],
            capture_output=True,
            check=False,
        )
        if tracked.returncode != 0:
            raise ValueError("Cannot verify whether private context is tracked by Git.")
        if tracked.stdout:
            raise ValueError("Private context path is tracked by Git. Untrack it before use.")
        ignored = subprocess.run(
            ["git", "-C", str(worktree), "check-ignore", "--no-index", "-z", "--stdin"],
            input="\0".join(relatives).encode() + b"\0",
            capture_output=True,
            check=False,
        )
        expected = {relative.encode() for relative in relatives}
        actual = set(ignored.stdout.rstrip(b"\0").split(b"\0"))
        if ignored.returncode != 0 or actual != expected:
            raise ValueError("Private context path must be ignored by Git before use.")
        return paths

    @staticmethod
    def _name(section: ContextSection, extension: str) -> str:
        if section not in {"matching", "autofill"}:
            raise ValueError("section must be matching or autofill")
        return f"{section}.private.{extension}"

    def _write(self, path: Path, content: str) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=self.root, suffix=".private.md", delete=False
        ) as handle:
            temporary = Path(handle.name)
            try:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
                os.chmod(temporary, 0o600)
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)

    def context_path(self, section: ContextSection) -> str:
        return str(self.root / self._name(section, "md"))

    def load_context(self, section: ContextSection) -> ContextDocument | None:
        markdown, metadata = self._paths(self._name(section, "md"), self._name(section, "json"))
        try:
            content = markdown.read_text(encoding="utf-8")
            record = json.loads(metadata.read_text(encoding="utf-8"))
            if not isinstance(record, dict):
                return None
            digest = record.pop("markdown_sha256")
            if hashlib.sha256(content.encode()).hexdigest() != digest:
                return None
            document = ContextDocument.model_validate({**record, "markdown": content})
            return document if document.section == section else None
        except (FileNotFoundError, UnicodeError, ValueError, KeyError, TypeError, ValidationError):
            return None

    def save_context(self, document: ContextDocument) -> str:
        markdown, metadata = self._paths(
            self._name(document.section, "md"), self._name(document.section, "json")
        )
        record = document.model_dump(mode="json", exclude={"markdown"})
        record["markdown_sha256"] = hashlib.sha256(document.markdown.encode()).hexdigest()
        self._write(markdown, document.markdown)
        self._write(metadata, json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        return str(markdown)

    def initialize_notes(self, template: str) -> str:
        (path,) = self._paths("README.private.md")
        if not path.exists():
            self._write(path, template)
        return str(path)

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from ...domain.models import CareerProfile, FillPlan, JobRole, SourceSnapshot


class JsonStore:
    def __init__(self, root: Path | None = None):
        self.root = (root or Path(os.environ.get("CAREER_DATA_DIR", "data"))).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def write(self, name: str, value: Any) -> None:
        # All callers use application-generated names, never user-provided paths.
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            try:
                json.dump(value, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
                os.chmod(temporary, 0o600)
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)

    def read(self, name: str) -> Any:
        path = self.root / name
        if not path.exists():
            raise ValueError(f"Missing {name}. Import the profile or collect jobs first.")
        return json.loads(path.read_text())

    def profile(self) -> CareerProfile:
        return CareerProfile.model_validate(self.read("profile.json"))

    def jobs(self) -> list[JobRole]:
        return [JobRole.model_validate(job) for job in self.read("jobs.json")]

    def plan(self, plan_id: str) -> FillPlan:
        if not plan_id.isalnum() or len(plan_id) != 32:
            raise ValueError("Invalid plan id.")
        return FillPlan.model_validate(self.read(f"plans/{plan_id}.json"))


class JsonCareerRepository:
    """Outbound persistence adapter; JSON names and permissions stay outside use cases."""

    def __init__(self, root: Path | None = None):
        self.store = JsonStore(root)

    def load_profile(self) -> CareerProfile:
        return self.store.profile()

    def save_profile(self, profile: CareerProfile) -> None:
        self.store.write("profile.json", profile.model_dump(mode="json"))

    def load_jobs(self) -> list[JobRole]:
        return self.store.jobs()

    def existing_jobs(self) -> list[JobRole]:
        return self.load_jobs() if (self.store.root / "jobs.json").exists() else []

    def save_jobs(self, jobs: list[JobRole]) -> None:
        self.store.write("jobs.json", [job.model_dump(mode="json") for job in jobs])

    def load_plan(self, plan_id: str) -> FillPlan:
        return self.store.plan(plan_id)

    def save_plan(self, plan: FillPlan) -> None:
        self.store.write(f"plans/{plan.id}.json", plan.model_dump(mode="json"))

    def save_source(self, document: SourceSnapshot) -> str:
        source_id = hashlib.sha256(document.url.encode()).hexdigest()[:16]
        self.store.write(f"sources/{source_id}.json", document.model_dump(mode="json"))
        return source_id

    def save_recommendations(self, report: dict) -> None:
        self.store.write("recommendations.json", report)

    def save_fill_report(self, report: dict) -> None:
        self.store.write("last_fill_report.json", report)

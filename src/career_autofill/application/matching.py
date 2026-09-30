from ..domain.matching import rank_jobs
from ..domain.models import CareerProfile, JobRole, SourceSnapshot
from ..domain.policies import check_url
from .ports import JobSource, MatchingRepository, SourceReader


class MatchingService:
    def __init__(self, repository: MatchingRepository, reader: SourceReader, jobs: JobSource):
        self.repository = repository
        self.reader = reader
        self.jobs = jobs

    async def read_portfolio(self, url: str) -> dict:
        check_url(url)
        return self.import_source_snapshot(await self.reader.read(url))

    def import_source_snapshot(self, document: SourceSnapshot) -> dict:
        check_url(document.url)
        source_id = self.repository.save_source(document)
        return {"source_id": source_id, "document": document.model_dump(mode="json")}

    def save_profile(self, profile: CareerProfile) -> dict:
        self.repository.save_profile(profile)
        return {"saved": True, "fact_count": len(profile.facts()), "issues": profile.issues}

    def get_profile(self) -> dict:
        return self.repository.load_profile().model_dump(mode="json")

    async def discover_db_jobs(self) -> dict:
        jobs, failures = await self.jobs.collect()
        if not jobs:
            return {"saved": False, "jobs": [], "failures": failures}
        return {**self.save_jobs(jobs), "scope": "first listing page", "failures": failures}

    def import_job_snapshot(self, document: SourceSnapshot) -> dict:
        new_jobs = self.jobs.parse(document)
        existing = self.repository.existing_jobs()
        merged = [job for job in existing if job.source_url != document.url] + new_jobs
        return self.save_jobs(merged)

    def save_jobs(self, jobs: list[JobRole]) -> dict:
        for job in jobs:
            check_url(job.source_url, application=True)
            if job.deadline is not None and job.deadline.tzinfo is None:
                raise ValueError("Deadline must include a timezone.")
        if len({job.id for job in jobs}) != len(jobs):
            raise ValueError("Role IDs must be unique.")
        self.repository.save_jobs(jobs)
        return {"saved": True, "role_count": len(jobs)}

    def recommend_jobs(self, limit: int = 5) -> dict:
        if not 1 <= limit <= 30:
            raise ValueError("limit must be between 1 and 30.")
        matches = rank_jobs(self.repository.load_profile(), self.repository.load_jobs(), limit)
        report = {
            "matches": [match.model_dump(mode="json") for match in matches],
            "method": "Transparent keyword baseline, not an acceptance probability",
            "next_step": "User chooses one role; career-autofill handles login handoff.",
        }
        self.repository.save_recommendations(report)
        return report

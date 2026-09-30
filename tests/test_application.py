import pytest

from career_autofill.application.autofill import AutofillService
from career_autofill.application.matching import MatchingService
from career_autofill.application.ports import BrowserBatchResult
from career_autofill.domain.models import FormField, FormInspection


class MemoryRepository:
    def __init__(self):
        self.profile = None
        self.jobs = []
        self.plans = {}
        self.recommendations = None
        self.report = None

    def load_profile(self):
        return self.profile.model_copy(deep=True)

    def save_profile(self, profile):
        self.profile = profile.model_copy(deep=True)

    def load_jobs(self):
        return self.jobs

    def existing_jobs(self):
        return self.jobs

    def save_jobs(self, jobs):
        self.jobs = jobs

    def save_source(self, document):
        return "memory-source"

    def save_recommendations(self, report):
        self.recommendations = report

    def load_plan(self, plan_id):
        return self.plans[plan_id].model_copy(deep=True)

    def save_plan(self, plan):
        self.plans[plan.id] = plan.model_copy(deep=True)

    def save_fill_report(self, report):
        self.report = report


class MemoryBrowser:
    def __init__(self):
        self.inspection = FormInspection(
            status="ready",
            url="https://dbgroup.recruiter.co.kr/v1/applicant/resume-form/123?step=2",
            fields=[
                FormField(id="f0:0", index=0, label="성명", kind="text"),
                FormField(
                    id="f0:1", index=1, label="이메일", kind="email", value="keep@example.com"
                ),
            ],
        )

    async def inspect(self):
        return self.inspection.model_copy(deep=True)

    async def open_application(self, job_url, mode):
        return {"status": "user_action_required", "url": job_url}

    async def execute(self, plan):
        actions = {action.field.id: action for action in plan.actions}
        self.inspection.fields = [
            field.model_copy(update={"value": actions[field.id].value})
            if field.id in actions
            else field
            for field in self.inspection.fields
        ]
        return BrowserBatchResult(filled_ids=set(actions), field_checks=len(actions))

    async def close(self):
        pass


class MemorySources:
    def __init__(self, jobs):
        self.jobs = jobs

    async def collect(self):
        return self.jobs, []

    async def read(self, url):
        raise ValueError("No document configured in this in-memory source.")

    def parse(self, document):
        return self.jobs


async def test_use_cases_work_with_memory_ports_without_mcp_browser_or_files(profile, job_factory):
    repository = MemoryRepository()
    sources = MemorySources([job_factory()])
    matching = MatchingService(repository, sources, sources)
    matching.save_profile(profile)
    assert (await matching.discover_db_jobs())["role_count"] == 1
    assert matching.recommend_jobs()["matches"][0]["score"] > 0
    autofill = AutofillService(repository, MemoryBrowser())
    plan = (await autofill.preview_autofill())["plan"]
    result = await autofill.apply_autofill(plan["id"])
    assert result["status"] == "applied"
    assert result["preserved_fields_verified"]
    assert repository.report == result
    with pytest.raises(ValueError, match="consumed"):
        await autofill.apply_autofill(plan["id"])


async def test_plan_is_consumed_before_adapter_failure_and_cannot_be_replayed(profile):
    repository = MemoryRepository()
    repository.save_profile(profile)

    class FailingBrowser(MemoryBrowser):
        async def execute(self, plan):
            assert repository.load_plan(plan.id).state == "failed"
            raise RuntimeError("Browser connection lost")

    service = AutofillService(repository, FailingBrowser())
    plan = (await service.preview_autofill())["plan"]
    result = await service.apply_autofill(plan["id"])
    assert result["status"] == "failed"
    assert "connection lost" in result["errors"][0]["error"]
    with pytest.raises(ValueError, match="consumed"):
        await service.apply_autofill(plan["id"])

from typing import Literal
from urllib.parse import urlsplit

from ..domain.models import CareerProfile, FillPlan, FormField
from ..domain.planning import build_plan
from ..domain.policies import check_url
from ..domain.verification import validate_before_fill, validate_plan_profile, verify_readback
from .ports import ApplicationBrowser, AutofillRepository


class AutofillService:
    def __init__(self, repository: AutofillRepository, browser: ApplicationBrowser):
        self.repository = repository
        self.browser = browser

    async def open_application(self, job_url: str, mode: Literal["new", "existing"]) -> dict:
        return await self.browser.open_application(job_url, mode)

    async def inspect_application(self) -> dict:
        return (await self.browser.inspect()).model_dump(exclude_none=True)

    def update_profile(self, profile: CareerProfile) -> dict:
        self.repository.save_profile(profile)
        return {"saved": True, "fact_count": len(profile.facts())}

    def _plan(self, url: str, fields: list[FormField], mappings: dict[str, str] | None) -> FillPlan:
        plan = build_plan(url, fields, self.repository.load_profile(), mappings)
        self.repository.save_plan(plan)
        return plan

    async def preview_autofill(self, mappings: dict[str, str] | None = None) -> dict:
        inspection = await self.browser.inspect()
        if inspection.status != "ready":
            return inspection.model_dump(exclude_none=True)
        plan = self._plan(inspection.url, inspection.fields, mappings)
        return {
            "status": "preview",
            "plan": plan.model_dump(mode="json"),
            "notice": "Typing can trigger recruiter autosave. Login, consent, uploads, custom "
            "widgets and submission remain manual.",
        }

    @staticmethod
    def _validate_host_form(url: str, fields: list[FormField]) -> None:
        check_url(url, application=True)
        if not urlsplit(url).path.startswith("/v1/applicant/resume-form/"):
            raise ValueError("Use the actual application form after the user completes login.")
        if any(field.kind == "password" for field in fields):
            raise ValueError("User must finish login before previewing application data.")

    def preview_from_snapshot(
        self, url: str, fields: list[FormField], mappings: dict[str, str] | None = None
    ) -> dict:
        self._validate_host_form(url, fields)
        plan = self._plan(url, fields, mappings)
        return {
            "status": "preview",
            "execution": "host_browser",
            "plan": plan.model_dump(mode="json"),
        }

    def _report(
        self, plan: FillPlan, filled: list[dict], errors: list[dict], execution: str, **extra
    ) -> dict:
        plan.state = "failed" if errors else "applied"
        self.repository.save_plan(plan)
        report = {
            "status": plan.state,
            "execution": execution,
            "filled": filled,
            "errors": errors,
            "skipped": plan.skipped,
            "preserved_fields_verified": not errors,
            "submitted": False,
            "submission_action_performed": False,
            **extra,
        }
        self.repository.save_fill_report(report)
        return report

    def verify_from_snapshot(self, plan_id: str, url: str, fields: list[FormField]) -> dict:
        check_url(url, application=True)
        plan = self.repository.load_plan(plan_id)
        validate_plan_profile(plan, self.repository.load_profile())
        if url != plan.url:
            raise ValueError("The application page changed.")
        filled, errors = verify_readback(plan, fields)
        return self._report(plan, filled, errors, "host_browser")

    async def apply_autofill(self, plan_id: str) -> dict:
        plan = self.repository.load_plan(plan_id)
        validate_plan_profile(plan, self.repository.load_profile())
        before = await self.browser.inspect()
        if before.status != "ready":
            raise ValueError("Login required. The user must log in manually.")
        validate_before_fill(plan, before.url, before.fields)
        if not plan.actions:
            return {"status": "nothing_to_fill", "filled": [], "skipped": plan.skipped}
        # Persist consumption before any browser side effects; partial plans cannot be replayed.
        plan.state = "failed"
        self.repository.save_plan(plan)
        filled, errors = [], []
        field_checks = 0
        try:
            batch = await self.browser.execute(plan)
            field_checks = batch.field_checks
            errors.extend(batch.errors)
            after = await self.browser.inspect()
            if after.status != "ready" or after.url != plan.url:
                errors.append({"field_id": "", "error": "Application page changed during fill"})
            else:
                filled, mismatches = verify_readback(plan, after.fields, batch.filled_ids)
                errors.extend(mismatches)
        except Exception as exc:
            errors.append({"field_id": "", "error": str(exc)[:300]})
        return self._report(
            plan,
            filled,
            errors,
            "native_browser",
            field_checks=field_checks,
            message="Review the result and fill unresolved fields yourself. "
            "Final submission is always performed by the user.",
        )

    async def close_browser(self) -> dict:
        await self.browser.close()
        return {"closed": True}

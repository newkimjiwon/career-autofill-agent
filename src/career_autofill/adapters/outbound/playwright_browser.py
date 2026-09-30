import re
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs, urlsplit

from ...application.ports import BrowserBatchResult
from ...domain.models import FillPlan, FormField, FormInspection
from ...domain.policies import check_url
from .form_dom import CONTROL_SELECTOR, READ_CONTROL_SCRIPT, scan_fields


class PlaywrightApplicationBrowser:
    """One long-lived browser, so user login and subsequent fills share the same session."""

    def __init__(self, directory: Path | None = None, headless: bool = False):
        self.directory = directory or Path(".browser")
        self.headless = headless
        self.runtime = None
        self.context = None
        self.page = None
        self.selected_job_url = None
        self.job_notice_sn = None

    async def start(self):
        if self.context is not None:
            return
        from playwright.async_api import async_playwright

        self.runtime = await async_playwright().start()
        directory = self.directory.resolve()
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.context = await self.runtime.chromium.launch_persistent_context(
                str(directory),
                headless=self.headless,
                viewport={"width": 1280, "height": 900},
            )
            self.page = (
                self.context.pages[0] if self.context.pages else await self.context.new_page()
            )
        except Exception:
            await self.runtime.stop()
            self.runtime = None
            raise

    async def open_application(
        self, job_url: str, mode: Literal["new", "existing"] = "new"
    ) -> dict:
        check_url(job_url, application=True)
        if not re.fullmatch(r"/career/jobs/\d+", urlsplit(job_url).path):
            raise ValueError("Choose one job detail URL from the recommendations.")
        await self.start()
        await self.page.goto(job_url, wait_until="domcontentloaded")
        check_url(self.page.url, application=True)
        self.selected_job_url = job_url
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError

        try:
            async with self.page.expect_popup(timeout=5000) as popup:
                button = "지원서 수정" if mode == "existing" else "지원하기"
                await self.page.get_by_role("button", name=button, exact=True).click()
            self.page = await popup.value
            await self.page.wait_for_load_state("domcontentloaded")
        except PlaywrightTimeoutError:
            # Some sites/configurations use the current tab instead of a popup.
            await self.page.wait_for_load_state("domcontentloaded")
        check_url(self.page.url, application=True)
        self.job_notice_sn = parse_qs(urlsplit(self.page.url).query).get("jobnoticeSn", [None])[0]
        return {
            "status": "user_action_required",
            "url": self.page.url,
            "message": "Complete login/account creation/agreements yourself in the opened "
            "browser, then open the selected application form and resume.",
        }

    async def current_page(self):
        if self.context is None:
            raise ValueError("Call open_application first, then complete login yourself.")
        # Login can spawn another window. Prefer a page visibly containing application controls.
        candidates = [page for page in self.context.pages if not page.is_closed()]
        for page in reversed(candidates):
            try:
                check_url(page.url, application=True)
                if await page.locator(CONTROL_SELECTOR).count():
                    self.page = page
                    break
            except ValueError:
                continue
        check_url(self.page.url, application=True)
        notice = parse_qs(urlsplit(self.page.url).query).get("jobnoticeSn", [None])[0]
        if self.job_notice_sn and notice and notice != self.job_notice_sn:
            raise ValueError("This form belongs to a different job. Open the chosen application.")
        return self.page

    async def inspect(self) -> FormInspection:
        page = await self.current_page()
        fields = await scan_fields(page)
        if self.needs_login(page, fields):
            return FormInspection(
                status="login_required",
                url=page.url,
                message="User must complete login. No credentials are read or entered.",
            )
        if not fields:
            return FormInspection(
                status="user_action_required",
                url=page.url,
                message="Open the actual application form after login and agreements.",
            )
        return FormInspection(status="ready", url=page.url, fields=fields)

    @staticmethod
    def needs_login(page, fields: list[FormField]) -> bool:
        login_path = re.search(
            r"/(?:login|sign-?in|sign-?up|register|join|auth)(?:/|$)", urlsplit(page.url).path, re.I
        )
        return bool(login_path) or any(field.kind == "password" for field in fields)

    async def execute(self, plan: FillPlan) -> BrowserBatchResult:
        """Fill a page-scoped batch with lightweight guards, never bypassing input events.

        The use case checks the full snapshot before and after this batch. Each mutation
        still checks its exact target immediately before typing, without rescanning all fields.
        """
        if self.page is None or self.page.is_closed():
            raise ValueError("The application browser is closed.")
        page = self.page
        result = BrowserBatchResult()
        for action in plan.actions:
            try:
                check_url(page.url, application=True)
                if page.url != plan.url:
                    raise ValueError("Application page changed while filling.")
                target = (
                    page.frames[action.field.frame]
                    .locator(CONTROL_SELECTOR)
                    .nth(action.field.index)
                )
                observed = await target.evaluate(READ_CONTROL_SCRIPT, action.field.index)
                result.field_checks += 1
                if observed is None:
                    raise ValueError("Field is no longer visible.")
                current = FormField(id=action.field.id, frame=action.field.frame, **observed)
                if current != action.field:
                    raise ValueError("Field changed while filling; inspect again.")
                if action.field.kind == "select-one":
                    await target.select_option(value=action.value)
                else:
                    await target.fill(action.value)
                if await target.input_value() != action.value:
                    raise ValueError("Read-back differs from the planned value.")
                result.filled_ids.add(action.field.id)
            except Exception as exc:
                result.errors.append({"field_id": action.field.id, "error": str(exc)[:300]})
                break
        return result

    async def close(self):
        if self.context is not None:
            await self.context.close()
        if self.runtime is not None:
            await self.runtime.stop()
        self.context = self.runtime = self.page = None

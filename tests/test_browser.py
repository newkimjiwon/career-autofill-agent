import pytest
import pytest_asyncio
from playwright.async_api import async_playwright

from career_autofill.adapters.outbound.form_dom import scan_fields
from career_autofill.adapters.outbound.json_repository import JsonCareerRepository
from career_autofill.adapters.outbound.playwright_browser import PlaywrightApplicationBrowser
from career_autofill.application.autofill import AutofillService
from career_autofill.domain.models import Fact
from career_autofill.domain.planning import build_plan

URL = "https://dbgroup.recruiter.co.kr/fixture/application"
FORM = """<!doctype html><html lang="ko"><head><meta charset="utf-8"></head><body>
<h1>로컬 테스트 지원서</h1>
<form onsubmit="window.submissions++; return false">
<label>성명<input name="name" required></label>
<label>이메일<input type="email" name="email"></label>
<label>휴대전화<input type="tel" name="phone" maxlength="11"></label>
<label>졸업구분<select name="graduation"><option value="">선택</option>
<option value="GRAD">졸업</option></select></label>
<label>입학일<input type="date" name="start"></label>
<label>병역구분<input name="military"></label>
<label><input type="checkbox" name="consent">약관 동의</label>
<input type="hidden" name="internal" value="leave-me">
<button type="submit">최종 제출</button>
</form>
<script>window.submissions=0; window.inputEvents=0;
document.addEventListener('input', () => window.inputEvents++);</script>
</body></html>"""


@pytest_asyncio.fixture
async def application(tmp_path, monkeypatch):
    monkeypatch.setenv("CAREER_DATA_DIR", str(tmp_path / "data"))
    store = JsonCareerRepository()
    async with async_playwright() as runtime:
        context = await runtime.chromium.launch(headless=True)
        page = await context.new_page()
        # Intercept every request; this fixture never contacts the real recruitment service.
        await page.route(
            "**/*", lambda route: route.fulfill(content_type="text/html; charset=utf-8", body=FORM)
        )
        await page.goto(URL)
        application = PlaywrightApplicationBrowser()
        application.context = context.contexts[0]
        application.page = page
        yield application, page, store
        await context.close()


async def test_real_dom_fill_readback_events_without_submission(application, profile):
    browser, page, store = application
    service = AutofillService(store, browser)
    store.save_profile(profile)
    fields = await scan_fields(page)
    plan = build_plan(URL, fields, profile)
    store.save_plan(plan)
    result = await service.apply_autofill(plan.id)
    assert result["status"] == "applied"
    assert len(result["filled"]) == 4
    assert await page.get_by_label("성명", exact=True).input_value() == "테스트지원자"
    assert await page.get_by_label("휴대전화").input_value() == "01000000000"
    assert await page.get_by_label("졸업구분").input_value() == "GRAD"
    assert await page.get_by_label("입학일").input_value() == ""
    assert await page.get_by_label("병역구분").input_value() == ""
    assert not await page.get_by_label("약관 동의").is_checked()
    assert await page.locator('[name="internal"]').input_value() == "leave-me"
    assert await page.evaluate("window.submissions") == 0
    assert await page.evaluate("window.inputEvents") >= 3
    assert result["submitted"] is False
    with pytest.raises(ValueError, match="consumed"):
        await service.apply_autofill(plan.id)


async def test_stale_form_is_rejected_before_any_fill(application, profile):
    browser, page, store = application
    service = AutofillService(store, browser)
    store.save_profile(profile)
    plan = build_plan(URL, await scan_fields(page), profile)
    store.save_plan(plan)
    await page.get_by_label("이메일").fill("changed@example.com")
    with pytest.raises(ValueError, match="form changed"):
        await service.apply_autofill(plan.id)
    assert await page.get_by_label("성명", exact=True).input_value() == ""


async def test_stale_profile_is_rejected_before_any_fill(application, profile):
    browser, page, store = application
    service = AutofillService(store, browser)
    plan = build_plan(URL, await scan_fields(page), profile)
    store.save_plan(plan)
    profile.basic["email"] = Fact(value="new@example.com", source="user:confirmed")
    store.save_profile(profile)
    with pytest.raises(ValueError, match="profile changed"):
        await service.apply_autofill(plan.id)
    assert await page.get_by_label("성명", exact=True).input_value() == ""


async def test_login_handoff_never_exposes_password_value(application):
    browser, page, _ = application
    await page.set_content(
        '<label>비밀번호<input type="password" value="synthetic-secret"></label>'
    )
    fields = await scan_fields(page)
    assert fields[0].value == ""
    result = await browser.inspect()
    assert result.status == "login_required"
    assert "synthetic-secret" not in str(result)


async def test_mrs_months_and_select_labels_are_scanned_without_option_text(application):
    _, page, _ = application
    await page.goto("https://dbgroup.recruiter.co.kr/v1/applicant/resume-form/123?step=2")
    await page.set_content(
        "<label>졸업구분<select><option>선택</option><option>졸업</option></select></label>"
        '<input placeholder="입학년월"><input placeholder="졸업년월">'
    )
    fields = await scan_fields(page)
    assert fields[0].label == "졸업구분"
    assert [field.format_hint for field in fields[1:]] == ["YYYY.MM", "YYYY.MM"]


@pytest.mark.parametrize("mode,button", [("new", "지원하기"), ("existing", "지원서 수정")])
async def test_chosen_application_popup_is_used_for_login_handoff(application, mode, button):
    browser, page, _ = application
    await page.route(
        "**/career/jobs/*",
        lambda route: route.fulfill(
            content_type="text/html; charset=utf-8",
            body=f"<button onclick=\"window.open('/fixture/login?mode={mode}')\">{button}</button>",
        ),
    )
    await browser.context.route(
        "**/fixture/login*",
        lambda route: route.fulfill(
            content_type="text/html; charset=utf-8",
            body='<label>비밀번호<input type="password"></label>',
        ),
    )
    # Routing on the context also covers the popup's first request.
    await browser.context.route(
        "**/*",
        lambda route: (
            route.fallback()
            if "/fixture/login" in route.request.url
            else route.fulfill(content_type="text/html; charset=utf-8", body=FORM)
        ),
    )
    result = await browser.open_application("https://dbgroup.recruiter.co.kr/career/jobs/123", mode)
    assert result["status"] == "user_action_required"
    assert result["url"].endswith(f"/fixture/login?mode={mode}")
    assert (await browser.inspect()).status == "login_required"


async def test_batch_of_100_fields_uses_only_two_full_form_scans(application, profile, monkeypatch):
    from career_autofill.adapters.outbound import playwright_browser as adapter

    browser, page, repository = application
    repository.save_profile(profile)
    await page.set_content(
        "".join(f'<label>항목{i}<input name="field{i}"></label>' for i in range(100))
    )
    service = AutofillService(repository, browser)
    plan = await service.preview_autofill({f"f0:{i}": "basic.name_ko" for i in range(100)})
    scans = 0
    original_scan = adapter.scan_fields

    async def counted_scan(page):
        nonlocal scans
        scans += 1
        return await original_scan(page)

    monkeypatch.setattr(adapter, "scan_fields", counted_scan)
    result = await service.apply_autofill(plan["plan"]["id"])
    assert result["status"] == "applied"
    assert len(result["filled"]) == 100
    assert result["field_checks"] == 100
    assert scans == 2


async def test_batch_stops_if_previous_input_changes_next_target(application, profile):
    browser, page, repository = application
    repository.save_profile(profile)
    await page.set_content(
        '<label>성명<input name="name" '
        "oninput=\"document.querySelector('[name=email]').readOnly=true\"></label>"
        '<label>이메일<input name="email"></label>'
    )
    service = AutofillService(repository, browser)
    plan = (await service.preview_autofill())["plan"]
    result = await service.apply_autofill(plan["id"])
    assert result["status"] == "failed"
    assert result["errors"][0]["field_id"] == "f0:1"
    assert await page.locator('[name="email"]').input_value() == ""
    with pytest.raises(ValueError, match="consumed"):
        await service.apply_autofill(plan["id"])

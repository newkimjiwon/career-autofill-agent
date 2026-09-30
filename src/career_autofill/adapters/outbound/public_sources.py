import re
from urllib.parse import urlsplit

from ...domain.models import JobRole, SourceSnapshot
from ...domain.policies import DB_APPLY, DB_HOST, check_url, now
from .db_job_parser import parse_job


async def snapshot(page) -> SourceSnapshot:
    # Read rendered content; do not use site-private APIs, cookies or hidden application state.
    data = await page.evaluate("""() => ({
      title: document.title, text: document.body.innerText,
      tables: [...document.querySelectorAll('table')].map(table =>
        [...table.rows].map(row => [...row.cells].map(cell => ({
          text: cell.innerText, rowspan: cell.rowSpan || 1, colspan: cell.colSpan || 1
        })))),
      links: [...document.querySelectorAll('a[href]')].filter(a => a.getClientRects().length)
        .map(a => ({text: a.innerText, url: a.href}))
    })""")
    return SourceSnapshot(url=page.url, collected_at=now(), **data)


async def read_public_source(url: str) -> SourceSnapshot:
    from playwright.async_api import async_playwright

    check_url(url)
    async with async_playwright() as runtime:
        browser = await runtime.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.goto(url, wait_until="domcontentloaded")
            check_url(page.url)
            target = "table" if urlsplit(url).hostname == DB_HOST else ".notion-page-content"
            try:
                await page.locator(target).first.wait_for(state="visible", timeout=15000)
            except Exception as exc:
                raise ValueError(
                    "Public content unavailable. Open the page in your browser and import its "
                    "visible snapshot; do not provide a password or private Notion token."
                ) from exc
            return await snapshot(page)
        finally:
            await browser.close()


async def collect_db_jobs() -> tuple[list[JobRole], list[dict[str, str]]]:
    from playwright.async_api import async_playwright

    jobs = []
    failures = []
    async with async_playwright() as runtime:
        browser = await runtime.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.goto(DB_APPLY, wait_until="domcontentloaded")
            await page.locator('a[href*="/career/jobs/"]').first.wait_for(timeout=15000)
            listing = await snapshot(page)
            urls = list(
                dict.fromkeys(
                    link["url"]
                    for link in listing.links
                    if re.fullmatch(r"/career/jobs/\d+", urlsplit(link["url"]).path)
                    and "신입" in link["text"]
                    and "마감" not in link["text"]
                )
            )
            for url in urls:
                try:
                    check_url(url, application=True)
                    await page.goto(url, wait_until="domcontentloaded")
                    await page.get_by_text(re.compile("모집 직무 및 전공")).wait_for(timeout=15000)
                    check_url(page.url, application=True)
                    jobs.extend(parse_job(await snapshot(page)))
                except Exception as exc:
                    failures.append({"url": url, "error": str(exc)[:300]})
        finally:
            await browser.close()
    return jobs, failures


class PlaywrightPublicSources:
    async def read(self, url: str) -> SourceSnapshot:
        return await read_public_source(url)

    async def collect(self) -> tuple[list[JobRole], list[dict[str, str]]]:
        return await collect_db_jobs()

    def parse(self, document: SourceSnapshot) -> list[JobRole]:
        return parse_job(document)

from contextlib import asynccontextmanager
from typing import Literal

from mcp.server.fastmcp import FastMCP

from ...application.autofill import AutofillService
from ...domain.models import CareerProfile, FormField


def create_server(service: AutofillService) -> FastMCP:
    @asynccontextmanager
    async def lifespan(server):
        try:
            yield {}
        finally:
            await service.close_browser()

    mcp = FastMCP(
        "career-autofill",
        lifespan=lifespan,
        instructions=(
            "The user chooses a single job. Hand login/account creation/agreements to the "
            "user. Resume only on the actual application form. preview_autofill already "
            "inspects the page: avoid a redundant inspect when explicit mappings are not needed. "
            "Apply one page-scoped plan in a single call; do not call per field. Never invent "
            "missing information, generate credentials, click submit or agree to terms. "
            "Filling may trigger autosave. Final review and submission belong to the user. "
            "For a host browser, collect one full snapshot, execute the returned actions in "
            "a batch with per-target guards, then verify one fresh snapshot. Refresh after "
            "custom widgets alter the form."
        ),
    )

    @mcp.tool()
    async def open_application(job_url: str, mode: Literal["new", "existing"] = "new") -> dict:
        """Open a chosen new/existing DB application and hand login and consent to the user."""
        return await service.open_application(job_url, mode)

    @mcp.tool()
    async def inspect_application() -> dict:
        """Inspect after manual login; use this when explicit field mappings are needed."""
        return await service.inspect_application()

    @mcp.tool()
    def update_profile(profile: CareerProfile) -> dict:
        """Update source-backed or user-confirmed facts before previewing a fill plan."""
        return service.update_profile(profile)

    @mcp.tool()
    async def preview_autofill(mappings: dict[str, str] | None = None) -> dict:
        """Inspect and plan the whole page once; optional observed field id -> fact path."""
        return await service.preview_autofill(mappings)

    @mcp.tool()
    async def apply_autofill(plan_id: str) -> dict:
        """Fill the whole reviewed page plan and verify existing values without submitting."""
        return await service.apply_autofill(plan_id)

    @mcp.tool()
    def preview_from_snapshot(
        url: str, fields: list[FormField], mappings: dict[str, str] | None = None
    ) -> dict:
        """Plan from a single host browser snapshot without extracting the login session.

        Execute returned actions together through the host browser with individual target
        checks, then call verify_from_snapshot with one fresh full snapshot. Handle custom
        widgets separately using source-backed values and exact visible options.
        """
        return service.preview_from_snapshot(url, fields, mappings)

    @mcp.tool()
    def verify_from_snapshot(plan_id: str, url: str, fields: list[FormField]) -> dict:
        """Verify both host-filled values and preserved fields in the same application."""
        return service.verify_from_snapshot(plan_id, url, fields)

    @mcp.tool()
    async def close_browser() -> dict:
        """Close the dedicated autofill browser after the user finishes reviewing."""
        return await service.close_browser()

    return mcp

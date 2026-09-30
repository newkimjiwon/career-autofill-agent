"""Composition root: the only place that chooses and wires concrete adapters."""

import os
from pathlib import Path

from .adapters.inbound.autofill_mcp import create_server as create_autofill_server
from .adapters.inbound.cli import run as run_cli
from .adapters.inbound.match_mcp import create_server as create_match_server
from .adapters.outbound.form_dom import SCAN_SCRIPT
from .adapters.outbound.json_repository import JsonCareerRepository
from .adapters.outbound.playwright_browser import PlaywrightApplicationBrowser
from .adapters.outbound.private_markdown import PrivateMarkdownRepository
from .adapters.outbound.public_sources import PlaywrightPublicSources
from .application.autofill import AutofillService
from .application.context import ContextService
from .application.matching import MatchingService


def build_matching_service() -> MatchingService:
    repository = JsonCareerRepository(Path(os.environ.get("CAREER_DATA_DIR", "data")))
    sources = PlaywrightPublicSources()
    return MatchingService(repository, sources, sources)


def build_autofill_service() -> AutofillService:
    repository = JsonCareerRepository(Path(os.environ.get("CAREER_DATA_DIR", "data")))
    browser = PlaywrightApplicationBrowser(
        directory=Path(os.environ.get("CAREER_BROWSER_DIR", ".browser")),
        headless=os.environ.get("CAREER_HEADLESS", "false") == "true",
    )
    return AutofillService(repository, browser)


def build_context_service() -> ContextService:
    repository = JsonCareerRepository(Path(os.environ.get("CAREER_DATA_DIR", "data")))
    documents = PrivateMarkdownRepository(repository.store.root / "context")
    return ContextService(repository, documents)


def match_main() -> None:
    create_match_server(build_matching_service(), build_context_service()).run(transport="stdio")


def autofill_main() -> None:
    create_autofill_server(build_autofill_service(), build_context_service()).run(transport="stdio")


def cli_main() -> None:
    run_cli(build_matching_service(), SCAN_SCRIPT, build_context_service())

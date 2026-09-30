import argparse
import json
from pathlib import Path

from ...application.context import ContextService
from ...application.matching import MatchingService
from ...domain.models import CareerProfile, JobRole, SourceSnapshot


def run(
    service: MatchingService,
    scanner_script: str,
    contexts: ContextService,
    argv: list[str] | None = None,
) -> None:
    parser = argparse.ArgumentParser(description="Career MCP local data and recommendation tools")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("import-profile", "import-jobs", "import-job-snapshot"):
        command = commands.add_parser(name)
        command.add_argument("file", type=Path)
    report = commands.add_parser("recommend")
    report.add_argument("--limit", type=int, default=5)
    commands.add_parser("schema")
    commands.add_parser("form-scanner", help="Print read-only JavaScript for host form snapshots")
    commands.add_parser("init-context", help="Create a private, empty local career guide")
    context = commands.add_parser("context", help="Generate or reuse private Markdown from JSON")
    context.add_argument("--section", choices=("matching", "autofill"), default="matching")
    context.add_argument("--refresh", action="store_true", help="Rebuild Markdown, not source data")
    context.add_argument("--print", dest="print_context", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "schema":
        print(json.dumps(CareerProfile.model_json_schema(), ensure_ascii=False, indent=2))
    elif args.command == "form-scanner":
        print(scanner_script)
    elif args.command == "init-context":
        print(contexts.initialize_notes()["path"])
    elif args.command == "context":
        try:
            result = contexts.get_reusable_context(args.section, args.refresh)
        except ValueError as error:
            parser.error(str(error))
        if args.print_context:
            print(result["context"], end="")
        else:
            print(result["path"])
            print(f"cache_hit={result['cache_hit']} elapsed_ms={result['elapsed_ms']}")
    elif args.command == "import-profile":
        profile = CareerProfile.model_validate_json(args.file.read_text())
        service.save_profile(profile)
        print(f"Saved {len(profile.facts())} facts and {len(profile.experiences)} experiences.")
    elif args.command == "import-jobs":
        jobs = [JobRole.model_validate(job) for job in json.loads(args.file.read_text())]
        print(service.save_jobs(jobs))
    elif args.command == "import-job-snapshot":
        document = SourceSnapshot.model_validate_json(args.file.read_text())
        print(service.import_job_snapshot(document))
    elif args.command == "recommend":
        if not 1 <= args.limit <= 30:
            parser.error("--limit must be between 1 and 30")
        for index, match in enumerate(service.recommend_jobs(args.limit)["matches"], 1):
            job = match["job"]
            print(f"{index}. {job['company']} / {job['title']} — {match['score']}")
            print(f"   {job['source_url']}")
            for gap in match["gaps"]:
                print(f"   확인: {gap}")

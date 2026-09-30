"""Compare separate and batched Git checks using synthetic, temporary profile data."""

import argparse
import json
import math
import statistics
import tempfile
from pathlib import Path

from career_autofill.adapters.outbound.json_repository import JsonCareerRepository
from career_autofill.adapters.outbound.private_markdown import PrivateMarkdownRepository
from career_autofill.application.context import ContextService
from career_autofill.domain.models import CareerProfile


class SeparateGitChecks(PrivateMarkdownRepository):
    """Baseline: validate Markdown and metadata individually with the same rules."""

    def _paths(self, *names: str) -> tuple[Path, ...]:
        return tuple(super(SeparateGitChecks, self)._paths(name)[0] for name in names)


def summary(results: list[dict]) -> dict:
    timings = sorted(result["elapsed_ms"] for result in results)
    return {
        "median_ms": round(statistics.median(timings), 3),
        "p95_ms": timings[math.ceil(len(timings) * 0.95) - 1],
        "all_cache_hits": all(result["cache_hit"] for result in results),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=30)
    args = parser.parse_args()
    if not 2 <= args.samples <= 1000:
        parser.error("--samples must be between 2 and 1000")
    root = Path(__file__).resolve().parents[1]
    profile = CareerProfile.model_validate_json(
        (root / "examples" / "profile.example.json").read_text(encoding="utf-8")
    )
    data = root / "data"
    data.mkdir(exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix="context-benchmark-", dir=data) as temporary:
        repository = JsonCareerRepository(Path(temporary) / "data")
        repository.save_profile(profile)
        directory = repository.store.root / "context"
        services = {
            "separate_git_checks": ContextService(repository, SeparateGitChecks(directory)),
            "batched_git_checks": ContextService(repository, PrivateMarkdownRepository(directory)),
        }
        services["batched_git_checks"].get_reusable_context()
        results: dict[str, list[dict]] = {name: [] for name in services}
        for index in range(args.samples):
            order = list(services) if index % 2 == 0 else list(reversed(services))
            for name in order:
                results[name].append(services[name].get_reusable_context())
        print(
            json.dumps(
                {
                    "profile": "synthetic",
                    "scope": "local context only; excludes MCP, model and browser latency",
                    "samples_per_case": args.samples,
                    **{name: summary(values) for name, values in results.items()},
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()

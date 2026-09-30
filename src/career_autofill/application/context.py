"""Reuse local facts without reading sources or interpreting them again."""

from time import perf_counter

from ..domain.context import CONTEXT_GUIDE, CONTEXT_VERSION, ContextSection, build_context
from ..domain.planning import fingerprint
from ..domain.policies import now
from .ports import ContextRepository, ProfileRepository


class ContextService:
    def __init__(self, profiles: ProfileRepository, documents: ContextRepository):
        self.profiles = profiles
        self.documents = documents

    def initialize_notes(self) -> dict:
        return {"path": self.documents.initialize_notes(CONTEXT_GUIDE), "private": True}

    def get_reusable_context(
        self, section: ContextSection = "matching", refresh: bool = False
    ) -> dict:
        started = perf_counter()
        if section not in {"matching", "autofill"}:
            raise ValueError("section must be matching or autofill")
        profile = self.profiles.load_profile()
        cached = None if refresh else self.documents.load_context(section)
        cache_hit = (
            cached is not None
            and cached.version == CONTEXT_VERSION
            and cached.profile_fingerprint == fingerprint(profile)
        )
        if cache_hit:
            document = cached
            path = self.documents.context_path(section)
        else:
            document = build_context(profile, section, now())
            path = self.documents.save_context(document)
        return {
            "section": section,
            "path": path,
            "private": True,
            "cache_hit": cache_hit,
            "generated_at": document.generated_at.isoformat(),
            "profile_fingerprint": document.profile_fingerprint,
            "elapsed_ms": round((perf_counter() - started) * 1000, 3),
            "character_count": len(document.markdown),
            "source_freshness": "local_profile_only",
            "context": document.markdown,
        }

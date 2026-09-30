import re
import unicodedata
from datetime import datetime

from .models import CareerProfile, JobMatch, JobRole, MatchEvidence
from .policies import now

# A transparent baseline, not a hiring decision or a probability of acceptance.
TOPICS = {
    "AI 모델": (
        "ai",
        "인공지능",
        "머신러닝",
        "딥러닝",
        "ml/dl",
        "pytorch",
        "kobert",
        "yolov8",
        "dinov2",
        "모델 개발",
    ),
    "생성형 AI / LLM": ("생성형", "llm", "chatgpt", "프롬프트", "prompt engineering"),
    "AI Agent 프레임워크": ("ai agent", "langchain", "langgraph", "agents sdk"),
    "데이터 분석 / 파이프라인": (
        "데이터 분석",
        "데이터분석",
        "데이터 파이프라인",
        "data science",
        "크롤링",
        "전처리",
        "데이터 수집",
    ),
    "웹 / API 개발": (
        "s/w",
        "어플리케이션",
        "애플리케이션",
        "웹",
        "web",
        "api",
        "flask",
        "django",
        "fastapi",
        "backend",
    ),
    "인프라 / 클라우드": (
        "인프라",
        "클라우드",
        "서버",
        "linux",
        "aws",
        "gcp",
        "docker",
        "컨테이너",
        "nginx",
        "배포",
    ),
    "데이터베이스": ("데이터베이스", "dbms", "dba", "sql", "mysql", "redis", "sap"),
    "정보보호": ("정보보호", "접근통제", "방화벽", "보안", "isms", "iso/iec 27001"),
}
SPECIALIZED_TECH = {
    "Java": ("java",),
    "JSP": ("jsp",),
    "Spring": ("spring",),
    "React": ("react",),
    "Oracle": ("oracle", "오라클"),
    "MSSQL": ("mssql",),
    "SAP": ("sap",),
    "Exadata": ("exadata",),
    "Kubernetes": ("kubernetes", "쿠버네티스"),
    "R": ("r",),
    "SAS": ("sas",),
    "Device Physics": ("device physics",),
    "SPICE": ("spice",),
    "TCAD": ("tcad",),
    "보험계리": ("보험계리",),
    "정보보호 법령": ("법령",),
    "ISMS": ("isms",),
    "ISO/IEC 27001": ("iso/iec 27001",),
}


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def contains(text: str, terms: tuple[str, ...]) -> bool:
    text = normalize(text)
    for term in terms:
        pattern = re.escape(normalize(term))
        if term.isascii():
            pattern = r"(?<![a-z0-9])" + pattern + r"(?![a-z0-9])"
        if re.search(pattern, text):
            return True
    return False


def profile_evidence(profile: CareerProfile, terms: tuple[str, ...]) -> tuple[str, str] | None:
    for experience in profile.experiences:
        content = f"{experience.title}: {experience.summary} {' '.join(experience.skills)}"
        if contains(content, terms):
            return experience.source, content[:450]
    for fact in profile.facts().values():
        if fact.status != "unverified" and contains(fact.value, terms):
            return fact.source, fact.value
    # Skills still need a visible portfolio source for the returned evidence.
    if contains(" ".join(profile.skills), terms) and profile.basic.get("portfolio_url"):
        source = profile.basic["portfolio_url"].value
        return source, "포트폴리오 Skills: " + ", ".join(profile.skills)
    return None


def rank_jobs(
    profile: CareerProfile,
    jobs: list[JobRole],
    limit: int = 5,
    at: datetime | None = None,
) -> list[JobMatch]:
    at = at or now()
    if at.tzinfo is None:
        raise ValueError("A timezone-aware time is required.")
    matches = []
    all_profile_text = " ".join(
        [
            *profile.skills,
            *[f.value for f in profile.facts().values() if f.status != "unverified"],
            *[f"{e.title} {e.summary} {' '.join(e.skills)}" for e in profile.experiences],
        ]
    )
    for job in jobs:
        if job.deadline and job.deadline <= at:
            continue
        if "신입" not in job.career_type:
            continue
        duty_text = f"{job.title} {job.responsibilities}"
        topics = [topic for topic, terms in TOPICS.items() if contains(duty_text, terms)]
        evidence = []
        matched = 0
        gaps = []
        for topic in topics:
            found = profile_evidence(profile, TOPICS[topic])
            if found:
                matched += 1
                evidence.append(
                    MatchEvidence(
                        topic=topic,
                        profile_source=found[0],
                        profile_excerpt=found[1],
                        job_excerpt=duty_text,
                    )
                )
            else:
                gaps.append(f"{topic}: 포트폴리오에서 직접 근거를 찾지 못함")
        score = round(70 * matched / len(topics)) + min(20, 4 * matched) if topics else 0
        if matched and any(
            profile_evidence(profile, terms) and contains(job.preferred, terms)
            for terms in TOPICS.values()
        ):
            score += 10
        missing_tech = [
            label
            for label, terms in SPECIALIZED_TECH.items()
            if contains(job.qualifications + " " + job.preferred + " " + duty_text, terms)
            and not contains(all_profile_text, terms)
        ]
        # These postings name alternatives, not simultaneous mandatory requirements.
        if (
            "R" in missing_tech
            and contains(job.qualifications, ("python",))
            and contains(all_profile_text, ("python",))
        ):
            missing_tech.remove("R")
        if (
            "Kubernetes" in missing_tech
            and contains(job.preferred, ("도커", "docker"))
            and contains(all_profile_text, ("도커", "docker"))
        ):
            missing_tech.remove("Kubernetes")
        gaps.extend(f"{tech}: 요구/우대 기술의 실제 경험 확인 필요" for tech in missing_tech)
        score = max(0, score - min(25, 5 * len(missing_tech)))
        checks = ["직무 관련성 점수이며 합격 가능성 또는 지원자격 충족을 뜻하지 않음"]
        if job.deadline is None:
            checks.append("마감시간 파싱 불가: 지원 전 원문에서 접수 중인지 확인 필요")
        graduation = [record.get("status") for record in profile.education]
        if not any(f and f.status != "unverified" and f.value == "졸업" for f in graduation):
            checks.append("졸업 여부 및 졸업예정 시점 확인 필요")
        if "병역" in job.general_qualifications and not profile.military.get("status"):
            checks.append("병역 요건 확인 필요: 정보가 없어 추정하지 않음")
        if "해외여행" in job.general_qualifications:
            checks.append("해외여행 결격사유는 사용자 확인 필요")
        if "제조" in duty_text:
            checks.append("제조/품질/생산 도메인의 실제 경험 확인 필요")
        checks.extend(profile.issues)
        matches.append(
            JobMatch(
                job=job,
                score=min(100, score),
                evidence=evidence,
                gaps=gaps,
                checks=checks,
            )
        )
    return sorted(matches, key=lambda match: (-match.score, match.job.id))[:limit]

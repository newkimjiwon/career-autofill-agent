from datetime import datetime

import pytest

from career_autofill.adapters.outbound.db_job_parser import parse_job
from career_autofill.domain.matching import contains, rank_jobs
from career_autofill.domain.models import Cell, SourceSnapshot
from career_autofill.domain.policies import SEOUL, check_url


def test_rowspan_keeps_the_correct_role_qualifications_and_location():
    document = SourceSnapshot(
        url="https://dbgroup.recruiter.co.kr/career/jobs/125826",
        title="[테스트회사] 신입 모집",
        collected_at=datetime(2026, 9, 30, tzinfo=SEOUL),
        text="마감일\n2026.10.02 오후 5:00\n응시자격\n병역필 또는 면제자\n전형방법",
        tables=[
            [
                [
                    Cell(text=t)
                    for t in (
                        "회사",
                        "모집직무",
                        "직무내용",
                        "지원자격 및 우대사항",
                        "인원",
                        "지역",
                    )
                ],
                [Cell(text="테스트회사", rowspan=3), Cell(text="* 안내", colspan=5)],
                [
                    Cell(text="AI"),
                    Cell(text="AI 개발"),
                    Cell(text="컴퓨터 전공 ※ 우대사항 LLM", rowspan=2),
                    Cell(text="O명"),
                    Cell(text="서울", rowspan=2),
                ],
                [Cell(text="API"), Cell(text="웹 API 개발"), Cell(text="O명")],
            ]
        ],
    )
    roles = parse_job(document)
    assert [role.title for role in roles] == ["AI", "API"]
    assert roles[1].qualifications == "컴퓨터 전공 "
    assert roles[1].preferred == " LLM"
    assert roles[1].location == "서울"
    assert roles[0].deadline.hour == 17
    assert "병역" in roles[0].general_qualifications


def test_expired_roles_are_excluded_at_korean_deadline(profile, job_factory):
    job = job_factory()
    assert rank_jobs(profile, [job], at=datetime(2026, 10, 2, 16, 59, tzinfo=SEOUL))
    assert not rank_jobs(profile, [job], at=datetime(2026, 10, 2, 17, tzinfo=SEOUL))


def test_generic_ai_preference_does_not_turn_hr_into_ai_role(profile, job_factory):
    roles = [
        job_factory(
            id="hr",
            title="인사",
            responsibilities="인력 채용 및 교육 운영",
            preferred="AI 관련 프로젝트 경험자",
        ),
        job_factory(id="it", responsibilities="AI 모델 개발, API 연계", preferred="Docker 경험자"),
    ]
    results = rank_jobs(profile, roles, at=datetime(2026, 9, 30, tzinfo=SEOUL))
    assert results[0].job.id == "it"
    assert results[1].score == 0
    assert results[0].evidence[0].profile_source


def test_missing_java_is_reported_not_inferred(profile, job_factory):
    role = job_factory(responsibilities="어플리케이션 개발 JAVA JSP Spring")
    result = rank_jobs(profile, [role], at=datetime(2026, 9, 30, tzinfo=SEOUL))[0]
    assert any("Java" in gap for gap in result.gaps)
    assert any("Spring" in gap for gap in result.gaps)


def test_ascii_terms_are_not_accidental_substrings():
    assert not contains("Oracle Server", ("r",))
    assert not contains("Training Pipeline", ("ai",))
    assert contains("Python, R 등", ("r",))


@pytest.mark.parametrize(
    "url",
    [
        "http://dbgroup.recruiter.co.kr/career/apply",
        "https://evil.example/career/apply",
        "https://dbgroup.recruiter.co.kr.evil.example/",
        "https://user:password@dbgroup.recruiter.co.kr/",
        "https://dbgroup.recruiter.co.kr:9999/",
    ],
)
def test_only_supported_https_origins(url):
    with pytest.raises(ValueError):
        check_url(url, application=True)

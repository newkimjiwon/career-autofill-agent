from datetime import datetime

import pytest

from career_autofill.domain.models import CareerProfile, Experience, Fact, JobRole
from career_autofill.domain.policies import SEOUL


@pytest.fixture
def profile():
    source = "https://example.notion.site/portfolio"
    return CareerProfile(
        basic={
            "name_ko": Fact(value="테스트지원자", source="user:confirmed", status="user"),
            "email": Fact(value="test@example.com", source=source),
            "phone": Fact(value="010-0000-0000", source=source),
            "portfolio_url": Fact(value=source, source=source),
        },
        education=[
            {
                "school": Fact(value="테스트대학교", source=source),
                "start": Fact(value="2020-03", source=source),
                "status": Fact(value="졸업", source="user:confirmed", status="user"),
            }
        ],
        experiences=[
            Experience(
                title="AI 모델과 웹 서비스",
                summary="머신러닝 모델 개발, Flask API 및 Docker GCP 배포",
                skills=["Python", "Flask", "Docker", "GCP"],
                source=source,
            ),
            Experience(
                title="AI NPC", summary="ChatGPT API 기반 생성형 대화 서비스", source=source
            ),
        ],
        skills=["Python", "Docker", "MySQL"],
    )


@pytest.fixture
def job_factory():
    def factory(**values):
        defaults = {
            "id": "125818:0",
            "company": "테스트회사",
            "title": "IT",
            "responsibilities": "AI 모델 개발, 데이터 분석, API 연계",
            "source_url": "https://dbgroup.recruiter.co.kr/career/jobs/125818",
            "deadline": datetime(2026, 10, 2, 17, tzinfo=SEOUL),
            "collected_at": datetime(2026, 9, 30, 12, tzinfo=SEOUL),
        }
        return JobRole(**(defaults | values))

    return factory

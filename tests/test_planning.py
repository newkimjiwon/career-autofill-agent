import pytest

from career_autofill.domain.models import Fact, FormField
from career_autofill.domain.planning import build_plan

URL = "https://dbgroup.recruiter.co.kr/fixture/application"


def field(index, label, **values):
    return FormField(id=f"f0:{index}", index=index, label=label, kind="text", **values)


def test_missing_sensitive_and_existing_fields_are_not_guessed(profile):
    fields = [
        field(0, "성명"),
        field(1, "생년월일"),
        field(2, "이메일", value="keep@example.com"),
        FormField(id="f0:3", index=3, label="약관 동의", kind="checkbox"),
        FormField(id="f0:4", index=4, label="비밀번호", kind="password"),
    ]
    plan = build_plan(URL, fields, profile)
    assert [action.field.label for action in plan.actions] == ["성명"]
    assert len(plan.skipped) == 4


def test_month_precision_is_not_invented_for_a_day_field(profile):
    fields = [FormField(id="f0:0", index=0, label="입학일", kind="date")]
    assert not build_plan(URL, fields, profile).actions
    fields[0].kind = "month"
    assert build_plan(URL, fields, profile).actions[0].value == "2020-03"


def test_repeated_school_fields_need_explicit_record_mapping(profile):
    fields = [field(0, "학교명"), field(1, "학교명")]
    assert not build_plan(URL, fields, profile).actions
    profile.education.append({"school": Fact(value="테스트고등학교", source="user:confirmed")})
    plan = build_plan(
        URL, fields, profile, {"f0:0": "education.0.school", "f0:1": "education.1.school"}
    )
    assert [action.value for action in plan.actions] == ["테스트대학교", "테스트고등학교"]


def test_select_maps_display_label_to_actual_value(profile):
    fields = [
        FormField(
            id="f0:0",
            index=0,
            label="졸업구분",
            kind="select-one",
            options=[{"label": "선택", "value": ""}, {"label": "졸업", "value": "GRAD"}],
        )
    ]
    assert build_plan(URL, fields, profile).actions[0].value == "GRAD"


def test_unverified_facts_stay_unfilled(profile):
    profile.basic["name_ko"].status = "unverified"
    assert not build_plan(URL, [field(0, "성명")], profile).actions


def test_observed_mrs_month_format_keeps_month_precision(profile):
    fields = [field(0, "입학년월", format_hint="YYYY.MM")]
    assert build_plan(URL, fields, profile).actions[0].value == "2020.03"
    fields[0].format_hint = "YYYY.MM.DD"
    assert not build_plan(URL, fields, profile).actions


def test_ambiguous_control_ids_are_rejected(profile):
    with pytest.raises(ValueError, match="unique ids"):
        build_plan(URL, [field(0, "성명"), field(0, "이메일")], profile)

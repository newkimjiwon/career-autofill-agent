import hashlib
import json
import re
import uuid

from .models import CareerProfile, FillAction, FillPlan, FormField
from .policies import now

ALIASES = {
    "basic.name_ko": ("성명", "이름", "한글성명", "한글이름", "성명(한글)"),
    "basic.name_en": ("영문성명", "영문이름", "성명(영문)"),
    "basic.email": ("이메일", "이메일주소", "email", "e-mail"),
    "basic.phone": ("휴대폰", "휴대전화", "휴대전화번호", "휴대폰번호", "연락처"),
    "basic.birth_date": ("생년월일", "birthdate"),
    "basic.portfolio_url": ("포트폴리오", "포트폴리오url", "포트폴리오주소"),
    "basic.github_url": ("github", "githuburl", "깃허브"),
    "basic.postal_code": ("우편번호",),
    "basic.address_line1": (
        "주소",
        "기본주소",
    ),
    "basic.address_line2": ("상세주소",),
    "education.0.school": ("학교", "학교명", "대학교", "대학교명", "출신학교"),
    "education.0.major": ("전공", "학과", "전공명", "주전공"),
    "education.0.gpa": ("학점", "전체학점", "평점", "평균학점"),
    "education.0.gpa_scale": ("학점기준", "만점", "만점기준"),
    "education.0.status": ("졸업구분", "졸업상태"),
    "education.0.start": ("입학일", "입학년월", "입학연월"),
    "education.0.end": ("졸업일", "졸업년월", "졸업연월"),
    "military.status": ("병역구분", "병역사항", "병역여부"),
    "military.branch": ("군별",),
    "military.rank": ("계급",),
    "military.start": ("입대일", "입대일자", "입대년월"),
    "military.end": ("전역일", "전역일자", "전역년월"),
    "military.discharge_type": ("전역구분",),
}
SUPPORTED_KINDS = {
    "text",
    "email",
    "tel",
    "url",
    "number",
    "date",
    "month",
    "textarea",
    "select-one",
}
BLOCKED_TERMS = re.compile(
    r"비밀번호|password|인증번호|otp|동의|약관|주민등록|보훈|장애|성별", re.I
)


def label_key(label: str) -> str:
    return re.sub(r"[\s*：:]", "", label).casefold()


def fingerprint(value) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def fields_fingerprint(url: str, fields: list[FormField]) -> str:
    return fingerprint({"url": url, "fields": [field.model_dump() for field in fields]})


def field_path(field: FormField, fields: list[FormField]) -> str | None:
    key = label_key(field.label)
    for path, aliases in ALIASES.items():
        if key in {label_key(alias) for alias in aliases}:
            # Repeated school/certificate fields need a host-reviewed explicit mapping.
            if path.startswith("education.") and (
                "고등" in field.section
                or sum(label_key(candidate.label) == key for candidate in fields) > 1
            ):
                return None
            return path
    return None


def format_value(field: FormField, value: str) -> str | None:
    if field.kind == "select-one":
        options = [
            option for option in field.options if label_key(option["label"]) == label_key(value)
        ]
        if len(options) != 1 or not options[0]["value"]:
            return None
        return options[0]["value"]
    if field.kind == "date" and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    if field.kind == "month" and not re.fullmatch(r"\d{4}-\d{2}", value):
        return None
    if field.kind == "number" and not re.fullmatch(r"\d+(?:\.\d+)?", value):
        return None
    if field.format_hint:
        pattern = r"\d{4}-\d{2}" if field.format_hint == "YYYY.MM" else r"\d{4}-\d{2}-\d{2}"
        if not re.fullmatch(pattern, value):
            return None
        value = value.replace("-", ".")
    if field.kind == "tel" and field.maxlength == 11:
        value = re.sub(r"[ -]", "", value)
    if field.maxlength >= 0 and len(value) > field.maxlength:
        return None
    return value


def build_plan(
    url: str,
    fields: list[FormField],
    profile: CareerProfile,
    mappings: dict[str, str] | None = None,
) -> FillPlan:
    mappings = mappings or {}
    ids = [field.id for field in fields]
    if len(set(ids)) != len(ids) or any(
        field.id != f"f{field.frame}:{field.index}" for field in fields
    ):
        raise ValueError("Fields must have unique ids matching their frame and control index.")
    unknown = set(mappings) - {field.id for field in fields}
    if unknown:
        raise ValueError(f"Unknown field ids: {sorted(unknown)}")
    facts = profile.facts()
    actions, skipped = [], []
    for field in fields:
        reason = None
        path = mappings.get(field.id) or field_path(field, fields)
        if field.disabled or field.readonly:
            reason = "disabled_or_readonly"
        elif field.kind not in SUPPORTED_KINDS or BLOCKED_TERMS.search(field.label + field.name):
            reason = "manual_field"
        elif not path:
            reason = "needs_field_mapping"
        elif path not in facts or not facts[path].value or facts[path].status == "unverified":
            reason = f"missing_or_unverified:{path}"
        else:
            fact = facts[path]
            value = format_value(field, fact.value)
            if value is None:
                reason = "format_or_option_needs_review"
            elif field.value and field.value != value:
                # A default select option is still existing data; do not overwrite it blindly.
                reason = "existing_value_needs_review"
            elif field.value == value:
                reason = "already_matches"
            else:
                actions.append(
                    FillAction(
                        field=field,
                        profile_path=path,
                        value=value,
                        source=fact.source,
                    )
                )
        if reason:
            skipped.append({"field_id": field.id, "label": field.label, "reason": reason})
    return FillPlan(
        id=uuid.uuid4().hex,
        url=url,
        fingerprint=fields_fingerprint(url, fields),
        profile_fingerprint=fingerprint(profile),
        created_at=now(),
        actions=actions,
        skipped=skipped,
        observed_fields=fields,
    )

"""Pure plan guards and read-back rules shared by native and host browser flows."""

from .models import CareerProfile, FillPlan, FormField
from .planning import fields_fingerprint, fingerprint


def validate_plan_profile(plan: FillPlan, profile: CareerProfile) -> None:
    if plan.state != "preview":
        raise ValueError("Plan already consumed. Inspect and preview again.")
    if fingerprint(profile) != plan.profile_fingerprint:
        raise ValueError("The profile changed after preview. Create a new plan.")


def validate_before_fill(plan: FillPlan, url: str, fields: list[FormField]) -> None:
    if fields_fingerprint(url, fields) != plan.fingerprint:
        raise ValueError("The form changed after preview. Inspect and create a new plan.")


def verify_readback(
    plan: FillPlan, fields: list[FormField], completed_ids: set[str] | None = None
) -> tuple[list[dict], list[dict]]:
    current = {field.id: field for field in fields}
    if len(current) != len(fields):
        raise ValueError("Duplicate field ids in verification snapshot.")
    actions = {action.field.id: action for action in plan.actions}
    completed_ids = set(actions) if completed_ids is None else completed_ids
    observed = plan.observed_fields or [action.field for action in plan.actions]
    verified, errors = [], []
    if {field.id for field in observed} != set(current):
        errors.append({"field_id": "", "error": "Observed control set changed"})
    for before in observed:
        expected = before.model_copy(
            update={"value": actions[before.id].value} if before.id in completed_ids else {}
        )
        if current.get(before.id) != expected:
            errors.append({"field_id": before.id, "error": "Field or preserved value changed"})
        elif before.id in completed_ids:
            verified.append(
                {
                    "field_id": before.id,
                    "label": before.label,
                    "profile_path": actions[before.id].profile_path,
                }
            )
    return verified, errors

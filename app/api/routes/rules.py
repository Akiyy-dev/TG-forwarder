"""Keyword rules and rule-groups API (super_admin)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import Field

from app.api.dependencies import SuperAdminUser, get_ctx
from app.api.errors import AppError
from app.api.pagination import PageParams, build_page
from app.api.schemas import APIModel, Envelope
from app.context import AppContext
from app.services.rules_service import RulesService, RulesServiceError

router = APIRouter(tags=["rules"])


class RuleOut(APIModel):
    id: int
    name: str
    description: str | None = None
    enabled: bool
    priority: int
    rule_type: str
    match_type: str
    pattern: str
    replacement: str | None = None
    case_sensitive: bool
    whole_word: bool
    use_regex: bool
    source_channel_ids: list[int] | None = None
    target_channel_ids: list[int] | None = None
    message_types: list[str] | None = None
    action: str
    stop_processing: bool
    group_id: int | None = None
    hit_count: int
    last_hit_at: Any = None
    created_by: int | None = None
    created_at: Any = None
    updated_at: Any = None


class RuleWriteRequest(APIModel):
    name: str = Field(min_length=1, max_length=128)
    pattern: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=512)
    enabled: bool = True
    priority: int = 100
    rule_type: str = "keyword"
    match_type: str = "contains"
    replacement: str | None = None
    case_sensitive: bool = False
    whole_word: bool = False
    use_regex: bool = False
    source_channel_ids: list[int] | None = None
    target_channel_ids: list[int] | None = None
    message_types: list[str] | None = None
    action: str = "flag"
    stop_processing: bool = False
    group_id: int | None = None


class RulePatchRequest(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    pattern: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=512)
    enabled: bool | None = None
    priority: int | None = None
    rule_type: str | None = None
    match_type: str | None = None
    replacement: str | None = None
    case_sensitive: bool | None = None
    whole_word: bool | None = None
    use_regex: bool | None = None
    source_channel_ids: list[int] | None = None
    target_channel_ids: list[int] | None = None
    message_types: list[str] | None = None
    action: str | None = None
    stop_processing: bool | None = None
    group_id: int | None = None


class RuleTestRequest(APIModel):
    sample_text: str = Field(min_length=0, max_length=8192)
    rule: RuleWriteRequest | None = None


class RuleImportRequest(APIModel):
    items: list[RuleWriteRequest] = Field(min_length=1, max_length=500)


class GroupOut(APIModel):
    id: int
    name: str
    description: str | None = None
    enabled: bool
    priority: int
    created_at: Any = None
    updated_at: Any = None


class GroupWriteRequest(APIModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    enabled: bool = True
    priority: int = 100


class GroupPatchRequest(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    enabled: bool | None = None
    priority: int | None = None


def _svc(ctx: AppContext) -> RulesService:
    return RulesService(ctx.session_factory)


def _map_err(exc: RulesServiceError) -> AppError:
    status = {"not_found": 404, "conflict": 409, "validation_error": 422}.get(exc.code, 400)
    return AppError(exc.code, exc.message, status_code=status)


@router.get("/rules", response_model=Envelope[dict[str, Any]])
async def list_rules(
    _admin: SuperAdminUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    enabled: bool | None = None,
    group_id: int | None = None,
    q: str | None = None,
) -> Envelope[dict[str, Any]]:
    params = PageParams(page=page, page_size=page_size)
    rows, total = await _svc(ctx).list_rules(
        page=page, page_size=page_size, enabled=enabled, group_id=group_id, q=q
    )
    items = [RuleOut.model_validate(r).model_dump(mode="json") for r in rows]
    return Envelope(data=build_page(items=items, total=total, params=params))


@router.post("/rules", response_model=Envelope[RuleOut])
async def create_rule(
    body: RuleWriteRequest,
    admin: SuperAdminUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[RuleOut]:
    try:
        rule = await _svc(ctx).create_rule(body.model_dump(), created_by=admin.id)
    except RulesServiceError as exc:
        raise _map_err(exc) from exc
    return Envelope(data=RuleOut.model_validate(rule))


@router.get("/rules/export", response_model=Envelope[dict[str, Any]])
async def export_rules(
    _admin: SuperAdminUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[dict[str, Any]]:
    items = await _svc(ctx).export_rules()
    return Envelope(data={"items": items})


@router.post("/rules/import", response_model=Envelope[dict[str, Any]])
async def import_rules(
    body: RuleImportRequest,
    admin: SuperAdminUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[dict[str, Any]]:
    try:
        created = await _svc(ctx).import_rules(
            [item.model_dump() for item in body.items],
            created_by=admin.id,
        )
    except RulesServiceError as exc:
        raise _map_err(exc) from exc
    return Envelope(
        data={
            "created": len(created),
            "ids": [r.id for r in created],
        }
    )


@router.post("/rules/test", response_model=Envelope[dict[str, Any]])
async def test_rule_payload(
    body: RuleTestRequest,
    _admin: SuperAdminUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[dict[str, Any]]:
    if body.rule is None:
        raise AppError("validation_error", "rule payload is required", status_code=422)
    try:
        result = await _svc(ctx).test_payload(body.rule.model_dump(), body.sample_text)
    except RulesServiceError as exc:
        raise _map_err(exc) from exc
    return Envelope(data=result)


@router.get("/rules/{rule_id}", response_model=Envelope[RuleOut])
async def get_rule(
    rule_id: int,
    _admin: SuperAdminUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[RuleOut]:
    try:
        rule = await _svc(ctx).get_rule(rule_id)
    except RulesServiceError as exc:
        raise _map_err(exc) from exc
    return Envelope(data=RuleOut.model_validate(rule))


@router.patch("/rules/{rule_id}", response_model=Envelope[RuleOut])
async def patch_rule(
    rule_id: int,
    body: RulePatchRequest,
    _admin: SuperAdminUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[RuleOut]:
    try:
        rule = await _svc(ctx).update_rule(
            rule_id, body.model_dump(exclude_unset=True)
        )
    except RulesServiceError as exc:
        raise _map_err(exc) from exc
    return Envelope(data=RuleOut.model_validate(rule))


@router.delete("/rules/{rule_id}", response_model=Envelope[dict[str, Any]])
async def delete_rule(
    rule_id: int,
    _admin: SuperAdminUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[dict[str, Any]]:
    try:
        await _svc(ctx).delete_rule(rule_id)
    except RulesServiceError as exc:
        raise _map_err(exc) from exc
    return Envelope(data={"deleted": True, "id": rule_id})


@router.post("/rules/{rule_id}/duplicate", response_model=Envelope[RuleOut])
async def duplicate_rule(
    rule_id: int,
    admin: SuperAdminUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[RuleOut]:
    try:
        rule = await _svc(ctx).duplicate_rule(rule_id, created_by=admin.id)
    except RulesServiceError as exc:
        raise _map_err(exc) from exc
    return Envelope(data=RuleOut.model_validate(rule))


@router.post("/rules/{rule_id}/test", response_model=Envelope[dict[str, Any]])
async def test_existing_rule(
    rule_id: int,
    body: RuleTestRequest,
    _admin: SuperAdminUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[dict[str, Any]]:
    try:
        result = await _svc(ctx).test_existing(rule_id, body.sample_text)
    except RulesServiceError as exc:
        raise _map_err(exc) from exc
    return Envelope(data=result)


@router.get("/rule-execution-logs", response_model=Envelope[dict[str, Any]])
async def list_execution_logs(
    _admin: SuperAdminUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    rule_id: int | None = None,
) -> Envelope[dict[str, Any]]:
    params = PageParams(page=page, page_size=page_size)
    rows, total = await _svc(ctx).list_execution_logs(
        page=page, page_size=page_size, rule_id=rule_id
    )
    items = [
        {
            "id": r.id,
            "rule_id": r.rule_id,
            "rule_name": r.rule_name,
            "action": r.action,
            "matched_text": r.matched_text,
            "review_task_id": r.review_task_id,
            "processed_message_id": r.processed_message_id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    return Envelope(data=build_page(items=items, total=total, params=params))


@router.get("/rule-groups", response_model=Envelope[dict[str, Any]])
async def list_groups(
    _admin: SuperAdminUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[dict[str, Any]]:
    groups = await _svc(ctx).list_groups()
    items = [GroupOut.model_validate(g).model_dump(mode="json") for g in groups]
    return Envelope(data={"items": items})


@router.post("/rule-groups", response_model=Envelope[GroupOut])
async def create_group(
    body: GroupWriteRequest,
    _admin: SuperAdminUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[GroupOut]:
    try:
        group = await _svc(ctx).create_group(body.model_dump())
    except RulesServiceError as exc:
        raise _map_err(exc) from exc
    return Envelope(data=GroupOut.model_validate(group))


@router.patch("/rule-groups/{group_id}", response_model=Envelope[GroupOut])
async def patch_group(
    group_id: int,
    body: GroupPatchRequest,
    _admin: SuperAdminUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[GroupOut]:
    try:
        group = await _svc(ctx).update_group(
            group_id, body.model_dump(exclude_unset=True)
        )
    except RulesServiceError as exc:
        raise _map_err(exc) from exc
    return Envelope(data=GroupOut.model_validate(group))


@router.delete("/rule-groups/{group_id}", response_model=Envelope[dict[str, Any]])
async def delete_group(
    group_id: int,
    _admin: SuperAdminUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[dict[str, Any]]:
    try:
        await _svc(ctx).delete_group(group_id)
    except RulesServiceError as exc:
        raise _map_err(exc) from exc
    return Envelope(data={"deleted": True, "id": group_id})

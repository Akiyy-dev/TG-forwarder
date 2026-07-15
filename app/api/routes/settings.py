"""Runtime / online settings API."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.api.dependencies import SuperAdminUser, ViewerUser, get_ctx
from app.api.schemas import APIModel, Envelope
from app.context import AppContext
from app.services.history_service import HistoryService
from app.services.runtime_settings import FIELD_META, get_runtime_settings

router = APIRouter(tags=["settings"])


class SettingsUpdateRequest(APIModel):
    values: dict[str, Any]


@router.get("/settings", response_model=Envelope[dict[str, Any]])
async def get_settings(
    _user: ViewerUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[dict[str, Any]]:
    runtime = get_runtime_settings()
    data = runtime.export_for_api(ctx.settings)
    data["schema"] = {
        k: {"apply": v.get("apply"), "group": v.get("group"), "secret": bool(v.get("secret"))}
        for k, v in FIELD_META.items()
    }
    return Envelope(data=data)


@router.put("/settings", response_model=Envelope[dict[str, Any]])
async def put_settings(
    body: SettingsUpdateRequest,
    _admin: SuperAdminUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[dict[str, Any]]:
    runtime = get_runtime_settings()
    result = runtime.update(body.values)
    # Hot-apply a few known settings onto live Settings object when possible.
    for key, value in body.values.items():
        meta = FIELD_META.get(key) or {}
        if meta.get("secret") or meta.get("apply") == "restart":
            continue
        if hasattr(ctx.settings, key):
            try:
                setattr(ctx.settings, key, value)
            except Exception:  # noqa: BLE001
                pass
    if "history_enabled" in body.values or "history_max_per_source" in body.values:
        HistoryService().prune_all()
    return Envelope(data={**result, "values": runtime.export_for_api(ctx.settings)["values"]})

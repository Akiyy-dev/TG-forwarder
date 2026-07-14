"""Bot command handlers."""

from aiogram import Router

from app.bot.handlers.admin import router as admin_router


def setup_routers() -> Router:
    root = Router()
    root.include_router(admin_router)
    return root

from fastapi import APIRouter

from app.api.v1 import admin, attendance, public, teacher_auth, teacher_data

api_router = APIRouter()
api_router.include_router(public.router)
api_router.include_router(admin.router)
api_router.include_router(teacher_auth.router)
api_router.include_router(teacher_data.router)
api_router.include_router(attendance.router)

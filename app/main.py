from fastapi import FastAPI

from app.api.audit import router as audit_router
from app.api.compare import router as compare_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="合规罗盘 API",
        version="0.1.0",
        description="基于 RAG 的轻量级动态风控与审查工作台后端服务",
    )

    app.include_router(audit_router, prefix="/api/v1")
    app.include_router(compare_router, prefix="/api/v1")

    @app.get("/health", tags=["system"])
    async def health_check() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()

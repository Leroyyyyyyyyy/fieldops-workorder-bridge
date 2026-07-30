from fastapi import FastAPI

from app.api.assets import router as assets_router
from app.api.errors import register_error_handlers
from app.api.health import router as health_router
from app.api.work_orders import router as work_orders_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="FieldOps Work Order Bridge",
        description="Field service work order integration API.",
        version="0.1.0",
    )
    register_error_handlers(app)
    app.include_router(health_router)
    app.include_router(assets_router)
    app.include_router(work_orders_router)
    return app


app = create_app()

from fastapi import APIRouter

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    """Liveness probe: proves the process is up. Must not touch the database."""
    return {"status": "ok"}

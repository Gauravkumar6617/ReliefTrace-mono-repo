from fastapi import APIRouter

from app.core.events import broadcaster

router = APIRouter(tags=["meta"])


@router.get("/health")
def health():
    return {"status": "ok", "sse_clients": broadcaster.client_count}

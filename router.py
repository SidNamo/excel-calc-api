from fastapi import APIRouter
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
import logging

from task_queue import enqueue_job, reload_workers_from_s3

router = APIRouter()
logger = logging.getLogger(__name__)


class ExcelJobData(BaseModel):
    input: List[Dict[str, Any]] = []
    output: List[str] = []


class ExcelRequest(BaseModel):
    A: Optional[ExcelJobData] = None
    S: Optional[ExcelJobData] = None


# ---------------------------------------------
# /calc
# ---------------------------------------------
@router.post("/calc")
async def calc(req: ExcelRequest):
    payload: Dict[str, Any] = {}

    if req.A is not None:
        payload["A"] = req.A.dict()
    if req.S is not None:
        payload["S"] = req.S.dict()

    # 요청 정보 로깅
    logger.info(
        f"[API /calc] Request received "
        f"(A={'yes' if req.A else 'no'}, S={'yes' if req.S else 'no'})"
    )

    logger.debug(f"[API /calc] Payload: {payload}")

    try:
        result = await enqueue_job(payload)
        logger.info("[API /calc] Job processed successfully")
        return result
    except Exception as e:
        logger.error(f"[API /calc] ERROR during job processing: {e}")
        raise


# ---------------------------------------------
# /admin/reload
# ---------------------------------------------
class ReloadRequest(BaseModel):
    dummy: Optional[str] = None


@router.post("/admin/reload")
async def admin_reload(_req: ReloadRequest):
    """
    A/S 파일 변경 여부 관계 없이,
    S3 최신 파일 기반으로 워커 세트를 순차 재시작
    """
    logger.warning("[API /admin/reload] Manual reload requested")

    try:
        await reload_workers_from_s3()
        logger.info("[API /admin/reload] Reload complete")
        return {"status": "ok"}

    except Exception as e:
        logger.error(f"[API /admin/reload] ERROR during reload: {e}")
        raise

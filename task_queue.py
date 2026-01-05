import asyncio
import os
import logging
from typing import Tuple, Dict, Any, Optional

from libreoffice import (
    process_excel,
    wait_worker_ready,
    download_latest_pair_from_s3,
    get_latest_s3_key,
    start_workers_for_set,
    stop_workers_for_set,
)

logger = logging.getLogger(__name__)

# 공통 job_queue (모든 세트가 같이 사용)
job_queue: "asyncio.Queue[Tuple[Dict[str, Any], asyncio.Future]]" = asyncio.Queue()

SET_COUNT = int(os.getenv("SET_COUNT", "2"))

# 세트별 락 (해당 세트 reload 시 그 세트 worker만 잠시 멈추기 위함)
set_locks = {set_id: asyncio.Lock() for set_id in range(1, SET_COUNT + 1)}

# reload 중복 실행 방지용 락
reload_lock = asyncio.Lock()

# 현재 사용 중인 S3 key (A/S 공통 버전)
LATEST_KEY_A: Optional[str] = None
LATEST_KEY_S: Optional[str] = None


# ----------------------------------------------------------
# 키 설정
# ----------------------------------------------------------
def set_latest_keys(a_key: str, s_key: str):
    """
    초기 기동 시 또는 reload 후 현재 사용 중인 A/S S3 key를 저장
    """
    global LATEST_KEY_A, LATEST_KEY_S
    LATEST_KEY_A = a_key
    LATEST_KEY_S = s_key
    logger.info(f"[KEY] Updated S3 Keys → A={LATEST_KEY_A}, S={LATEST_KEY_S}")


# ----------------------------------------------------------
# Job Enqueue
# ----------------------------------------------------------
async def enqueue_job(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    외부에서 호출하는 함수.
    payload를 queue에 넣고, 결과 future를 기다렸다가 반환.
    """
    loop = asyncio.get_event_loop()
    fut: asyncio.Future = loop.create_future()

    logger.debug(f"[QUEUE] Enqueue job: {payload}")
    await job_queue.put((payload, fut))

    return await fut


# ----------------------------------------------------------
# Queue Worker
# ----------------------------------------------------------
async def job_worker(worker_id: int):
    logger.info(f"[JOB-WORKER-{worker_id}] Worker started")

    # 최초 LO 준비 체크
    ready = await wait_worker_ready(worker_id, timeout=10.0, interval=0.5)
    if not ready:
        logger.error(f"[JOB-WORKER-{worker_id}] LO not ready at startup → stopping worker")
        return

    logger.info(f"[JOB-WORKER-{worker_id}] LO ready → entering job loop")

    while True:
        payload, future = await job_queue.get()

        try:
            async with set_locks[worker_id]:
                logger.info(f"[JOB-WORKER-{worker_id}] Processing job")
                logger.debug(f"[JOB-WORKER-{worker_id}] Payload: {payload}")

                result = await process_excel(worker_id, payload)

            future.set_result(result)
            logger.info(f"[JOB-WORKER-{worker_id}] Job complete")

        except Exception as e:
            logger.error(f"[JOB-WORKER-{worker_id}] ERROR while processing job: {e}")
            future.set_exception(e)

        finally:
            job_queue.task_done()


def start_queue_workers(count: int):
    """
    SET_COUNT 만큼 worker 코루틴 생성.
    모든 worker는 같은 job_queue를 바라보면서 작업을 가져간다.
    """
    loop = asyncio.get_event_loop()
    for worker_id in range(1, count + 1):
        logger.info(f"[QUEUE] Starting job worker {worker_id}")
        loop.create_task(job_worker(worker_id))


# ----------------------------------------------------------
# Reload Logic
# ----------------------------------------------------------
async def reload_workers_from_s3():
    global LATEST_KEY_A, LATEST_KEY_S

    async with reload_lock:
        logger.info("[RELOAD] Checking for changes in S3…")

        # 최신 S3 key 확인
        try:
            new_key_A = get_latest_s3_key("A")
            new_key_S = get_latest_s3_key("S")
        except Exception as e:
            logger.error(f"[RELOAD] Failed to get latest S3 keys: {e}")
            return

        # 변화 없으면 skip
        if LATEST_KEY_A is not None and LATEST_KEY_S is not None:
            if new_key_A == LATEST_KEY_A and new_key_S == LATEST_KEY_S:
                logger.warning("[RELOAD] No changes detected → reload skipped")
                return

        logger.info(
            f"[RELOAD] Change detected! "
            f"A: {LATEST_KEY_A} → {new_key_A}, "
            f"S: {LATEST_KEY_S} → {new_key_S}"
        )
        logger.info("[RELOAD] Downloading updated A/S files...")

        # 파일 다운로드
        try:
            a_src, s_src = download_latest_pair_from_s3()
        except Exception as e:
            logger.error(f"[RELOAD] Download failed: {e}")
            return

        logger.info(f"[RELOAD] Download complete. A={a_src}, S={s_src}")

        # 세트별로 재시작
        for set_id in range(1, SET_COUNT + 1):
            logger.info(f"[RELOAD] Reloading set {set_id}…")

            async with set_locks[set_id]:
                # 기존 워커 종료
                stop_workers_for_set(set_id)
                logger.debug(f"[RELOAD] Set {set_id} workers stopped")

                # 새 파일로 워커 다시 시작
                start_workers_for_set(set_id, a_src, s_src)
                logger.debug(f"[RELOAD] Set {set_id} new workers started")

            logger.info(f"[RELOAD] Set {set_id} reload complete")

        # 최신 키 갱신
        LATEST_KEY_A = new_key_A
        LATEST_KEY_S = new_key_S
        logger.info(f"[RELOAD] Updated keys → A={LATEST_KEY_A}, S={LATEST_KEY_S}")

        logger.info("[RELOAD] All sets reloaded successfully")

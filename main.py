import asyncio
import os
import logging
from fastapi import FastAPI

from router import router
from task_queue import start_queue_workers, reload_workers_from_s3, set_latest_keys
from libreoffice import (
    download_latest_pair_from_s3,
    start_all_workers_with_files,
    get_latest_s3_key,
)
from clean_tmp import cleanup_temp_files
from task_queue import job_queue
from libreoffice import workers


# ------------------------------------------------------
# Logger 설정
# ------------------------------------------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

logger = logging.getLogger(__name__)


app = FastAPI()
app.include_router(router)

SET_COUNT = int(os.getenv("SET_COUNT", "2"))


# ------------------------------------------------------
# Health Check
# ------------------------------------------------------
@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "queue_size": job_queue.qsize(),
        # "worker_count": len(workers),
        # "workers": list(workers.keys()),
    }


# ------------------------------------------------------
# Startup
# ------------------------------------------------------
@app.on_event("startup")
async def startup_event():
    logger.info("🚀 Server starting...")

    logger.info("Downloading initial A/S from S3...")
    try:
        a_src, s_src = download_latest_pair_from_s3()
        logger.info(f"Initial S3 download complete. A={a_src}, S={s_src}")
    except Exception as e:
        logger.error(f"❌ Failed to download initial A/S from S3: {e}")
        raise

    # 초기 S3 key 설정
    try:
        a_key = get_latest_s3_key("A")
        s_key = get_latest_s3_key("S")
        set_latest_keys(a_key, s_key)
        logger.info(f"Latest S3 Keys initialized. A={a_key}, S={s_key}")
    except Exception as e:
        logger.error(f"❌ Failed to get latest S3 keys: {e}")
        raise

    # LibreOffice Worker 시작
    logger.info(f"Starting LibreOffice Workers... (set_count={SET_COUNT})")
    start_all_workers_with_files(SET_COUNT, a_src, s_src)
    logger.info("LibreOffice Workers started.")

    # Queue Worker 시작
    logger.info("Starting Queue Workers...")
    start_queue_workers(SET_COUNT)
    logger.info("Queue Workers ready.")

    loop = asyncio.get_event_loop()

    # Cleaner Task
    logger.info("Starting Cleaner Task (every 600s)…")
    loop.create_task(cleanup_temp_files(SET_COUNT))

    # Auto Reload Task
    logger.info("Starting S3 Auto-Reload Task (every 60s, first after 60s)…")
    loop.create_task(auto_reload_task())

    logger.info("🔥 Startup complete! Server is ready.")


# ------------------------------------------------------
# Auto Reload Task
# ------------------------------------------------------
async def auto_reload_task():
    """
    1분마다 S3 최신 키 확인 → 변경 있을 경우 reload
    """
    logger.info("Auto reload task will run 60 seconds after startup...")
    await asyncio.sleep(60)

    while True:
        try:
            await reload_workers_from_s3()
        except Exception as e:
            logger.warning(f"[AUTO-RELOAD] Error during S3 check: {e}")

        await asyncio.sleep(60)

import asyncio
import os
import logging
from typing import List

PROFILE_BASE = "/tmp/lo_profile"

logger = logging.getLogger(__name__)


async def cleanup_temp_files(set_count: int, interval_sec: int = 600):
    """
    LibreOffice 프로필 디렉터리 아래의 temp/cache/backup 및
    *.tmp, *.dat, ~$* 파일들을 주기적으로 삭제
    """
    logger.info(f"[CLEANER] Temp cleaner started (interval={interval_sec}s, sets={set_count})")

    while True:
        try:
            deleted_count = 0

            for set_id in range(1, set_count + 1):
                for file_type in ["A", "S"]:
                    base = f"{PROFILE_BASE}/{set_id}/{file_type}"

                    logger.debug(f"[CLEANER] Checking {base}")

                    targets: List[str] = [
                        f"{base}/cache",
                        f"{base}/temp",
                        f"{base}/backup",
                        f"{base}/user/temp",
                        f"{base}/user/backup",
                    ]

                    # 폴더 제거
                    for t in targets:
                        if os.path.exists(t):
                            import shutil
                            shutil.rmtree(t, ignore_errors=True)
                            logger.debug(f"[CLEANER] Removed directory: {t}")

                    # 파일 제거
                    if os.path.exists(base):
                        for fname in os.listdir(base):
                            if (
                                fname.endswith(".tmp")
                                or fname.endswith(".dat")
                                or fname.startswith("~$")
                            ):
                                fpath = os.path.join(base, fname)
                                try:
                                    os.remove(fpath)
                                    deleted_count += 1
                                    logger.debug(f"[CLEANER] Deleted file: {fpath}")
                                except Exception as e:
                                    logger.warning(f"[CLEANER] Failed to delete {fpath}: {e}")

            logger.info(f"[CLEANER] Temp cleanup done (deleted {deleted_count} files)")

        except Exception as e:
            logger.error(f"[CLEANER] ERROR: {e}")

        await asyncio.sleep(interval_sec)

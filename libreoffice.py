import subprocess
import os
import asyncio
import sys
import logging
from typing import Dict, Any, Tuple

# Logger
logger = logging.getLogger(__name__)

# UNO 파이썬 바인딩 경로 + 환경 설정
sys.path.append("/usr/lib/libreoffice/program")
os.environ["URE_BOOTSTRAP"] = "vnd.sun.star.pathname:/usr/lib/libreoffice/program/fundamentalrc"

import uno  # type: ignore
from com.sun.star.connection import NoConnectException  # type: ignore

import boto3

# =========================================
# A / S LibreOffice Worker 기본 포트 설정
# A 세트: 2000 + set_id
# S 세트: 2100 + set_id
# =========================================
BASE_PORT_A = 2000
BASE_PORT_S = 2100

# S3 설정
S3_BUCKET = os.getenv("AWS_S3_BUCKET_NAME", "")
AWS_S3_ACCESS_KEY = os.getenv("AWS_S3_ACCESS_KEY", "")
AWS_S3_SECRET_KEY = os.getenv("AWS_S3_SECRET_KEY", "")
S3_REGION = os.getenv("AWS_REGION", "ap-northeast-2")

# 기본 Prefix (docker-compose에서 override 가능)
#   예: Contents/Excel/A/, Contents/Excel/S/
S3_PREFIX_A = os.getenv("S3_PREFIX_A", "Contents/Excel/A/")
S3_PREFIX_S = os.getenv("S3_PREFIX_S", "Contents/Excel/S/")

# S3에서 내려받을 로컬 디렉터리
S3_LOCAL_DIR = "/tmp/s3_excel"

# 실행된 LibreOffice 워커 정보를 저장하는 딕셔너리
# key: "A-1", "S-1" ...
# value: { process, port, profile, filepath }
workers: Dict[str, Dict[str, Any]] = {}

_s3_client = None


# =========================================
# 공통 유틸
# =========================================
def ensure_dir(p: str):
    if not os.path.exists(p):
        os.makedirs(p, exist_ok=True)


def get_s3_client():
    global _s3_client
    if _s3_client is None:
        logger.debug("[S3] Creating new S3 client")
        _s3_client = boto3.client(
            "s3",
            aws_access_key_id=AWS_S3_ACCESS_KEY,
            aws_secret_access_key=AWS_S3_SECRET_KEY,
            region_name=S3_REGION,
        )
    return _s3_client


def _find_latest_s3_key(prefix: str) -> str:
    """
    prefix 아래에서 .xlsx / .xlsm 중
    파일명 기준 내림차순 후 최신 파일 선택
    """
    if not S3_BUCKET:
        raise Exception("AWS_S3_BUCKET_NAME 이 설정되지 않았습니다.")

    client = get_s3_client()

    continuation_token = None
    keys = []

    while True:
        if continuation_token:
            resp = client.list_objects_v2(
                Bucket=S3_BUCKET,
                Prefix=prefix,
                ContinuationToken=continuation_token,
            )
        else:
            resp = client.list_objects_v2(Bucket=S3_BUCKET, Prefix=prefix)

        contents = resp.get("Contents", [])
        for obj in contents:
            key = obj["Key"]
            fname = os.path.basename(key)
            if (
                (fname.endswith(".xlsx") or fname.endswith(".xlsm"))
                and not fname.startswith("~$")
            ):
                keys.append(key)

        if resp.get("IsTruncated"):
            continuation_token = resp.get("NextContinuationToken")
        else:
            break

    if not keys:
        raise Exception(f"[S3] prefix={prefix} 에서 사용할 엑셀 파일을 찾을 수 없습니다.")

    keys.sort(reverse=True)
    latest_key = keys[0]
    logger.info(f"[S3] Latest key for prefix {prefix}: {latest_key}")
    return latest_key


def _download_s3_file(key: str, file_type: str) -> str:
    folder = os.path.join(S3_LOCAL_DIR, file_type)
    ensure_dir(folder)

    filename = os.path.basename(key)
    local_path = os.path.join(folder, filename)

    client = get_s3_client()
    logger.info(f"[S3] Downloading s3://{S3_BUCKET}/{key} → {local_path}")
    client.download_file(S3_BUCKET, key, local_path)

    return local_path


def download_latest_from_s3(file_type: str) -> str:
    prefix = S3_PREFIX_A if file_type == "A" else S3_PREFIX_S
    latest_key = _find_latest_s3_key(prefix)
    return _download_s3_file(latest_key, file_type)


def download_latest_pair_from_s3() -> Tuple[str, str]:
    a_path = download_latest_from_s3("A")
    s_path = download_latest_from_s3("S")
    return a_path, s_path


def get_latest_s3_key(file_type: str) -> str:
    prefix = S3_PREFIX_A if file_type == "A" else S3_PREFIX_S
    return _find_latest_s3_key(prefix)


# =========================================
# LO Worker 시작 / 종료
# =========================================
def start_lo_worker(set_id: int, file_type: str, src_file: str):
    profile = f"/tmp/lo_profile/{set_id}/{file_type}"
    ensure_dir(profile)

    port = BASE_PORT_A + set_id if file_type == "A" else BASE_PORT_S + set_id

    if not os.path.exists(src_file):
        raise Exception(f"[ERROR] {file_type} 타입 src_file 이 존재하지 않습니다: {src_file}")

    logger.info(f"[LO-{file_type}-{set_id}] Source file (from S3): {src_file}")

    base_name = os.path.basename(src_file)
    dst_path = os.path.join(profile, base_name)

    try:
        import shutil
        shutil.copy2(src_file, dst_path)
        logger.debug(f"[LO-{file_type}-{set_id}] Copied → {dst_path}")
    except Exception as e:
        raise Exception(f"[ERROR] 파일 복사 실패: {e}")

    file_url = "file://" + dst_path.replace("\\", "/")

    cmd = [
        "soffice",
        "--headless",
        "--invisible",
        "--nocrashreport",
        "--nodefault",
        "--nologo",
        "--nolockcheck",
        "--nofirststartwizard",
        f"-env:UserInstallation=file://{profile}",
        f"--accept=socket,host=localhost,port={port};urp;",
        file_url,
    ]

    logger.info(f"[LO-{file_type}-{set_id}] starting on port {port}")

    proc = subprocess.Popen(cmd)

    workers[f"{file_type}-{set_id}"] = {
        "process": proc,
        "port": port,
        "profile": profile,
        "filepath": dst_path,
    }


def start_workers_for_set(set_id: int, a_src: str, s_src: str):
    start_lo_worker(set_id, "A", a_src)
    start_lo_worker(set_id, "S", s_src)


def start_all_workers_with_files(count: int, a_src: str, s_src: str):
    ensure_dir("/tmp/lo_profile")
    for set_id in range(1, count + 1):
        start_workers_for_set(set_id, a_src, s_src)


def stop_workers_for_set(set_id: int):
    for file_type in ["A", "S"]:
        key = f"{file_type}-{set_id}"
        wk = workers.get(key)

        if not wk:
            continue

        proc = wk.get("process")
        try:
            if proc and proc.poll() is None:
                logger.info(f"[LO-{file_type}-{set_id}] terminating...")
                proc.terminate()
        except Exception as e:
            logger.error(f"[LO-{file_type}-{set_id}] Error terminating: {e}")

        workers.pop(key, None)


def stop_all_workers():
    logger.info("[LO] Stopping all workers...")
    for key, wk in list(workers.items()):
        proc = wk.get("process")
        try:
            if proc and proc.poll() is None:
                proc.terminate()
        except Exception as e:
            logger.error(f"[LO] Error terminating worker {key}: {e}")

    workers.clear()
    logger.info("[LO] All workers stopped")


# =========================================
# UNO 연결 체크
# =========================================
def _try_uno_connect(file_type: str, worker_id: int) -> bool:
    key = f"{file_type}-{worker_id}"
    wk = workers.get(key)

    if not wk:
        return False

    port = wk["port"]
    uno_url = f"uno:socket,host=127.0.0.1,port={port};urp;StarOffice.ComponentContext"

    try:
        local_ctx = uno.getComponentContext()
        resolver = local_ctx.ServiceManager.createInstanceWithContext(
            "com.sun.star.bridge.UnoUrlResolver",
            local_ctx,
        )
        resolver.resolve(uno_url)
        return True
    except NoConnectException:
        return False
    except Exception:
        return False


async def wait_worker_ready(worker_id: int, timeout: float = 10.0, interval: float = 0.5) -> bool:
    elapsed = 0.0
    while elapsed < timeout:
        a_ready = _try_uno_connect("A", worker_id)
        s_ready = _try_uno_connect("S", worker_id)

        if a_ready and s_ready:
            logger.info(f"[WORKER-{worker_id}] LO ready")
            return True

        await asyncio.sleep(interval)
        elapsed += interval

    logger.error(f"[WORKER-{worker_id}] LO not ready within {timeout} seconds")
    return False


# =========================================
# Excel 처리 (세트 전체)
# =========================================
async def process_excel(worker_id: int, payload: dict):
    A_payload = payload.get("A")
    S_payload = payload.get("S")

    result: Dict[str, Any] = {}

    if A_payload:
        result["A"] = await process_one(worker_id, "A", A_payload)

    if S_payload:
        result["S"] = await process_one(worker_id, "S", S_payload)

    return result


# =========================================
# 하나의 파일 처리 (입력 → 계산 → 출력)
# =========================================
async def process_one(worker_id: int, file_type: str, data: dict):
    key = f"{file_type}-{worker_id}"
    wk = workers.get(key)

    if not wk:

        raise Exception(f"Worker 정보 없음: {key}")

    port = wk["port"]
    filepath = wk["filepath"]

    uno_url = f"uno:socket,host=127.0.0.1,port={port};urp;StarOffice.ComponentContext"
    logger.info(f"[UNO] worker_id={worker_id}, type={file_type}, url={uno_url}")

    local_ctx = uno.getComponentContext()
    resolver = local_ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.bridge.UnoUrlResolver",
        local_ctx,
    )

    ctx = None
    for _ in range(20):
        try:
            ctx = resolver.resolve(uno_url)
            break
        except NoConnectException:
            await asyncio.sleep(0.5)

    if ctx is None:
        raise Exception(
            f"UNO 연결 실패(재시도 초과): worker={worker_id}, port={port}"
        )

    smgr = ctx.ServiceManager
    desktop = smgr.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)

    doc = desktop.getCurrentComponent()
    if doc is None or not hasattr(doc, "getSheets"):
        file_url = "file://" + filepath.replace("\\", "/")
        logger.debug(f"[UNO] loading document: {file_url}")
        doc = desktop.loadComponentFromURL(file_url, "_blank", 0, ())

    if doc is None:
        raise Exception(f"[Worker {worker_id}] UNO 문서 접근 실패")

    # input 적용
    for item in data.get("input", []):
        full_cell = item["cell"]
        value = item["value"]

        sheet_name, cell_addr = full_cell.split("!")
        sheet = doc.getSheets().getByName(sheet_name)
        cell = sheet.getCellRangeByName(cell_addr)

        if isinstance(value, (int, float)):
            cell.setValue(float(value))
        else:
            cell.setString(str(value))

    # Hard Recalc
    doc.calculateAll()
    await asyncio.sleep(0.1)

    result: Dict[str, Any] = {}

    for out_range in data.get("output", []):
        sheet_name, cell_range = out_range.split("!")
        stable_flat = await process_output_range(doc, sheet_name, cell_range)
        result[out_range] = stable_flat

    return {
        "filepath": filepath,
        "result": result,
    }


async def process_output_range(doc, sheet_name: str, cell_range: str):
    sheet = doc.getSheets().getByName(sheet_name)
    rng = sheet.getCellRangeByName(cell_range)

    old_flat = None

    for _ in range(200):
        arr = rng.getDataArray()
        flat = [v for row in arr for v in row]

        if flat == old_flat:
            return flat

        old_flat = flat
        await asyncio.sleep(0.1)

    return old_flat

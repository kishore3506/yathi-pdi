import os
import shutil
import tempfile
import zipfile
from datetime import datetime

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

try:
    from ..services.portable_backup import create_backup, import_backup
    from ..services.excel_data_backup import FILENAME as EXCEL_DATA_FILENAME
except ImportError:
    from services.portable_backup import create_backup, import_backup
    from services.excel_data_backup import FILENAME as EXCEL_DATA_FILENAME


router = APIRouter(prefix="/api/admin", tags=["Administration"])
MAX_BACKUP_IMPORT_BYTES = int(os.getenv("MAX_BACKUP_IMPORT_BYTES", str(1024 * 1024 * 1024)))


@router.get("/backup")
async def download_backup():
    temp_dir = tempfile.mkdtemp(prefix="pdi-backup-download-")
    destination = os.path.join(
        temp_dir,
        f"yathi-pdi-backup-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.zip",
    )
    try:
        await run_in_threadpool(create_backup, destination)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    return FileResponse(
        destination,
        filename=os.path.basename(destination),
        media_type="application/zip",
        background=BackgroundTask(shutil.rmtree, temp_dir, ignore_errors=True),
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/backup/excel")
async def download_excel_data(request: Request):
    temp_dir = tempfile.mkdtemp(prefix="pdi-excel-download-")
    destination = os.path.join(temp_dir, EXCEL_DATA_FILENAME)
    try:
        await run_in_threadpool(request.app.state.excel_data.copy_latest, destination)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    return FileResponse(
        destination,
        filename=EXCEL_DATA_FILENAME,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        background=BackgroundTask(shutil.rmtree, temp_dir, ignore_errors=True),
        headers={"Cache-Control": "private, no-store"},
    )


@router.post("/import")
async def import_initial_backup(request: Request, file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Choose a PDI backup ZIP file.")
    temp_path = None
    total_bytes = 0
    try:
        with tempfile.NamedTemporaryFile(prefix="pdi-backup-upload-", suffix=".zip", delete=False) as temp:
            temp_path = temp.name
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > MAX_BACKUP_IMPORT_BYTES:
                    raise HTTPException(status_code=413, detail="Backup archive exceeds the import limit.")
                temp.write(chunk)
        def restore():
            with request.app.state.excel_data.lock:
                return import_backup(temp_path)

        try:
            result = await run_in_threadpool(restore)
        except (ValueError, FileNotFoundError, zipfile.BadZipFile) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return result
    finally:
        await file.close()
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)

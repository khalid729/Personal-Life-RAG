from fastapi import APIRouter, Request

router = APIRouter(prefix="/backup", tags=["backup"])


@router.post("/create")
async def create_backup(request: Request):
    backup_service = request.app.state.backup_service
    result = await backup_service.create_backup()
    # Cleanup old backups after creating new one
    removed = await backup_service.cleanup_old_backups()
    result["old_backups_removed"] = removed
    return result


@router.get("/list")
async def list_backups(request: Request):
    backup_service = request.app.state.backup_service
    backups = await backup_service.list_backups()
    return {"backups": backups}


@router.post("/restore/{timestamp}")
async def restore_backup(timestamp: str, request: Request):
    backup_service = request.app.state.backup_service
    result = await backup_service.restore_backup(timestamp)
    return result

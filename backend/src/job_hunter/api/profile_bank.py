"""HTTP schemas and thin routes for the profile bank."""
from typing import Any, Literal
from uuid import UUID

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import ValidationError
from fastapi.responses import JSONResponse
from pathlib import Path
from job_hunter.adapters import storage
from sqlalchemy import select
from job_hunter.domain.models import Upload
from job_hunter.profile_bank.export import export_profile
from job_hunter.profile_bank.importing import services as imports
from job_hunter.profile_bank.importing.docx import DOCX_CONTENT_TYPE
from job_hunter.profile_bank.importing.schema import within_depth
from job_hunter.config import settings
from pydantic import Field
from sqlalchemy.orm import Session

from job_hunter.profile_bank import services
from job_hunter.profile_bank.schema import BankModel, MAX_POINT_LENGTH
from job_hunter.profile_bank.settings import ResumeDefaults


class ItemCreate(BankModel):
    kind: str
    data: dict[str, Any]
    tags: list[str] = Field(default_factory=list, max_length=50)
    parent_id: UUID | None = None


class ItemWrite(BankModel):
    expected_revision: int = Field(ge=0)
    data: dict[str, Any] | None = None
    tags: list[str] | None = Field(default=None, max_length=50)
    parent_id: UUID | None = None


class ItemOrder(BankModel):
    kind: str
    item_ids: list[UUID] = Field(max_length=50)
    expected_bank_revision: int = Field(ge=0)


class PointWrite(BankModel):
    expected_revision: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=MAX_POINT_LENGTH)
    tags: list[str] = Field(default_factory=list, max_length=50)
    skills: list[str] = Field(default_factory=list, max_length=50)


class PointVersionWrite(PointWrite):
    replace_alternative_id: str | None = None


class PointUpdate(BankModel):
    expected_revision: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=MAX_POINT_LENGTH)
    alternative_id: str | None = None
    make_main: bool = False
    keep_previous: bool = True
    replace_alternative_id: str | None = None


class SettingsWrite(BankModel):
    expected_revision: int = Field(ge=0)
    resume_defaults: ResumeDefaults


class DeleteProfile(BankModel):
    confirmation: Literal['DELETE']
    delete_settings: bool = False


# 1 MiB of input plus JSON envelope and escaping overhead.
MAX_IMPORT_BODY = 2 * 1024 * 1024


class ImportCreate(BankModel):
    upload_id: UUID | None = None
    document_id: UUID | None = None
    json_resume: dict[str, Any] | None = None
    text: str | None = None


class ImportDecision(BankModel):
    candidate_id: str
    action: Literal['add', 'merge', 'skip']
    target_item_id: UUID | None = None
    expected_revision: int | None = Field(default=None, ge=0)
    data: dict[str, Any] | None = None
    accepted_fields: list[str] = Field(default_factory=list)


class ImportApply(BankModel):
    expected_profile_epoch: int = Field(ge=0)
    decisions: list[ImportDecision] = Field(max_length=401)


def build_router(db_dependency):
    router = APIRouter(prefix='/v1')

    # The body is read manually (size and depth checked first), so document its schema explicitly.
    @router.post('/profile/imports', status_code=201, openapi_extra={'requestBody': {
        'required': True, 'content': {'application/json': {'schema': ImportCreate.model_json_schema()}}}})
    async def start_import(request: Request, db: Session = Depends(db_dependency)):
        # Read the body ourselves so oversized or deeply nested input is rejected before parsing.
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > MAX_IMPORT_BODY:
                raise HTTPException(413, detail={'code': 'INPUT_TOO_LARGE', 'message': 'Import input must be at most 1 MiB'})
        try:
            parsed = json.loads(raw or b'{}')
            if not within_depth(parsed):
                raise RecursionError
            body = ImportCreate.model_validate(parsed)
        except RecursionError:
            raise HTTPException(422, detail={'code': 'INVALID_IMPORT_SOURCE', 'message': 'Import input is nested too deeply'})
        except (ValueError, ValidationError):
            raise HTTPException(422, detail={'code': 'INVALID_IMPORT_SOURCE', 'message': 'Send exactly one valid import source'})
        return imports.start_import(db, body.model_dump(exclude_none=True), settings)

    @router.get('/profile/imports')
    def list_imports(db: Session = Depends(db_dependency)):
        return imports.list_imports(db)

    @router.get('/profile/imports/{import_id}')
    def get_import(import_id: UUID, db: Session = Depends(db_dependency)):
        return imports.get_import(db, import_id)

    @router.post('/profile/imports/{import_id}/apply')
    def apply_import(import_id: UUID, body: ImportApply, db: Session = Depends(db_dependency)):
        return imports.apply_import(db, import_id, [decision.model_dump(exclude_none=True) for decision in body.decisions], body.expected_profile_epoch)

    @router.post('/profile/imports/{import_id}/discard')
    def discard_import(import_id: UUID, db: Session = Depends(db_dependency)):
        return imports.discard_import(db, import_id)

    @router.post('/profile/imports/{import_id}/retry')
    def retry_import(import_id: UUID, db: Session = Depends(db_dependency)):
        return imports.retry_import(db, import_id, settings)

    @router.get('/profile/export.json')
    def export(db: Session = Depends(db_dependency)):
        return JSONResponse(export_profile(services.get_bank(db)), headers={'Content-Disposition': 'attachment; filename="profile.json"'})

    @router.get('/uploads')
    def uploads(db: Session = Depends(db_dependency)):
        rows = db.scalars(select(Upload).where(Upload.user_id == db.info['current_user'].id).order_by(Upload.created_at.desc()).limit(100)).all()
        return {'items': [{'upload_id': str(row.id), 'filename': row.filename, 'status': row.status,
                          'page_count': row.page_count, 'created_at': row.created_at} for row in rows], 'next_cursor': None}

    @router.get('/uploads/{upload_id}/download')
    def download_upload(upload_id: UUID, db: Session = Depends(db_dependency)):
        row = db.scalar(select(Upload).where(Upload.id == upload_id, Upload.user_id == db.info['current_user'].id))
        if row is None:
            raise HTTPException(404, detail={'code': 'NOT_FOUND', 'message': 'Resource not found'})
        if row.sha256 is None:
            raise HTTPException(409, detail={'code': 'UPLOAD_NOT_CAPTURED', 'message': 'Finish uploading this resume first'})
        docx = row.content_type == DOCX_CONTENT_TYPE
        if row.file_path.startswith('s3://'):
            return JSONResponse({'url': storage.download_url(row.file_path, 'resume.docx' if docx else 'resume.pdf', row.content_type)}, headers={'Cache-Control': 'no-store'})
        try:
            data = storage.read(row.file_path)
        except FileNotFoundError:
            raise HTTPException(404, detail={'code': 'NOT_FOUND', 'message': 'Resource not found'})
        return Response(data, media_type=DOCX_CONTENT_TYPE if docx else 'application/pdf',
                        headers={'Content-Disposition': f'attachment; filename="resume.{"docx" if docx else "pdf"}"'})

    @router.get('/profile/bank')
    def bank(db: Session = Depends(db_dependency)):
        return services.get_bank(db)

    # Static route must precede /items/{item_id}.
    @router.put('/profile/items/order')
    def order(body: ItemOrder, db: Session = Depends(db_dependency)):
        return services.reorder_items(db, body.kind, body.item_ids, body.expected_bank_revision)

    @router.post('/profile/items', status_code=201)
    def create(body: ItemCreate, db: Session = Depends(db_dependency)):
        return services.create_item(db, body.kind, body.data, body.tags, body.parent_id)

    @router.get('/profile/items/{item_id}')
    def read(item_id: UUID, db: Session = Depends(db_dependency)):
        return services.item_out(services._item(db, item_id))

    @router.patch('/profile/items/{item_id}')
    def update(item_id: UUID, body: ItemWrite, db: Session = Depends(db_dependency)):
        changes = body.model_dump(exclude_unset=True, exclude={'expected_revision'})
        if any(changes.get(key) is None for key in ('data', 'tags') if key in changes):
            raise HTTPException(422, detail={'code': 'INVALID_PROFILE_ITEM', 'message': 'Data and tags cannot be null'})
        return services.update_item(db, item_id, body.expected_revision, changes)

    @router.delete('/profile/items/{item_id}')
    def archive(item_id: UUID, expected_revision: int | None = Query(default=None, ge=0),
                db: Session = Depends(db_dependency)):
        return services.archive_item(db, item_id, expected_revision)

    @router.post('/profile/items/{item_id}/revert')
    def revert(item_id: UUID, body: ItemWrite, db: Session = Depends(db_dependency)):
        if body.data is None:
            raise HTTPException(422, detail={'code': 'INVALID_REVERT', 'message': 'Supply the previous item data to restore'})
        return services.revert_item(db, item_id, body.expected_revision,
                                    body.model_dump(exclude_unset=True, exclude={'expected_revision'}))

    @router.post('/profile/items/{item_id}/bullets')
    def add_point(item_id: UUID, body: PointWrite, db: Session = Depends(db_dependency)):
        return services.mutate_bullet(db, item_id, body.expected_revision, 'add',
                                      body.model_dump(exclude={'expected_revision'}))

    @router.put('/profile/items/{item_id}/bullets/{bullet_id}')
    def update_point(item_id: UUID, bullet_id: str, body: PointUpdate,
                     db: Session = Depends(db_dependency)):
        return services.mutate_bullet(db, item_id, body.expected_revision, 'update',
                                      body.model_dump(exclude={'expected_revision'}), bullet_id)

    @router.post('/profile/items/{item_id}/bullets/{bullet_id}/alternatives')
    def alternative(item_id: UUID, bullet_id: str, body: PointVersionWrite,
                    db: Session = Depends(db_dependency)):
        return services.mutate_bullet(db, item_id, body.expected_revision, 'alternative',
                                      body.model_dump(exclude={'expected_revision'}), bullet_id)

    @router.get('/settings')
    def read_settings(db: Session = Depends(db_dependency)):
        return services.get_settings(db)

    @router.put('/settings')
    def write_settings(body: SettingsWrite, db: Session = Depends(db_dependency)):
        return services.update_settings(db, body.resume_defaults.model_dump(mode='json', exclude_unset=True),
                                        body.expected_revision)

    @router.delete('/profile/data')
    def delete_data(body: DeleteProfile, db: Session = Depends(db_dependency)):
        result, paths = services.delete_profile_data(db, body.delete_settings)
        # Cleanup runs after the DB commit; rollback must not destroy uploaded bytes.
        db.info.setdefault('profile_upload_cleanup', []).extend(paths)
        return result

    return router

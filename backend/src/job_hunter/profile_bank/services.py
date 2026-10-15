"""Owned profile-bank operations within the caller's database transaction."""
from copy import deepcopy
import hashlib
import json
import re
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from job_hunter.domain.models import Profile, ProfileItem, ProfileImport, ProfileVersion, Upload, User, UserSettings, now_utc
from .schema import ITEM_KINDS, MAX_ITEMS_PER_KIND, MAX_VERSIONS, validate_item_data
from .snapshots import assemble_profile_snapshot


class BankError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message
        super().__init__(message)


def _evidence_matches(value, provenance):
    evidence = provenance.get('evidence') or {}
    query = ' '.join(re.findall(r'\w+', str(value).casefold()))
    source = ' '.join(re.findall(r'\w+', evidence.get('text','').casefold()))
    return bool(query) and f' {query} ' in f' {source} '


def _user_id(db):
    return db.info['current_user'].id


def _conflict():
    raise BankError(409, 'REVISION_CONFLICT', 'Profile changed; reload before saving')


def _profile(db, create=False, lock=False):
    if lock:
        db.execute(select(User.id).where(User.id == _user_id(db)).with_for_update())
    query = select(Profile).where(Profile.user_id == _user_id(db))
    if lock:
        query = query.with_for_update()
    profile = db.scalar(query)
    if profile is None and create:
        profile = Profile(user_id=_user_id(db), draft={}, revision=0, bank_revision=0, profile_epoch=0)
        db.add(profile)
        db.flush()
    return profile


def _bump(profile):
    profile.bank_revision += 1
    profile.updated_at = now_utc()


def item_out(item):
    return {'id': str(item.id), 'kind': item.kind, 'position': item.position, 'data': item.data,
            'tags': item.tags, 'origin': item.origin,
            'import_id': str(item.import_id) if item.import_id else None,
            'parent_id': str(item.parent_id) if item.parent_id else None,
            'revision': item.revision, 'archived_at': item.archived_at,
            'created_at': item.created_at, 'updated_at': item.updated_at}


def _items(db):
    return db.scalars(select(ProfileItem).where(ProfileItem.user_id == _user_id(db),
                     ProfileItem.archived_at.is_(None)).order_by(ProfileItem.kind, ProfileItem.position, ProfileItem.id)).all()


def get_bank(db):
    profile = _profile(db)
    items = [item_out(item) for item in _items(db)]
    return {'basics': profile.draft if profile else {}, 'items': items,
            'grouped': {kind: [item for item in items if item['kind'] == kind] for kind in ITEM_KINDS},
            'bank_revision': profile.bank_revision if profile else 0,
            'confirmed_revision': profile.confirmed_revision if profile else None,
            'profile_epoch': profile.profile_epoch if profile else 0,
            'basics_provenance': profile.basics_provenance if profile else {}}


def build_profile_snapshot(db):
    profile = _profile(db)
    return assemble_profile_snapshot(profile.draft if profile else {},
                                     [item_out(item) for item in _items(db)],
                                     profile.bank_revision if profile else 0)


def get_confirmed_snapshot(db):
    profile = _profile(db)
    if profile is None or profile.confirmed_revision is None:
        return None
    version = db.scalar(select(ProfileVersion).where(ProfileVersion.user_id == _user_id(db),
                         ProfileVersion.revision == profile.confirmed_revision))
    return (str(version.id), version.revision, deepcopy(version.data)) if version else None


def _item(db, item_id, lock=False, active=True):
    query = select(ProfileItem).where(ProfileItem.id == item_id, ProfileItem.user_id == _user_id(db))
    if active:
        query = query.where(ProfileItem.archived_at.is_(None))
    if lock:
        query = query.with_for_update()
    item = db.scalar(query)
    if item is None:
        raise BankError(404, 'NOT_FOUND', 'Resource not found')
    return item


def get_bullet(db, item_id, bullet_id):
    item = _item(db, item_id)
    bullet = next((point for point in item.data.get('bullets', []) if point['id'] == bullet_id), None)
    if bullet is None:
        raise BankError(404, 'NOT_FOUND', 'Resource not found')
    return deepcopy(bullet)


def _validated(kind, data):
    try:
        return validate_item_data(kind, data)
    except (ValidationError, ValueError) as exc:
        raise BankError(422, 'INVALID_PROFILE_ITEM', str(exc)) from exc


def _parent(db, kind, parent_id):
    if parent_id is not None:
        parent = _item(db, parent_id)
        if kind != 'project' or parent.kind != 'experience':
            raise BankError(422, 'INVALID_PARENT', 'Only a project may belong to an experience')


def _skill_unique(db, kind, data, exclude=None):
    if kind == 'skill':
        name = data['name'].strip().casefold()
        if not name:
            raise BankError(422, 'INVALID_PROFILE_ITEM', 'Skill name cannot be blank')
        for item in _items(db):
            if item.kind == 'skill' and item.id != exclude and item.data['name'].strip().casefold() == name:
                raise BankError(422, 'DUPLICATE_SKILL', 'This skill already exists in the profile')


def create_item(db, kind, data, tags, parent_id=None):
    profile = _profile(db, create=True, lock=True)
    data = _validated(kind, data)
    _parent(db, kind, parent_id)
    items = [item for item in _items(db) if item.kind == kind]
    if len(items) >= MAX_ITEMS_PER_KIND:
        raise BankError(422, 'PROFILE_ITEM_LIMIT', 'The profile allows 50 active items per kind')
    _skill_unique(db, kind, data)
    item = ProfileItem(user_id=_user_id(db), kind=kind, data=data, tags=tags,
                       parent_id=parent_id, position=max((item.position for item in items), default=-1) + 1)
    db.add(item)
    _bump(profile)
    db.flush()
    return item_out(item)


def update_item(db, item_id, expected_revision, changes):
    profile = _profile(db, create=True, lock=True)
    item = _item(db, item_id, lock=True)
    if item.revision != expected_revision:
        _conflict()
    if any(changes.get(key) is None for key in ('data', 'tags') if key in changes):
        raise BankError(422, 'INVALID_PROFILE_ITEM', 'Data and tags cannot be null')
    if 'data' in changes:
        data = _validated(item.kind, changes['data'])
        _skill_unique(db, item.kind, data, item.id)
        # A user edit retains source excerpts but cannot claim new text is extracted evidence.
        old_points = {point['id']: point for point in item.data.get('bullets', [])}
        for point in data.get('bullets', []):
            old = old_points.get(point['id'])
            if old and old.get('provenance'):
                point['provenance'] = deepcopy(old['provenance'])
                if point['text'] != old['text'] and not _evidence_matches(point['text'], old['provenance']):
                    point['provenance']['origin'] = 'user'
            old_versions = {version['id']: version for version in (old or {}).get('alternatives', [])}
            for version in point.get('alternatives', []):
                old_version = old_versions.get(version['id'])
                if old_version and old_version.get('provenance'):
                    version['provenance'] = deepcopy(old_version['provenance'])
                    if version['text'] != old_version['text'] and not _evidence_matches(version['text'], old_version['provenance']):
                        version['provenance']['origin'] = 'user'
        old_provenance = item.data.get('provenance', {})
        for field, provenance in old_provenance.items():
            data.setdefault('provenance', {})[field] = deepcopy(provenance)
            if item.data.get(field) != data.get(field) and not _evidence_matches(data.get(field), provenance):
                data['provenance'][field]['origin'] = 'user'
        item.data = data
    if 'tags' in changes:
        item.tags = changes['tags']
    if 'parent_id' in changes:
        _parent(db, item.kind, changes['parent_id'])
        item.parent_id = changes['parent_id']
    item.revision += 1
    item.updated_at = now_utc()
    _bump(profile)
    db.flush()
    return item_out(item)


def archive_item(db, item_id, expected_revision=None):
    profile = _profile(db, create=True, lock=True)
    item = _item(db, item_id, lock=True)
    if expected_revision is not None and item.revision != expected_revision:
        _conflict()
    item.archived_at = now_utc()
    item.revision += 1
    _bump(profile)
    db.flush()
    return item_out(item)


def revert_item(db, item_id, expected_revision, changes):
    """Restore held prior data, including an archived item, without a stale write."""
    profile = _profile(db, create=True, lock=True)
    item = _item(db, item_id, lock=True, active=False)
    if item.revision != expected_revision:
        _conflict()
    if changes.get('data') is None:
        raise BankError(422, 'INVALID_REVERT', 'Supply the previous item data to restore')
    data = _validated(item.kind, changes['data'])
    _skill_unique(db, item.kind, data, item.id)
    parent_id = changes.get('parent_id', item.parent_id)
    if parent_id != item.parent_id:
        _parent(db, item.kind, parent_id)
    if item.archived_at is not None:
        active_items = [row for row in _items(db) if row.kind == item.kind]
        if len(active_items) >= MAX_ITEMS_PER_KIND:
            raise BankError(422, 'PROFILE_ITEM_LIMIT', 'The profile allows 50 active items per kind')
    if 'tags' in changes and changes['tags'] is None:
        raise BankError(422, 'INVALID_PROFILE_ITEM', 'Tags cannot be null')
    # A revision-checked undo restores the supplied original provenance as well.
    item.data = data
    item.tags = changes.get('tags', item.tags)
    item.parent_id = parent_id
    item.archived_at = None
    item.revision += 1
    item.updated_at = now_utc()
    _bump(profile)
    db.flush()
    return item_out(item)


def reorder_items(db, kind, item_ids, expected_bank_revision):
    profile = _profile(db, create=True, lock=True)
    if profile.bank_revision != expected_bank_revision:
        _conflict()
    if kind not in ITEM_KINDS or len(item_ids) != len(set(item_ids)):
        raise BankError(422, 'INVALID_ORDER', 'Supply one unique ID for every active item of the kind')
    ordered = [_item(db, item_id, lock=True) for item_id in item_ids]
    current = [item for item in _items(db) if item.kind == kind]
    if any(item.kind != kind for item in ordered) or {item.id for item in current} != set(item_ids):
        raise BankError(422, 'INVALID_ORDER', 'Supply every active item of the selected kind')
    for position, item in enumerate(ordered):
        item.position = position
        item.revision += 1
        item.updated_at = now_utc()
    _bump(profile)
    db.flush()
    return get_bank(db)


def mutate_bullet(db, item_id, expected_revision, mode, payload, bullet_id=None):
    profile = _profile(db, create=True, lock=True)
    payload = deepcopy(payload)
    item = _item(db, item_id, lock=True)
    if item.revision != expected_revision:
        _conflict()
    data = deepcopy(item.data)
    if mode == 'add':
        data.setdefault('bullets', []).append({'id': 'b_' + uuid4().hex, **payload})
    else:
        point = next((point for point in data.get('bullets', []) if point['id'] == bullet_id), None)
        if point is None:
            raise BankError(404, 'NOT_FOUND', 'Resource not found')
        make_main = payload.pop('make_main', False)
        if make_main:
            alternative_id = payload.get('alternative_id')
            selected = next((version for version in point.get('alternatives', [])
                             if version['id'] == alternative_id), None)
            if selected is None:
                raise BankError(422, 'INVALID_VERSION', 'Choose an existing alternative to make main')
            # Swap whole wording metadata; IDs remain the stable source links.
            old_main = {key: deepcopy(value) for key, value in point.items()
                        if key not in ('id', 'alternatives')}
            new_main = {key: deepcopy(value) for key, value in selected.items() if key != 'id'}
            selected_id, point_id = selected['id'], point['id']
            alternatives = point['alternatives']
            selected.clear()
            selected.update({'id': selected_id, **old_main})
            point.clear()
            point.update({'id': point_id, **new_main, 'alternatives': alternatives})
            item.data = _validated(item.kind, data)
            item.revision += 1
            item.updated_at = now_utc()
            _bump(profile)
            db.flush()
            return item_out(item)
        replace_id = payload.pop('replace_alternative_id', None)
        keep_previous = payload.pop('keep_previous', True)
        alternatives = point.setdefault('alternatives', [])
        if replace_id is not None:
            # Only alternatives can be dropped; the main wording (and an unknown id) is refused.
            if not any(version['id'] == replace_id for version in alternatives):
                raise BankError(422, 'INVALID_VERSION', 'Choose one of this point\'s other versions to replace')
            if mode == 'update' and replace_id == payload.get('alternative_id'):
                raise BankError(422, 'INVALID_VERSION', 'The version being updated cannot also be replaced')
            alternatives[:] = [version for version in alternatives if version['id'] != replace_id]
        needs_room = mode == 'alternative' or keep_previous
        if needs_room and len(alternatives) >= MAX_VERSIONS - 1:
            raise BankError(422, 'POINT_VERSION_LIMIT', 'A point allows 5 versions including its main wording')
        if mode == 'alternative':
            alternatives.append({'id': 'v_' + uuid4().hex, **payload})
        else:
            alternative_id = payload.pop('alternative_id', None)
            target = point if alternative_id is None else next((version for version in alternatives if version['id'] == alternative_id), None)
            if target is None:
                raise BankError(404, 'NOT_FOUND', 'Resource not found')
            if keep_previous:
                old = {key: deepcopy(value) for key, value in target.items() if key != 'alternatives'}
                old['id'] = 'v_' + uuid4().hex
                alternatives.append(old)
            target['text'] = payload['text']
    return update_item(db, item_id, expected_revision, {'data': data})


def read_basics(db):
    profile = _profile(db)
    return {'draft': profile.draft if profile else {}, 'revision': profile.revision if profile else 0,
            'bank_revision': profile.bank_revision if profile else 0,
            'confirmed_revision': profile.confirmed_revision if profile else None,
            'profile_epoch': profile.profile_epoch if profile else 0,
            'basics_provenance': profile.basics_provenance if profile else {}}


def update_basics(db, draft, expected_revision):
    allowed = {'name', 'display_name', 'headline', 'email', 'phone', 'location', 'summary', 'links'}
    if set(draft) - allowed:
        raise BankError(422, 'INVALID_PROFILE_BASICS', 'Profile draft accepts basics only; use profile items for experience and skills')
    for field, value in draft.items():
        if field != 'links' and (not isinstance(value, str) or len(value) > 5000):
            raise BankError(422, 'INVALID_PROFILE_BASICS', 'Basic fields must be text up to 5000 characters')
    if 'links' in draft and (not isinstance(draft['links'], list) or len(draft['links']) > 20 or
                            any(not isinstance(link, (str, dict)) for link in draft['links'])):
        raise BankError(422, 'INVALID_PROFILE_BASICS', 'Links must be a list of at most 20 links')
    profile = _profile(db, create=True, lock=True)
    if profile.revision != expected_revision:
        _conflict()
    provenance = deepcopy(profile.basics_provenance or {})
    for field, source in provenance.items():
        if profile.draft.get(field) != draft.get(field) and not _evidence_matches(draft.get(field), source):
            source['origin'] = 'user'
    profile.basics_provenance = provenance
    profile.draft = deepcopy(draft)
    profile.revision += 1
    _bump(profile)
    return read_basics(db)


def confirm_bank(db, expected_bank_revision):
    profile = _profile(db, create=True, lock=True)
    if profile.bank_revision != expected_bank_revision:
        _conflict()
    data = build_profile_snapshot(db)
    version = db.scalar(select(ProfileVersion).where(ProfileVersion.user_id == _user_id(db),
                         ProfileVersion.revision == profile.bank_revision))
    if version is None:
        content_hash = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        version = ProfileVersion(user_id=_user_id(db), revision=profile.bank_revision, data=data,
                                 content_hash=content_hash, embedding_status='unavailable')
        db.add(version)
        db.flush()
    profile.confirmed_revision = profile.bank_revision
    return {'confirmed': True, 'revision': profile.bank_revision, 'bank_revision': profile.bank_revision,
            'profile_version_id': str(version.id), 'embedding_status': version.embedding_status}


def get_settings(db):
    item = db.get(UserSettings, _user_id(db))
    return {'resume_defaults': item.resume_defaults if item else {}, 'revision': item.revision if item else 0}


def update_settings(db, defaults, expected_revision):
    # Lock the shared profile row to serialize the first settings insert too.
    _profile(db, create=True, lock=True)
    item = db.scalar(select(UserSettings).where(UserSettings.user_id == _user_id(db)).with_for_update())
    if (item.revision if item else 0) != expected_revision:
        _conflict()
    if item is None:
        item = UserSettings(user_id=_user_id(db), resume_defaults=deepcopy(defaults), revision=1)
        db.add(item)
    else:
        item.resume_defaults = deepcopy(defaults)
        item.revision += 1
    db.flush()
    return get_settings(db)


def delete_profile_data(db, delete_settings=False):
    profile = _profile(db, create=True, lock=True)
    paths = list(db.scalars(select(Upload.file_path).where(Upload.user_id == _user_id(db))))
    db.execute(delete(ProfileImport).where(ProfileImport.user_id == _user_id(db)))
    # Remove self-references before deleting parents and children together.
    items = db.scalars(select(ProfileItem).where(ProfileItem.user_id == _user_id(db))).all()
    for item in items:
        item.parent_id = None
    db.flush()
    db.execute(delete(ProfileItem).where(ProfileItem.user_id == _user_id(db)))
    db.execute(delete(ProfileVersion).where(ProfileVersion.user_id == _user_id(db)))
    db.execute(delete(Upload).where(Upload.user_id == _user_id(db)))
    if delete_settings:
        db.execute(delete(UserSettings).where(UserSettings.user_id == _user_id(db)))
    profile.draft = {}
    profile.basics_provenance = {}
    profile.revision += 1
    profile.confirmed_revision = None
    profile.profile_epoch += 1
    _bump(profile)
    # Storage cleanup is supplied by the HTTP composition layer, never by the domain.
    return {'deleted': True, 'bank_revision': profile.bank_revision, 'profile_epoch': profile.profile_epoch}, paths

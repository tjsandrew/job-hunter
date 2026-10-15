"""Profile-bank domain and public read contract."""
from .schema import ITEM_KINDS, validate_item_data
from .snapshots import EMBEDDING_TEXT_VERSION, assemble_profile_snapshot, profile_embedding_text

# Database readers are imported lazily so pure schema/migration use needs no DB.
def build_profile_snapshot(db):
    from .services import build_profile_snapshot as read
    return read(db)


def get_confirmed_snapshot(db):
    from .services import get_confirmed_snapshot as read
    return read(db)


def get_bank(db):
    from .services import get_bank as read
    return read(db)


def get_bullet(db, item_id, bullet_id):
    from .services import get_bullet as read
    return read(db, item_id, bullet_id)

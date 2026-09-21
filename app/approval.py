"""
approval.py
===========
รับรองผลทั้งรอบ is a statement about one specific set of results. When those
results change, the statement no longer describes them, so the approval is withdrawn.

It is withdrawn rather than the round being locked: a locked round would forbid
correcting a wrong value, which is exactly what an approved round most needs. And
withdrawing loses nothing — the data stays, only the claim that someone vouched for it
goes, and the next approval says who vouches for what is there now.

Called wherever a stored result of a round can actually change: an import that stores
something new, a conflict resolved in favour of the new value, a value typed by hand.
Not called for a file that changes nothing (same values again), or for a conflict that
is only found, or kept as it was.
"""

from app.models import CheckupBatch


def revoke_if_approved(db, batch: "CheckupBatch | int | None") -> bool:
    """True if an approval was withdrawn. Accepts the round or its id."""
    if batch is None:
        return False
    if isinstance(batch, int):
        batch = db.get(CheckupBatch, batch)
        if batch is None:
            return False
    if not batch.is_approved:
        return False
    batch.is_approved = False
    batch.approved_by = None
    batch.approved_at = None
    return True

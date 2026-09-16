"""
Nothing waiting for a human may be hidden by a cap the caller cannot see.

`/api/reviews` capped its answer at a hard-coded 500 rows. Reviews are the only way
an item waiting for a human is visible at all, so every row past the cap waited
forever with nothing on any screen to say so. On 2026-09-16 a database with 521 open
reviews showed 3 of its 24 open mapping questions, and the page looked finished.

These tests need no database: they hand the route a fake query and watch what it asks
for. That matches the rest of the suite, which deliberately avoids Postgres.
"""

from app.routes import conflicts as conflicts_route
from app.routes import reviews as reviews_route


class FakeQuery:
    """Records the limit asked for, and returns nothing."""

    def __init__(self, seen):
        self.seen = seen

    def filter(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def limit(self, n):
        self.seen.append(n)
        return []


class FakeDB:
    def __init__(self):
        self.limits = []

    def query(self, model):
        return FakeQuery(self.limits)


def test_reviews_default_cap_is_far_above_the_old_500():
    db = FakeDB()
    reviews_route.list_reviews(db=db)
    assert db.limits == [5000], "the default must leave room for a real backlog"


def test_reviews_cap_is_the_callers_choice():
    db = FakeDB()
    reviews_route.list_reviews(limit=12, db=db)
    assert db.limits == [12], "the page asks for a cap it knows, so it can tell it hit it"


def test_reviews_cap_is_never_zero_or_negative():
    db = FakeDB()
    reviews_route.list_reviews(limit=0, db=db)
    reviews_route.list_reviews(limit=-5, db=db)
    assert db.limits == [1, 1], "a zero cap would hide every open review at once"


def test_conflicts_have_the_same_protection():
    db = FakeDB()
    conflicts_route.list_conflicts(db=db)
    conflicts_route.list_conflicts(limit=7, db=db)
    assert db.limits == [5000, 7], "an unseen conflict is an undecided conflict"

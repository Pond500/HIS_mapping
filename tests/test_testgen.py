"""The generated test sets must be internally consistent, and the exam set untouched."""

from testgen import selfcheck
from testgen.build import verify
import random

from testgen.truth import cid_checksum, corrupt_cid, make_cid


def test_cid_checksum_worked_example():
    # digits 1 1 0 0 5 0 0 1 1 2 2 3, weights 13..2:
    # 13+12+0+0+45+0+0+6+5+8+6+6 = 101; 101 % 11 = 2; (11 - 2) % 10 = 9
    # (so the old mock CID 1100500112233 is NOT valid)
    assert cid_checksum("110050011223") == 9


def test_generated_cids_valid_and_corruption_invalid():
    rng = random.Random(1)
    for _ in range(200):
        cid = make_cid(rng)
        assert cid_checksum(cid[:12]) == int(cid[12])
        bad = corrupt_cid(cid, rng)
        assert cid_checksum(bad[:12]) != int(bad[12])


def test_dev_set_consistent():
    assert selfcheck.main("dev")


def test_exam_set_consistent_and_locked():
    assert verify("exam")
    assert selfcheck.main("exam")

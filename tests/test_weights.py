import pytest

from app.weights import Slot, WeightError, problems, rebalance


def active(n):
    return [Slot(True, False, 0) for _ in range(n)]


@pytest.mark.parametrize(
    "n, expected",
    [
        (1, [100]),
        (2, [50, 50]),
        (3, [34, 33, 33]),
        (4, [25, 25, 25, 25]),
        (6, [17, 17, 17, 17, 16, 16]),
        (7, [15, 15, 14, 14, 14, 14, 14]),
    ],
)
def test_even_split_always_sums_to_100(n, expected):
    shares = rebalance(active(n))
    assert shares == expected
    assert sum(shares) == 100


def test_pinned_share_is_kept_and_rest_split():
    slots = [Slot(True, True, 25), Slot(True, False, 0), Slot(True, False, 0)]
    assert rebalance(slots) == [25, 38, 37]


def test_removed_offers_get_zero():
    slots = [Slot(True, False, 50), Slot(False, False, 50), Slot(True, False, 0)]
    assert rebalance(slots) == [50, 0, 50]


def test_pinned_over_100_is_rejected():
    with pytest.raises(WeightError):
        rebalance([Slot(True, True, 70), Slot(True, True, 40)])


def test_problems():
    assert problems([Slot(True, False, 100)]) == []
    assert problems([Slot(False, False, 0)]) == ["В потоке нет активных офферов"]
    # всё закреплено, но в сумме не 100 — публиковать нельзя
    assert "90%" in problems([Slot(True, True, 50), Slot(True, True, 40)])[0]

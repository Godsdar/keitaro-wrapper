"""Пересчёт долей офферов в потоке.

В Keitaro доля (share) — целое число процентов, сумма по активным офферам
должна быть ровно 100. Правила:
- закреплённые (pinned) доли не меняются;
- остаток 100 − Σзакреплённых делится поровну между незакреплёнными
  активными офферами; если не делится нацело, лишние проценты по одному
  получают первые офферы (100 / 3 → 34, 33, 33);
- у удалённых офферов доля 0.
"""

from dataclasses import dataclass


class WeightError(ValueError):
    pass


@dataclass
class Slot:
    active: bool
    pinned: bool
    share: int


def rebalance(slots: list[Slot]) -> list[int]:
    """Возвращает новые доли в том же порядке, что и slots."""
    pinned_total = sum(s.share for s in slots if s.active and s.pinned)
    if pinned_total > 100:
        raise WeightError(f"Закреплённые доли в сумме {pinned_total}% — больше 100%")

    free = [i for i, s in enumerate(slots) if s.active and not s.pinned]
    rest = 100 - pinned_total
    base, extra = divmod(rest, len(free)) if free else (0, 0)

    result = []
    free_rank = {idx: rank for rank, idx in enumerate(free)}
    for i, s in enumerate(slots):
        if not s.active:
            result.append(0)
        elif s.pinned:
            result.append(s.share)
        else:
            result.append(base + (1 if free_rank[i] < extra else 0))
    return result


def problems(slots: list[Slot]) -> list[str]:
    """Почему поток нельзя опубликовать (пустой список — можно)."""
    active = [s for s in slots if s.active]
    if not active:
        return ["В потоке нет активных офферов"]
    total = sum(s.share for s in active)
    if total != 100:
        return [f"Сумма долей {total}%, а должна быть 100% — открепите или поправьте доли"]
    return []

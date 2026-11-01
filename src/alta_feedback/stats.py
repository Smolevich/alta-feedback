"""Сводка проверенных отчётов о счетах для публичной страницы статистики."""

from collections import Counter
from dataclasses import dataclass, field

from alta_feedback.accounts import ACCOUNT_TYPES, DOCUMENTS, RESIDENCIES, RESULTS

RECENT_MAX = 20
NO_RESIDENCY = "Не указан"


@dataclass
class Tally:
    """Итоги по одной группе: банку, городу или статусу."""

    name: str
    results: Counter = field(default_factory=Counter)
    types: Counter = field(default_factory=Counter)

    @property
    def total(self) -> int:
        return sum(self.results.values())

    def share(self, result: str) -> int:
        """Доля результата в процентах — ширина полоски."""
        return round(100 * self.results[result] / self.total) if self.total else 0


@dataclass(frozen=True)
class DocumentCount:
    name: str
    count: int
    percent: int


@dataclass(frozen=True)
class AccountStats:
    total: int
    results: Counter
    banks: list[Tally]
    cities: list[Tally]
    residencies: list[Tally]
    documents: list[DocumentCount]
    recent: list[dict]


def tally_by(items: list[dict], key: str, names: dict[str, str] | None = None) -> list[Tally]:
    """Группы по полю отчёта, крупные сверху; коды заменяются подписями."""
    groups: dict[str, Tally] = {}
    for item in items:
        raw = item[key] or ""
        name = (names or {}).get(raw, raw) or NO_RESIDENCY
        tally = groups.setdefault(name, Tally(name))
        tally.results[item["result"]] += 1
        tally.types[item["account_type"]] += 1
    return sorted(groups.values(), key=lambda tally: (-tally.total, tally.name))


def count_documents(items: list[dict]) -> list[DocumentCount]:
    counts = Counter(DOCUMENTS.get(doc, doc) for item in items for doc in item["documents"])
    total = len(items)
    return [
        DocumentCount(name, count, round(100 * count / total))
        for name, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    ]


def readable(item: dict) -> dict:
    """Запись для карточки: коды заменены словами."""
    return {
        **item,
        "account_type": ACCOUNT_TYPES.get(item["account_type"], item["account_type"]),
        "result_label": RESULTS.get(item["result"], item["result"]),
        "residency": RESIDENCIES.get(item["residency"], item["residency"]),
        "documents": [DOCUMENTS.get(doc, doc) for doc in item["documents"]],
    }


def account_stats(items: list[dict]) -> AccountStats:
    """Сводка по принятым отчётам; items — свежие визиты сверху."""
    return AccountStats(
        total=len(items),
        results=Counter(item["result"] for item in items),
        banks=tally_by(items, "bank"),
        cities=tally_by(items, "city"),
        residencies=tally_by(items, "residency", RESIDENCIES),
        documents=count_documents(items),
        recent=[readable(item) for item in items[:RECENT_MAX]],
    )

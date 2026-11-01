"""Сводка проверенных отчётов о счетах для публичной страницы статистики."""

from collections import Counter
from dataclasses import dataclass, field

from alta_feedback.accounts import ACCOUNT_TYPES, DOCUMENTS, RESIDENCIES, RESULTS

RECENT_MAX = 20
NO_RESIDENCY = "Не указан"
# Отделение показываем, только если о нём минимум два ответа: по одному ответу человека легко узнать.
BRANCH_MIN = 2
OTHER_BRANCHES = "Другие отделения"


@dataclass
class Tally:
    """Итоги по одной группе: банку, городу или статусу."""

    name: str
    results: Counter = field(default_factory=Counter)
    types: Counter = field(default_factory=Counter)
    branches: list["Tally"] = field(default_factory=list)

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


def branch_counts(items: list[dict]) -> Counter:
    return Counter((item["bank"], item["branch"]) for item in items if item.get("branch"))


def hide_rare_branches(items: list[dict]) -> list[dict]:
    """Отделение остаётся в записи, только если о нём в этом банке не меньше BRANCH_MIN ответов."""
    counts = branch_counts(items)

    def visible(item: dict) -> str | None:
        branch = item.get("branch")
        return branch if counts[(item["bank"], branch)] >= BRANCH_MIN else None

    return [{**item, "branch": visible(item)} for item in items]


def branch_tallies(bank_items: list[dict]) -> list[Tally]:
    """Разбивка одного банка по отделениям; редкие и не указанные — одной строкой в конце.

    Пусто, если ни одно отделение не набрало BRANCH_MIN ответов: одна строка «другие» ничего не говорит.
    """
    groups: dict[str, Tally] = {}
    for item in hide_rare_branches(bank_items):
        name = item["branch"] or OTHER_BRANCHES
        tally = groups.setdefault(name, Tally(name))
        tally.results[item["result"]] += 1
        tally.types[item["account_type"]] += 1
    if set(groups) <= {OTHER_BRANCHES}:
        return []
    return sorted(groups.values(), key=lambda tally: (tally.name == OTHER_BRANCHES, -tally.total, tally.name))


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
    banks = tally_by(items, "bank")
    for tally in banks:
        tally.branches = branch_tallies([item for item in items if item["bank"] == tally.name])
    return AccountStats(
        total=len(items),
        results=Counter(item["result"] for item in items),
        banks=banks,
        cities=tally_by(items, "city"),
        residencies=tally_by(items, "residency", RESIDENCIES),
        documents=count_documents(items),
        recent=[readable(item) for item in hide_rare_branches(items)[:RECENT_MAX]],
    )

"""Сводка проверенных отчётов о счетах для публичной страницы статистики."""

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date

from alta_feedback.accounts import ACCOUNT_TYPES, BANKS, CITIES, DOCUMENTS, RESIDENCIES, RESULTS

PAGE_SIZE = 20
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


@dataclass(frozen=True)
class AnswerFilter:
    """Фильтр ответов на странице статистики: коды справочников и даты визита ISO."""

    bank: str | None = None
    city: str | None = None
    result: str | None = None
    date_from: str | None = None
    date_to: str | None = None

    @property
    def active(self) -> bool:
        return any(self.query().values())

    def equals(self) -> dict[str, str]:
        """Колонка → значение, как оно лежит в базе: банк и город хранятся подписями."""
        pairs = {
            "bank": BANKS.get(self.bank or ""),
            "city": CITIES.get(self.city or ""),
            "result": self.result,
        }
        return {column: value for column, value in pairs.items() if value}

    def query(self) -> dict[str, str]:
        """Параметры для ссылок, чтобы листание не сбрасывало фильтр."""
        pairs = {
            "bank": self.bank, "city": self.city, "result": self.result,
            "from": self.date_from, "to": self.date_to,
        }
        return {name: value for name, value in pairs.items() if value}


@dataclass(frozen=True)
class AnswerPage:
    items: list[dict]
    next_cursor: str | None


def pick(raw: str | None, names: Mapping[str, str]) -> str | None:
    return raw if raw in names else None


def iso_date(raw: str | None) -> str | None:
    try:
        return date.fromisoformat(raw or "").isoformat()
    except ValueError:
        return None


def parse_filter(params: Mapping[str, str]) -> AnswerFilter:
    """Фильтр из GET-параметров; значение не из справочника или не дата — просто не применяется."""
    return AnswerFilter(
        bank=pick(params.get("bank"), BANKS),
        city=pick(params.get("city"), CITIES),
        result=pick(params.get("result"), RESULTS),
        date_from=iso_date(params.get("from")),
        date_to=iso_date(params.get("to")),
    )


def parse_cursor(raw: str | None) -> tuple[str, int] | None:
    """Курсор `<visit_date>_<id>` — последний показанный ответ; битый — None, то есть с начала."""
    visit_date, _, item_id = (raw or "").rpartition("_")
    if not item_id.isdigit() or iso_date(visit_date) != visit_date:
        return None
    return visit_date, int(item_id)


def cursor_of(item: dict) -> str:
    return f"{item['visit_date']}_{item['id']}"


def answer_page(rows: list[dict], size: int) -> AnswerPage:
    """Страница из size + 1 строк: лишняя строка значит, что есть следующая страница."""
    items = rows[:size]
    return AnswerPage(items, cursor_of(items[-1]) if len(rows) > size and items else None)


def shown_before(items: list[dict], cursor: tuple[str, int] | None) -> int:
    """Сколько ответов из items показано до курсора включительно: номер первой строки минус один."""
    if cursor is None:
        return 0
    return sum(1 for item in items if (item["visit_date"], item["id"]) >= cursor)


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


def hide_rare_branches(items: list[dict], counts: Counter | None = None) -> list[dict]:
    """Отделение остаётся в записи, только если о нём в этом банке не меньше BRANCH_MIN ответов.

    counts — число ответов по (банк, отделение) среди всех принятых: страница или фильтр видят
    лишь часть записей, а прятать отделение надо по полному числу.
    """
    counts = branch_counts(items) if counts is None else counts

    def visible(item: dict) -> str | None:
        branch = item.get("branch")
        return branch if counts[(item["bank"], branch)] >= BRANCH_MIN else None

    return [{**item, "branch": visible(item)} for item in items]


def branch_tallies(bank_items: list[dict], counts: Counter | None = None) -> list[Tally]:
    """Разбивка одного банка по отделениям; редкие и не указанные — одной строкой в конце.

    Пусто, если ни одно отделение не набрало BRANCH_MIN ответов: одна строка «другие» ничего не говорит.
    """
    groups: dict[str, Tally] = {}
    for item in hide_rare_branches(bank_items, counts):
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


def answer_cards(items: list[dict], counts: Counter | None = None) -> list[dict]:
    return [readable(item) for item in hide_rare_branches(items, counts)]


def account_stats(items: list[dict], counts: Counter | None = None) -> AccountStats:
    """Сводка по принятым отчётам; counts — отделения по всем принятым, см. hide_rare_branches."""
    banks = tally_by(items, "bank")
    for tally in banks:
        tally.branches = branch_tallies([item for item in items if item["bank"] == tally.name], counts)
    return AccountStats(
        total=len(items),
        results=Counter(item["result"] for item in items),
        banks=banks,
        cities=tally_by(items, "city"),
        residencies=tally_by(items, "residency", RESIDENCIES),
        documents=count_documents(items),
    )

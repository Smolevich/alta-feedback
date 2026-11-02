"""Официальные цифры Народного банка Сербии по банкам (data/nbs_banks.json).

Числа посчитаны из квартальных форм NBS: баланс (строки A, A.I, A.IV, A.VI, PO.III, PK.XX) и отчёт
о прибыли (XXI.1 − XXI.2, 12 месяцев); у каждой цифры — ссылка на форму. Цифра без https-ссылки
не показывается.
"""

import json
from dataclasses import dataclass
from datetime import date
from functools import cache
from importlib.resources import files

from alta_feedback.accounts import BANKS, match_label
from alta_feedback.branches import fold

TOP = 10
SOURCE_URL = "https://webappcenter.nbs.rs/WebApp/FinInstBank/BankFinancialBalanceSheet/IndexArchive"
# Банк без лицензии: в справке по размеру остаётся для сравнения, с ответами формы не сопоставляется.
DEFUNCT = frozenset({"alta"})


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    explain: str
    digits: int


METRICS: tuple[Metric, ...] = (
    Metric("share", "Доля рынка", "какая часть всех активов банков Сербии приходится на этот банк", 1),
    Metric("equity_ratio", "Капитал к активам",
           "сколько собственных денег владельцев на каждые 100 динаров активов: "
           "ими банк первым покрывает убытки, раньше вкладчиков", 1),
    Metric("liquidity", "Деньги под рукой",
           "наличные, деньги на счёте в Народном банке и ценные бумаги "
           "на каждые 100 динаров активов", 1),
    Metric("loan_deposit", "Кредиты к вкладам",
           "сколько выдано кредитов клиентам на каждые 100 динаров их вкладов; "
           "больше 100 — кредиты не покрыты вкладами", 0),
    Metric("roa", "Прибыльность (ROA)",
           "сколько банк заработал за 12 месяцев (июль 2025 – июнь 2026) на каждые 100 динаров "
           "активов; минус — убыток. Ссылки 2–4 — отчёты, из которых сложена прибыль за 12 месяцев, "
           "и баланс с активами", 2),
)
ASSETS = Metric("assets", "Активы", "всё, чем владеет банк: кредиты, деньги, ценные бумаги — "
                "по ним видно размер банка", 1)


@dataclass(frozen=True)
class Figure:
    value: float
    source_url: str
    also: tuple[str, ...] = ()


@dataclass(frozen=True)
class Row:
    """Строка карточки банка: подпись, число для показа и где его проверить."""

    label: str
    text: str
    amount: str
    source_url: str
    also: tuple[str, ...]


@dataclass(frozen=True)
class Bank:
    code: str
    name: str
    rank: int
    aliases: tuple[str, ...]
    figures: dict[str, Figure]

    @property
    def defunct(self) -> bool:
        return self.code in DEFUNCT

    @property
    def size(self) -> Row | None:
        """Активы банка в млрд динаров; None — у цифры нет источника."""
        return row(ASSETS, self.figures.get(ASSETS.key), " млрд RSD")

    @property
    def rows(self) -> list[Row]:
        return [r for metric in METRICS if (r := row(metric, self.figures.get(metric.key), " %"))]

    @property
    def share(self) -> Row | None:
        return next((r for r in self.rows if r.label == METRICS[0].label), None)

    @property
    def details(self) -> list[Row]:
        """Показатели, которые видны после раскрытия строки банка: всё, кроме доли рынка."""
        return [r for r in self.rows if r.label != METRICS[0].label]


@dataclass(frozen=True)
class Snapshot:
    as_of: date
    bank_count: int
    banks: tuple[Bank, ...]

    @property
    def day(self) -> str:
        return self.as_of.strftime("%d.%m.%Y")

    def top(self, count: int = TOP) -> list[Bank]:
        return sorted(self.banks, key=lambda bank: bank.rank)[:count]

    def find(self, name: str) -> Bank | None:
        """Банк NBS для названия из ответа формы: по справочнику формы, иначе по написанию."""
        code = match_label(name, BANKS)
        wanted = fold(name)
        for bank in self.banks:
            if bank.defunct:
                continue
            if bank.code == code or any(called(wanted, alias) for alias in bank.aliases):
                return bank
        return None

    def listing(self, names: list[str]) -> tuple[list[Bank], list[Bank]]:
        """Банки из ответов формы (в их порядке, без повторов) и остальные из топа по размеру."""
        reported: list[Bank] = []
        for name in names:
            bank = self.find(name)
            if bank and bank not in reported:
                reported.append(bank)
        return reported, [bank for bank in self.top() if bank not in reported]


def called(wanted: str, alias: str) -> bool:
    """«Raiffeisen banka Srbija» — тоже Raiffeisen: псевдоним целым первым словом (словами)."""
    return wanted == alias or wanted.startswith(alias + " ")


def number(value: float, digits: int) -> str:
    """Число по-русски: пробел между тысячами, запятая перед дробью, настоящий минус."""
    text = f"{abs(value):,.{digits}f}".replace(",", " ").replace(".", ",")
    return f"−{text}" if value < 0 else text


def sourced(figure: Figure | None) -> bool:
    return figure is not None and figure.source_url.startswith("https://")


def row(metric: Metric, figure: Figure | None, unit: str) -> Row | None:
    if not sourced(figure):
        return None
    amount = number(figure.value, metric.digits)
    return Row(metric.label, amount + unit, amount, figure.source_url, figure.also)


def parse_figure(raw: dict) -> Figure:
    return Figure(float(raw["value"]), raw.get("source_url") or "", tuple(raw.get("also", ())))


def parse_snapshot(raw: dict) -> Snapshot:
    banks = tuple(
        Bank(
            code=item["code"],
            name=item["name"],
            rank=int(item["rank"]),
            aliases=tuple(fold(alias) for alias in item.get("aliases", ())),
            figures={key: parse_figure(value) for key, value in item["figures"].items()},
        )
        for item in raw["banks"]
    )
    return Snapshot(date.fromisoformat(raw["as_of"]), int(raw["bank_count"]), banks)


@cache
def snapshot() -> Snapshot:
    text = files("alta_feedback").joinpath("data/nbs_banks.json").read_text(encoding="utf-8")
    return parse_snapshot(json.loads(text))

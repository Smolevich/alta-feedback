"""Анонимные отчёты «где мне открыли счёт»: справочники, разбор формы, вычистка личных данных."""

import re
from dataclasses import dataclass
from datetime import date, timedelta

# Действующие банки по реестру NBS на 01.11.2026 (без ALTA), сначала самые частые у иностранцев.
BANKS: dict[str, str] = {
    "intesa": "Banca Intesa",
    "otp": "OTP banka",
    "raiffeisen": "Raiffeisen",
    "unicredit": "UniCredit",
    "aik": "AikBank",
    "nlb": "NLB Banka",
    "postanska": "Poštanska štedionica",
    "erste": "Erste",
    "addiko": "Addiko",
    "procredit": "ProCredit",
    "halkbank": "Halkbank",
    "yettel": "Yettel Bank",
    "adriatic": "Adriatic Bank",
    "3banka": "3 Banka",
    "api": "API Bank",
    "mirabank": "Mirabank",
    "bankofchina": "Bank of China",
    "srpska": "Srpska banka",
}
CITIES: dict[str, str] = {
    "beograd": "Белград",
    "novisad": "Нови-Сад",
    "nis": "Ниш",
    "kragujevac": "Крагуевац",
    "subotica": "Суботица",
}
ACCOUNT_TYPES: dict[str, str] = {"personal": "Личный", "entrepreneur": "ИП (preduzetnik)"}
RESULTS: dict[str, str] = {"opened": "Открыли", "refused": "Отказали", "pending": "Ещё в процессе"}
# Временный и постоянный ВНЖ для банков одно и то же — одним чипом.
RESIDENCIES: dict[str, str] = {
    "boravak": "ВНЖ / ПМЖ (боравак)",
    "white_card": "Только белый картон",
    "tourist": "Ничего нет (турист)",
    "citizen": "Гражданин Сербии",
}
DOCUMENTS: dict[str, str] = {
    "passport": "Паспорт",
    "boravak": "Боравак / ВНЖ",
    "jmbg": "JMBG / EBS",
    "lease": "Договор аренды / белый картон",
    "income": "Справка с работы / доход",
    "apr": "PIB и решение APR (ИП)",
    "reference": "Рекомендация другого банка",
    "statements": "Выписки из другого банка",
    "nothing": "Ничего сверх обычного",
}
FREE_TEXT_MAX = 60
DOCUMENTS_MAX = 15
COMMENT_MAX = 1000
VISIT_DAYS_BACK = 400
ACCOUNT_STATUSES = frozenset({"new", "accepted", "rejected", "test", "spam"})

MASK = "[скрыто]"
# Порядок важен: сначала длинные номера счетов, потом 13 цифр JMBG, потом всё остальное длинное.
PII_PATTERNS = (
    re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
    re.compile(r"\bRS\s?\d{2}(?:[\s-]?\d){18}\b", re.IGNORECASE),
    re.compile(r"(?<!\d)\d{3}[\s-]?\d{13}[\s-]?\d{2}(?!\d)"),
    re.compile(r"(?<!\d)\d{13}(?!\d)"),
    # Телефоны, паспорта, короткая запись счёта: 9+ цифр с пробелами, дефисами, скобками, слэшами.
    # Точку не считаем разделителем, чтобы не съедать даты вида 08.10.2026.
    re.compile(r"(?<![\w])\+?\d(?:[\s()/-]{0,2}\d){8,}(?!\d)"),
)


@dataclass(frozen=True)
class AccountReport:
    bank: str
    city: str
    account_type: str
    result: str
    visit_date: str
    residency: str
    documents: tuple[str, ...]
    comment: str


def scrub_pii(text: str) -> str:
    """Заменяет похожее на email, JMBG, номер счёта, телефон или паспорт на «[скрыто]»."""
    for pattern in PII_PATTERNS:
        text = pattern.sub(MASK, text)
    return text


def free_text(raw: str) -> str:
    return scrub_pii(" ".join(raw.split())[:FREE_TEXT_MAX])


def match_label(raw: str, names: dict[str, str]) -> str | None:
    """Код справочника по коду или по подписи без учёта регистра; None — значения в справочнике нет."""
    value = " ".join(raw.split())
    if value in names:
        return value
    wanted = value.casefold()
    return next((code for code, label in names.items() if label.casefold() == wanted), None)


def pick_name(raw: str, names: dict[str, str]) -> str:
    """Название из справочника или своё значение человека, очищенное от личных данных."""
    code = match_label(raw, names)
    return names[code] if code else free_text(raw)


def pick_code(raw: str, names: dict[str, str]) -> str:
    """Код справочника или своё значение человека, очищенное от личных данных."""
    return match_label(raw, names) or free_text(raw)


def pick_documents(values: list[str]) -> tuple[str, ...]:
    """Коды документов из справочника и свои значения, без пустых и повторов."""
    picked = [pick_code(value, DOCUMENTS) for value in values]
    unique = [value for value in dict.fromkeys(picked) if value]
    return tuple(unique[:DOCUMENTS_MAX])


def parse_visit_date(raw: str, today: date) -> str | None:
    """Дата визита ISO; будущее (кроме завтра — часовые пояса) и слишком старое не принимаем."""
    try:
        visit = date.fromisoformat(raw.strip())
    except ValueError:
        return None
    if not today - timedelta(days=VISIT_DAYS_BACK) <= visit <= today + timedelta(days=1):
        return None
    return visit.isoformat()


def parse_account_form(
    form: dict[str, str], documents: list[str], today: date
) -> tuple[AccountReport, list[str]]:
    """Собирает отчёт из полей формы; возвращает его и список ошибок для человека.

    Банк, город, статус и документы приходят текстом из полей с подсказками: название из
    списка превращается в справочное значение, своё сохраняется как есть после вычистки.
    """
    bank = pick_name(form.get("bank", ""), BANKS)
    city = pick_name(form.get("city", ""), CITIES)
    account_type = form.get("account_type", "")
    result = form.get("result", "")
    visit_date = parse_visit_date(form.get("visit_date", ""), today)
    residency = form.get("residency", "")
    comment = (form.get("comment") or "").strip()
    errors: list[str] = []
    if not bank:
        errors.append("Выберите банк или впишите свой.")
    if not city:
        errors.append("Выберите город или впишите свой.")
    if account_type not in ACCOUNT_TYPES:
        errors.append("Укажите, какой счёт: личный или ИП.")
    if result not in RESULTS:
        errors.append("Укажите, чем закончилось: открыли, отказали или ещё в процессе.")
    if visit_date is None:
        errors.append("Дата визита — не в будущем и не старше года.")
    if len(comment) > COMMENT_MAX:
        errors.append(f"Комментарий длиннее {COMMENT_MAX} знаков.")
    report = AccountReport(
        bank=bank,
        city=city,
        account_type=account_type,
        result=result,
        visit_date=visit_date or "",
        residency=pick_code(residency, RESIDENCIES),
        documents=pick_documents(documents),
        comment=scrub_pii(comment),
    )
    return report, errors


def labels() -> dict[str, dict[str, str]]:
    """Подписи кодов для тех, кто строит таблицу из публичного JSON."""
    return {
        "account_type": ACCOUNT_TYPES,
        "result": RESULTS,
        "residency": RESIDENCIES,
        "documents": DOCUMENTS,
    }

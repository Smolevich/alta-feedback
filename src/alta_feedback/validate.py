"""Чистые правила формы: что принимаем и как режем входные строки."""

import hashlib
import re
from dataclasses import dataclass

TEXT_MAX = 2000
SOURCE_MAX = 500
CONTACT_MAX = 200
TITLE_MAX = 200
UA_MAX = 120
SECTION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
STATUSES = frozenset({"new", "accepted", "rejected", "test", "spam"})


@dataclass(frozen=True)
class Suggestion:
    section_id: str
    section_title: str
    text: str
    source: str
    contact: str


def clean_section_id(raw: str | None) -> str:
    """id раздела из ссылки; всё, что не похоже на id, превращается в пустую строку."""
    value = (raw or "").strip()
    return value if SECTION_ID_RE.match(value) else ""


def clip(raw: str | None, limit: int) -> str:
    return " ".join((raw or "").split())[:limit]


def parse_form(form: dict[str, str]) -> tuple[Suggestion, list[str]]:
    """Собирает правку из полей формы и возвращает её вместе со списком ошибок."""
    text = (form.get("text") or "").strip()
    source = (form.get("source") or "").strip()
    contact = (form.get("contact") or "").strip()
    errors: list[str] = []
    if not text:
        errors.append("Напишите, что исправить.")
    if len(text) > TEXT_MAX:
        errors.append(f"Текст правки длиннее {TEXT_MAX} знаков.")
    if len(source) > SOURCE_MAX:
        errors.append(f"Источник длиннее {SOURCE_MAX} знаков.")
    if len(contact) > CONTACT_MAX:
        errors.append(f"Контакт длиннее {CONTACT_MAX} знаков.")
    suggestion = Suggestion(
        section_id=clean_section_id(form.get("s")),
        section_title=clip(form.get("section_title"), TITLE_MAX),
        text=text,
        source=source,
        contact=contact,
    )
    return suggestion, errors


def is_bot(form: dict[str, str]) -> bool:
    """Скрытое поле видят только боты: человек его не заполняет."""
    return bool((form.get("website") or "").strip())


def hash_ip(ip: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{ip}".encode()).hexdigest()[:32]

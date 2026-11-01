"""Справочник отделений банков (data/branches.json, собирает scripts/build_branches.py) и выбор отделения."""

import json
import unicodedata
from dataclasses import dataclass
from functools import cache
from importlib.resources import files

BRANCH_MAX = 120
NOT_SURE = "Не помню / не важно"
# Города формы в том виде, как их пишут сайты банков.
CITY_LATIN: dict[str, str] = {
    "beograd": "Beograd",
    "novisad": "Novi Sad",
    "nis": "Niš",
    "kragujevac": "Kragujevac",
    "subotica": "Subotica",
}
CYRILLIC = dict(zip(
    "абвгдђежзийклљмнњопрстћуфхцчџшщыэюяё",
    ["a", "b", "v", "g", "d", "dj", "e", "z", "z", "i", "j", "k", "l", "lj", "m", "n", "nj", "o", "p",
     "r", "s", "t", "c", "u", "f", "h", "c", "c", "dz", "s", "s", "i", "e", "ju", "ja", "e"],
    strict=True,
))


@dataclass(frozen=True)
class Branch:
    city: str
    name: str
    address: str

    @property
    def label(self) -> str:
        """Строка подсказки и значение, которое сохраняется в отчёт."""
        return f"{self.name} — {self.address}" if self.name else self.address


type Directory = dict[str, tuple[Branch, ...]]


def fold(text: str) -> str:
    """Ключ сравнения: латиница без диакритики и регистра, дефисы как пробелы («Нови-Сад» = «Novi Sad»)."""
    lowered = text.casefold().replace("đ", "dj")
    latin = "".join(CYRILLIC.get(char, char) for char in lowered)
    plain = "".join(c for c in unicodedata.normalize("NFKD", latin) if not unicodedata.combining(c))
    return " ".join(plain.replace("-", " ").split())


def parse_directory(raw: dict) -> Directory:
    return {
        code: tuple(Branch(item["city"], item["name"], item["address"]) for item in entry["branches"])
        for code, entry in raw["banks"].items()
    }


@cache
def directory() -> Directory:
    text = files("alta_feedback").joinpath("data/branches.json").read_text(encoding="utf-8")
    return parse_directory(json.loads(text))


def city_key(city_code: str | None, city_text: str) -> str:
    """Город формы (код справочника или свой текст) как ключ сравнения с городами банков."""
    return fold(CITY_LATIN.get(city_code or "", city_text))


def branch_options(branches: tuple[Branch, ...], city: str) -> list[str]:
    """Подсказки для поля «Отделение»: «Не помню» и отделения банка в этом городе."""
    labels = sorted({item.label for item in branches if fold(item.city) == city}, key=fold)
    return [NOT_SURE, *labels]


def match_branch(raw: str, branches: tuple[Branch, ...]) -> str | None:
    """Название из справочника банка, если человек выбрал его из подсказок (без учёта регистра)."""
    wanted = fold(raw)
    return next((item.label for item in branches if fold(item.label) == wanted), None)

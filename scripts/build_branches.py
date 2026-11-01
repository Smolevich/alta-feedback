# /// script
# requires-python = ">=3.13"
# dependencies = ["pdfplumber>=0.11"]
# ///
"""Справочник отделений банков формы «Где открыли счёт» — только с официальных сайтов банков.

Запуск: `uv run scripts/build_branches.py`. Пишет src/alta_feedback/data/branches.json: у каждого
банка источник, дата сбора и список {city, name, address}. Если сайт банка не ответил, у банка
остаются прежние данные с прежней датой; если их нет — status "unavailable", в форме только
свободный ввод.
"""

import html
import io
import json
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pdfplumber

OUT = Path(__file__).resolve().parent.parent / "src" / "alta_feedback" / "data" / "branches.json"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0 Safari/537.36"
)
TIMEOUT = 60

type Branch = dict[str, str]

# Районы Белграда, которые банки пишут вместо города: в форме город один — Белград.
BELGRADE_AREAS = frozenset({
    "banovo brdo", "bezanija", "borca", "cukarica", "dorcol", "karaburma", "konjarnik", "krnjaca",
    "mirijevo", "novi beograd", "palilula", "rakovica", "savski venac", "stari grad", "surcin",
    "visnjica", "vozdovac", "vracar", "zemun", "zvezdara", "zarkovo", "skyline",
})
CYRILLIC = dict(zip(
    "абвгдђежзијклљмнњопрстћуфхцчџшАБВГДЂЕЖЗИЈКЛЉМНЊОПРСТЋУФХЦЧЏШ",
    ["a", "b", "v", "g", "d", "đ", "e", "ž", "z", "i", "j", "k", "l", "lj", "m", "n", "nj", "o", "p",
     "r", "s", "t", "ć", "u", "f", "h", "c", "č", "dž", "š",
     "A", "B", "V", "G", "D", "Đ", "E", "Ž", "Z", "I", "J", "K", "L", "Lj", "M", "N", "Nj", "O", "P",
     "R", "S", "T", "Ć", "U", "F", "H", "C", "Č", "Dž", "Š"],
    strict=True,
))
ROMAN = frozenset({"I", "II", "III", "IV", "V", "VI"})


def get(url: str, data: bytes | None = None, headers: dict[str, str] | None = None) -> str:
    request = urllib.request.Request(url, data=data, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read().decode("utf-8-sig", errors="replace")


def get_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read()


def tidy(text: str) -> str:
    return " ".join(html.unescape(text).replace(" ", " ").split()).strip(" ,")


def to_latin(text: str) -> str:
    """Сербская кириллица в латиницу; слово заглавными остаётся заглавным (ЉИГ → LJIG)."""
    words = []
    for word in text.split(" "):
        latin = "".join(CYRILLIC.get(char, char) for char in word)
        words.append(latin.upper() if word.isupper() else latin)
    return " ".join(words)


def fold(text: str) -> str:
    """Ключ сравнения: латиница, без диакритики и регистра."""
    decomposed = unicodedata.normalize("NFKD", to_latin(text).replace("đ", "dj").replace("Đ", "Dj"))
    return " ".join("".join(c for c in decomposed if not unicodedata.combining(c)).casefold().split())


def capitalized(word: str) -> str:
    if word in ROMAN:
        return word
    if word in {"BB", "BR."}:
        return word.lower()
    return re.sub(r"\w.*", lambda match: match.group(0)[0] + match.group(0)[1:].lower(), word, count=1)


def smart_title(text: str) -> str:
    """ЗАГЛАВНЫЕ из реестров банков — в обычный вид; смешанный регистр не трогаем."""
    if text != text.upper():
        return text
    return " ".join(capitalized(word) for word in text.split())


def calm_caps(text: str) -> str:
    """«EKSPOZITURA BEOGRAD 1 - Banovo brdo» → «Ekspozitura Beograd 1 - Banovo brdo»."""
    return " ".join(capitalized(word) if len(word) > 2 and word.isupper() else word for word in text.split())


def split_city(raw: str) -> tuple[str, str]:
    """«BEOGRAD (NOVI BEOGRAD)», «Novi Beograd» → («Beograd», «Novi Beograd»)."""
    text = smart_title(tidy(raw))
    match = re.fullmatch(r"(.+?)\s*\((.+)\)", text)
    city, area = (match.group(1), tidy(match.group(2))) if match else (text, "")
    if fold(city) in BELGRADE_AREAS:
        city, area = "Beograd", area or city
    if fold(city) == "beograd" and fold(area) == "beograd":
        area = ""
    return city, area


def branch(city_raw: str, name: str, address: str) -> Branch:
    city, area = split_city(city_raw)
    name = tidy(name) or area
    address = tidy(address)
    if fold(name) in {fold(address), fold(city)}:
        name = area
    return {"city": city, "name": name, "address": address}


def strip_city_tail(address: str) -> str:
    """«Jurija Gagarina 14n, 11000 Beograd» → «Jurija Gagarina 14n»."""
    text = tidy(address)
    return re.sub(r",\s*(\d{5}\s+)?[^,\d]+(,\s*Srbija)?$", "", text) if "," in text else text


def page_lines(page: str) -> list[str]:
    page = re.sub(r"<!--.*?-->", "", page, flags=re.S)
    page = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", page, flags=re.S)
    text = re.sub(r"<[^>]+>", "\n", page)
    return [tidy(line) for line in text.split("\n") if tidy(line)]


def intesa() -> list[Branch]:
    url = ("https://www.bancaintesa.rs/digitalServicesServlet/?operation=searchLocations&headers=lbsHeader"
           "&endpointName=searchLocations&locale=sr&bank=BIB&apiVersion=V2")
    body = json.dumps({"search": {"locationType": "BRANCH", "size": 1000, "start": 0}}).encode()
    data = json.loads(get(url, body, {"Content-Type": "application/json"}))
    return [branch(item["city"], "", item["name"]) for item in data["availableLocations"]]


def otp() -> list[Branch]:
    page = get("https://www.otpbanka.rs/lokacije-ekspozitura-i-bankomata/")
    markers = {m["id"]: m for m in json.loads(re.search(r"var allMarkers = (\[.*?\]);", page).group(1))}
    found = []
    for item in json.loads(re.search(r"var allLocations = (\[.*?\]);", page).group(1)):
        label = tidy(item["label"])
        if not label.startswith("Ekspozitura "):
            continue
        address = tidy(markers[item["id"]]["address"])
        city = label.removeprefix("Ekspozitura ").removesuffix(address).strip()
        city = re.sub(r"^za (fizička|pravna) lica\s+", "", city)
        found.append(branch(city, "", address))
    return found


def raiffeisen() -> list[Branch]:
    base = "https://www.raiffeisenbank.rs"
    page = get(f"{base}/sr/stanovnistvo/lokacije.html")
    path = re.search(r"'([^']*\.maps\.viewport\.json)'", page).group(1)
    data = json.loads(get(base + path))
    places = [place for location in data["locations"] for place in location["places"]]
    return [
        branch(p["address"]["city"], p["name"], p["address"]["addressLines"][0])
        for p in places if p.get("type") == "BRANCH"
    ]


def unicredit() -> list[Branch]:
    page = get("https://www.unicreditbank.rs/rs/pi.html")
    href = re.search(r'href="([^"]*Spisak%20ekspozitura[^"]*\.pdf)"', page).group(1)
    found = []
    pdf_bytes = get_bytes(urllib.parse.urljoin("https://www.unicreditbank.rs", href))
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for pdf_page in pdf.pages:
            for table in pdf_page.extract_tables():
                for row in table:
                    # Таблица отделений — та, где в третьей колонке часы работы кассы.
                    if len(row) >= 3 and row[2] and "Blagajna" in row[2] and row[0] and row[1]:
                        found.append(branch(row[0], "", smart_title(row[1].replace("\n", " "))))
    return found


def aik() -> list[Branch]:
    data = json.loads(get("https://www.aikbank.rs/data/maps-formated.json"))
    found = []
    for item in data["locations"]["data"]:
        if item.get("desc") != "Filijala":
            continue
        address = tidy(item["address"])
        # После адреса в заголовке бывает название ТЦ, а бывает объявление о ремонте — его не берём.
        rest = tidy(item["title"]).removeprefix(address).strip()
        name = rest if rest and not rest.startswith("-") and len(rest) <= 40 else ""
        found.append(branch(item["city_name"], name, address))
    return found


def nlb() -> list[Branch]:
    url = ("https://www.nlb.rs/content/nlbbanks/nlbrs/sr/poslovnice/jcr:content/root/container/container/"
           "branchsearch.facilities.json?kind=branch")
    found = []
    for item in json.loads(get(url)):
        location = item["location"]
        street = tidy(location["street"])
        name = tidy(item["name"])
        # Название вида «Ekspozitura Beograd Kneza Mihaila 38» — просто город и адрес.
        if fold(street) in fold(name):
            name = ""
        found.append(branch(location["city"], name, street))
    return found


def postanska_city(municipality: str) -> str:
    """«BEOGRAD VOŽDOVAC» → «BEOGRAD (VOŽDOVAC)», «NIŠ MEDIJANA» → «NIŠ (MEDIJANA)»; Лазаревац — город."""
    match = re.fullmatch(r"(BEOGRAD|NIŠ) (.+)", municipality)
    if not match:
        return municipality
    city, area = match.groups()
    if city == "BEOGRAD" and fold(area) not in BELGRADE_AREAS:
        return area
    return f"{city} ({area})"


def postanska() -> list[Branch]:
    data = json.loads(get("https://www.posted.co.rs/branches_atms.php?only_eks=1").strip())
    found = []
    for item in data["items"]:
        found.append(branch(
            postanska_city(to_latin(tidy(item["opstina"]))), calm_caps(to_latin(tidy(item["naziv"]))),
            smart_title(to_latin(tidy(item["adresa"]))),
        ))
    return found


def erste() -> list[Branch]:
    items = json.loads(get("https://moduli.erstebank.rs//aspx/filijale/branches.aspx"))
    return [
        branch(item["city"], item["branch_name"], item["address"])
        for item in items if item.get("branch1") and item.get("Valid") and not item.get("temporarily_closed")
    ]


def addiko() -> list[Branch]:
    url = "https://www.addiko.rs/o-nama/o-addiko-banci/ekspoziture-i-bankomati/"
    cities = re.findall(r'<option value="([^"]+)" class="map-center"', get(url))
    found = []
    for city in dict.fromkeys(cities):
        page = get(url, urllib.parse.urlencode({"sort": city}).encode())
        blocks = re.findall(
            r'<h3 class="atm-title"[^>]*><a[^>]*>([^<]*)</a></h3><p class="atm-address">'
            r'<span class="bold"> Adresa: </span>([^<]*)', page,
        )
        for title, address in blocks:
            title = tidy(title)
            if title.startswith("Ekspozitura"):
                found.append(branch(city, title.removeprefix("Ekspozitura"), strip_city_tail(address)))
    return found


def procredit() -> list[Branch]:
    page = get("https://www.procreditbank.rs/lokacije")
    data = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S).group(1))
    found = []
    for item in data["@graph"][0]["itemListElement"]["itemListElement"]:
        if "Trening" in item["name"]:
            continue
        street = tidy(item["address"]["streetAddress"])
        area, _, rest = street.rpartition(", ")
        city = item["address"]["addressLocality"]
        found.append(branch(f"{city} ({area})" if area else city, "", rest))
    return found


def halkbank() -> list[Branch]:
    page = get("https://www.halkbank.rs/kontakt/lokacije/mapa-lokacija.45.html")
    items = re.findall(
        r'<div class="location-name[^"]*">\s*<span>\s*(.*?)\s*</span>.*?'
        r'<div class="location-address">\s*(.*?)\s*</div>',
        page, re.S,
    )
    found = []
    for name, address in items:
        name = tidy(name)
        if name.startswith("ATM") or " - " not in address:
            continue
        city, _, street = tidy(address).partition(" - ")
        area = split_city(name.removeprefix("Ekspozitura "))
        found.append(branch(city, area[1] or area[0], strip_city_tail(street)))
    return found


def yettel() -> list[Branch]:
    page = get("https://www.yettelbank.rs/stanovnistvo/lokacije/yettel-bank-specijalisti/")
    found = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        raw_cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        cells = [tidy(re.sub(r"<[^>]+>", " ", cell)) for cell in raw_cells]
        if len(cells) >= 3 and cells[1]:
            found.append(branch(cells[2], cells[0], cells[1]))
    return found


def adriatic() -> list[Branch]:
    page = get("https://www.adriaticbank.rs/index.php/sr/o-adriaticbanci/lokacije")
    rows = re.findall(r"<strong[^>]*>Filijala ([^<]+)</strong><br\s*/?>([^<]+)</td>", page)
    return [branch(name, "", address) for name, address in rows]


def three_bank() -> list[Branch]:
    url = ("https://www.3bank.rs/wp-json/w2dc/v1/maps/8100/listings?directory_id=8097&directory_legacy_id=1"
           "&host_page=1014&page=1&per_page=200")
    found = []
    for item in json.loads(get(url))["items"]:
        match = re.search(r"field--address[^>]*><div[^>]*>(.*?)</div>", item["html"])
        if not match:
            continue
        parts = [tidy(part) for part in html.unescape(match.group(1)).split(",")]
        city = re.sub(r"^\d{5}\s+", "", parts[1]) if len(parts) > 1 else item["title"]
        found.append(branch(city, item["title"], parts[0]))
    return found


def api_bank() -> list[Branch]:
    lines = page_lines(get("https://www.apibank.rs/kontakt-i-lokacije/"))
    found = []
    for index, line in enumerate(lines[:-1]):
        match = re.fullmatch(r"(.+?) - ((?:filijala|centrala).*)", line, re.I)
        if match:
            found.append(branch(match.group(1), match.group(2).capitalize(), lines[index + 1]))
    return found


def mirabank() -> list[Branch]:
    lines = page_lines(get("https://www.mirabankserbia.com/rs/kontakt"))
    start = lines.index("Adresa")
    street, city = lines[start + 2], re.sub(r"^\d{5}\s+", "", lines[start + 3])
    return [branch(city, "Sedište banke", street)]


def bank_of_china() -> list[Branch]:
    lines = page_lines(get("https://www.bankofchina.com/rs/rs/index.html"))
    line = next(line for line in lines if re.search(r", \d{5} [^,]+, Srbija$", line))
    street, city, _ = [tidy(part) for part in line.split(",")]
    return [branch(re.sub(r"^\d{5}\s+", "", city), "Sedište banke", street)]


def srpska() -> list[Branch]:
    page = get("https://www.srpskabanka.rs/kontakt/poslovne-jedinice.html")
    page = re.sub(r"<!--.*?-->", "", page, flags=re.S)
    found = []
    for title, address in re.findall(r"<strong>\s*(Експозитура[^<]*)</strong>\s*<br>\s*([^<]+)<br>", page):
        city, area = split_city(to_latin(tidy(title)).removeprefix("Ekspozitura "))
        found.append(branch(f"{city} ({area})" if area else city, "", to_latin(address)))
    return found


# Код банка из формы → (страница-источник для людей, сборщик).
SOURCES: dict[str, tuple[str, Callable[[], list[Branch]]]] = {
    "intesa": ("https://www.bancaintesa.rs/stanovnistvo/lokacije-ekspozitura-i-bankomata.html", intesa),
    "otp": ("https://www.otpbanka.rs/lokacije-ekspozitura-i-bankomata/", otp),
    "raiffeisen": ("https://www.raiffeisenbank.rs/sr/stanovnistvo/lokacije.html", raiffeisen),
    "unicredit": ("https://www.unicreditbank.rs/rs/pi.html (PDF «Spisak ekspozitura»)", unicredit),
    "aik": ("https://www.aikbank.rs/lokacije/", aik),
    "nlb": ("https://www.nlb.rs/poslovnice", nlb),
    "postanska": ("https://www.posted.co.rs/o-nama/ekspoziture.html", postanska),
    "erste": ("https://www.erstebank.rs/sr/filijale-i-bankomati", erste),
    "addiko": ("https://www.addiko.rs/o-nama/o-addiko-banci/ekspoziture-i-bankomati/", addiko),
    "procredit": ("https://www.procreditbank.rs/lokacije", procredit),
    "halkbank": ("https://www.halkbank.rs/kontakt/lokacije/mapa-lokacija.45.html", halkbank),
    "yettel": ("https://www.yettelbank.rs/stanovnistvo/lokacije/yettel-bank-specijalisti/", yettel),
    "adriatic": ("https://www.adriaticbank.rs/index.php/sr/o-adriaticbanci/lokacije", adriatic),
    "3banka": ("https://www.3bank.rs/filijale/", three_bank),
    "api": ("https://www.apibank.rs/kontakt-i-lokacije/", api_bank),
    "mirabank": ("https://www.mirabankserbia.com/rs/kontakt", mirabank),
    "bankofchina": ("https://www.bankofchina.com/rs/rs/index.html", bank_of_china),
    "srpska": ("https://www.srpskabanka.rs/kontakt/poslovne-jedinice.html", srpska),
}


def unique(branches: list[Branch]) -> list[Branch]:
    seen: dict[tuple[str, str], Branch] = {}
    for item in branches:
        if item["city"] and item["address"]:
            seen.setdefault((fold(item["city"]), fold(item["address"])), item)
    return sorted(seen.values(), key=lambda b: (fold(b["city"]), fold(b["name"]), fold(b["address"])))


def collect(code: str, previous: dict, today: str) -> dict:
    source, fetch = SOURCES[code]
    try:
        branches = unique(fetch())
        if not branches:
            raise ValueError("пустой список")
        return {"source": source, "collected_at": today, "status": "ok", "branches": branches}
    except Exception as error:  # noqa: BLE001 — любой сбой сайта банка не должен ронять сборку остальных
        print(f"{code}: {error!r}", file=sys.stderr)
        if previous.get("branches"):
            return previous
        return {"source": source, "collected_at": today, "status": "unavailable", "note": str(error)[:200],
                "branches": []}


def main() -> None:
    old = json.loads(OUT.read_text(encoding="utf-8"))["banks"] if OUT.exists() else {}
    today = date.today().isoformat()
    banks = {code: collect(code, old.get(code, {}), today) for code in sys.argv[1:] or SOURCES}
    merged = {**old, **banks}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {"generated_at": today, "banks": {code: merged[code] for code in SOURCES if code in merged}}
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for code, entry in payload["banks"].items():
        print(f"{code:12} {entry['status']:12} {len(entry['branches']):4}  {entry['collected_at']}")


if __name__ == "__main__":
    main()

"""Пересчёт цифр блока «Что было видно по отчётности» (ALTA banka).

Скачивает балансы и отчёты о прибылях всех 19 банков Сербии с публичного сайта
NBS, заново считает каждое число блока и пишет signals.csv. Цифры, которых нет
в формах NBS (примечания годового отчёта, раскрытие за I полугодие 2026,
протоколы собраний), вписаны константами со ссылкой на страницу PDF.

Запуск: python3 signals.py [--cache nbs-csv] [--out signals.csv]
Нужен только Python 3.10+, без сторонних пакетов.
"""

import argparse
import csv
import io
import sys
import time
import urllib.request
from pathlib import Path

NBS = "https://webappcenter.nbs.rs/WebApp/FinInstBank"
FORMS = {"bs": "BankFinancialBalanceSheet", "is": "BankFinancialIncomeStatement"}

ALTA = "7074433"
TOP5 = {
    "Intesa": "7759231",
    "OTP": "8603537",
    "Raiffeisen": "17335600",
    "UniCredit": "17324918",
    "NLB": "7737068",
}
OTHERS = {
    "Yettel": "17138669",
    "ProCredit": "17335677",
    "API": "20439866",
    "Mirabank": "21080608",
    "Bank of China": "21251640",
    "AikBank": "6876366",
    "Poštanska": "7004893",
    "Srpska": "7092288",
    "Adriatic": "7534183",
    "Halkbank": "7601093",
    "Addiko": "7726716",
    "Erste": "8063818",
    "3 Banka": "8761132",
}
SIX = {"ALTA": ALTA, **TOP5}
ALL = {**SIX, **OTHERS}

ANNUAL = "https://altabanka.rs/static/uploads/2026/04/Alta-banka_Izvestaj-revizora_2025_Final-potpisan.pdf"
H1_DISCLOSURE = "https://altabanka.rs/static/uploads/2026/09/Objavljivanje-podataka-i-informacija_01.01.2026.-30.06.2026.pdf"
BS_0930 = "https://altabanka.rs/static/uploads/2026/10/Nerevidirani-bilans-stanja-30.09.2026.pdf"
ASSEMBLY = "https://altabanka.rs/skupstina/"
ASSEMBLY_2025 = "https://altabanka.rs/static/uploads/2025/04/Zapisnik-sa-redovne-sednice-Skupstine_25_04_2025.pdf"
N1_VICEGOV = "https://n1info.rs/biznis/viceguverneri-nbs-traze-da-tuzilastvo-reaguje-zbog-alta-banke"

FIELDS = ["signal", "bank", "metric", "period", "value", "unit", "formula", "source"]


def url(form: str, code: str, date: str) -> str:
    return f"{NBS}/{FORMS[form]}/Download?NationalCode={code}&Date={date}.%2000:00:00&Format=csv"


def parse(text: str) -> dict[str, int]:
    lines = {}
    for row in list(csv.reader(io.StringIO(text)))[1:]:
        if len(row) >= 5:
            lines[row[2].strip()] = int(row[-1])
    return lines


def fetch(form: str, code: str, date: str, cache: Path) -> dict[str, int]:
    path = cache / f"{form}-{code}-{date}.csv"
    if not path.exists():
        with urllib.request.urlopen(url(form, code, date), timeout=60) as resp:
            path.write_bytes(resp.read())
        time.sleep(0.3)
    return parse(path.read_text(encoding="utf-8"))


class Data:
    def __init__(self, cache: Path):
        self.cache = cache

    def bs(self, code: str, date: str) -> dict[str, int]:
        return fetch("bs", code, date, self.cache)

    def inc(self, code: str, date: str) -> dict[str, int]:
        return fetch("is", code, date, self.cache)


def net(lines: dict[str, int], pos: str, neg: str) -> int:
    return lines.get(pos, 0) - lines.get(neg, 0)


def growth(d: Data, code: str, line: str, start: str, end: str) -> float:
    return (d.bs(code, end)[line] / d.bs(code, start)[line] - 1) * 100


def roa(d: Data, code: str) -> float:
    profit = net(d.inc(code, "31.12.2025"), "XXI.1", "XXI.2")
    return profit / ((d.bs(code, "31.12.2025")["A"] + d.bs(code, "31.12.2024")["A"]) / 2) * 100


def roe(d: Data, code: str) -> float:
    profit = net(d.inc(code, "31.12.2025"), "XXI.1", "XXI.2")
    return profit / ((d.bs(code, "31.12.2025")["PK.XX"] + d.bs(code, "31.12.2024")["PK.XX"]) / 2) * 100


def nim(d: Data, code: str, year: int) -> float:
    nii = net(d.inc(code, f"31.12.{year}"), "I.1", "I.2")
    avg = (d.bs(code, f"31.12.{year}")["A"] + d.bs(code, f"31.12.{year - 1}")["A"]) / 2
    return nii / avg * 100


def rank(values: dict[str, float], name: str) -> int:
    return sorted(values, key=values.get).index(name) + 1


def row(signal: str, bank: str, metric: str, period: str, value: float | int | str,
        unit: str, formula: str, *sources: str) -> dict[str, str]:
    shown = f"{value:.2f}" if isinstance(value, float) else str(value)
    return dict(signal=signal, bank=bank, metric=metric, period=period, value=shown,
                unit=unit, formula=formula, source=" ; ".join(sources))


def signal1_2(d: Data) -> list[dict[str, str]]:
    out = []
    for name, code in SIX.items():
        b = d.bs(code, "30.6.2026")
        src = url("bs", code, "30.6.2026")
        out.append(row("1", name, "Кредиты клиентам ÷ вклады клиентов", "30.06.2026",
                       b["A.VI"] / b["PO.III"] * 100, "%", "баланс A.VI / PO.III", src))
        out.append(row("2", name, "Касса и средства в NBS ÷ все активы", "30.06.2026",
                       b["A.I"] / b["A"] * 100, "%", "баланс A.I / A", src))
    return out


def signal3(d: Data) -> list[dict[str, str]]:
    roas = {n: roa(d, c) for n, c in ALL.items()}
    profitable = {n: v for n, v in roas.items() if v > 0}
    out = []
    for name, code in SIX.items():
        srcs = (url("is", code, "31.12.2025"), url("bs", code, "31.12.2025"), url("bs", code, "31.12.2024"))
        out.append(row("3", name, "Доходность на активы (ROA)", "2025", roas[name], "%",
                       "XXI.1−XXI.2 (2025) / среднее A на 31.12.2024 и 31.12.2025", *srcs))
        out.append(row("3", name, "Доходность на капитал (ROE)", "2025", roe(d, code), "%",
                       "XXI.1−XXI.2 (2025) / среднее PK.XX на 31.12.2024 и 31.12.2025", *srcs))
    out.append(row("3", "ALTA", "Место по ROA среди прибыльных банков, снизу", "2025",
                   f"{rank(profitable, 'ALTA')} из {len(profitable)}", "место",
                   "ROA всех 19 банков; убыточные (Yettel, Mirabank) исключены",
                   f"{NBS}/BankFinancialIncomeStatement/Index"))
    profit = sum(net(d.inc(c, "31.12.2025"), "XXI.1", "XXI.2") for c in ALL.values())
    assets = sum((d.bs(c, "31.12.2025")["A"] + d.bs(c, "31.12.2024")["A"]) / 2 for c in ALL.values())
    out.append(row("3", "все 19 банков", "Доходность на активы (ROA), вместе", "2025",
                   profit / assets * 100, "%", "сумма XXI.1−XXI.2 / сумма средних A",
                   f"{NBS}/BankFinancialIncomeStatement/Index"))
    return out


def signal4(d: Data) -> list[dict[str, str]]:
    out = []
    for year in (2023, 2024, 2025, 2026):
        lines = d.inc(ALTA, f"30.6.{year}")
        out.append(row("4", "ALTA", "Прибыль до налога", f"I пол. {year}",
                       net(lines, "XVI.1", "XVI.2"), "тыс. RSD", "отчёт о прибыли XVI.1−XVI.2",
                       url("is", ALTA, f"30.6.{year}")))
    for date, period in (("31.12.2023", "2023"), ("31.12.2024", "2024"),
                         ("31.12.2025", "2025"), ("30.6.2026", "I пол. 2026")):
        out.append(row("4", "ALTA", "Прочие расходы", period, d.inc(ALTA, date)["XV.2"],
                       "тыс. RSD", "отчёт о прибыли XV.2 «Остали расходи»", url("is", ALTA, date)))
    a_dec = d.bs(ALTA, "31.12.2025")["A"]
    a_sep = 231_497_192  # неаудированный баланс банка на 30.09.2026, строка АОП 0018
    out.append(row("4", "ALTA", "Рост активов", "31.12.2025 → 30.09.2026",
                   (a_sep / a_dec - 1) * 100, "%", "A 30.09.2026 (баланс банка) / A 31.12.2025 (NBS) − 1",
                   BS_0930, url("bs", ALTA, "31.12.2025")))
    note15 = "прим. 15 «Ostali rashodi»: APR-пояснения с. 78 / отчёт банка с. 89"
    for metric, value in (("Спонсорство, гуманитарная помощь и пожертвования", 233_111),
                          ("Маркетинг", 208_979),
                          ("Прочие нематериальные расходы", 819_611),
                          ("Косвенные налоги и взносы", 325_440),
                          ("Услуги подрядчиков (proizvodne usluge)", 624_248)):
        out.append(row("4", "ALTA", f"Прочие расходы: {metric}", "2025", value, "тыс. RSD", note15, ANNUAL))
    return out


def signal5(d: Data) -> list[dict[str, str]]:
    out = []
    for date, period in (("31.12.2024", "2024"), ("31.12.2025", "2025"), ("30.6.2026", "I пол. 2026")):
        lines = d.inc(ALTA, date)
        src = url("is", ALTA, date)
        out.append(row("5", "ALTA", "Чистый комиссионный доход", period, net(lines, "II.1", "II.2"),
                       "тыс. RSD", "отчёт о прибыли II.1−II.2", src))
        out.append(row("5", "ALTA", "Чистый процентный доход", period, net(lines, "I.1", "I.2"),
                       "тыс. RSD", "отчёт о прибыли I.1−I.2", src))
    for name, code in SIX.items():
        lines = d.inc(code, "31.12.2025")
        out.append(row("5", name, "Комиссии ÷ проценты", "2025",
                       net(lines, "II.1", "II.2") / net(lines, "I.1", "I.2") * 100, "%",
                       "(II.1−II.2) / (I.1−I.2)", url("is", code, "31.12.2025")))
    note7 = "прим. 7: APR-пояснения с. 73 / отчёт банка с. 84"
    out.append(row("5", "ALTA", "Комиссии за обмен валют, брутто", "2025", 2_692_300, "тыс. RSD", note7, ANNUAL))
    out.append(row("5", "ALTA", "Все комиссионные доходы, брутто", "2025", 4_383_818, "тыс. RSD", note7, ANNUAL))
    out.append(row("5", "ALTA", "Комиссии за платёжные услуги (кроме населения)", "2025", 433_005,
                   "тыс. RSD", note7, ANNUAL))
    return out


def signal6(d: Data) -> list[dict[str, str]]:
    out = []
    periods = (("31.12.2023", "31.12.2024", "2024"), ("31.12.2024", "31.12.2025", "2025"),
               ("31.12.2025", "30.6.2026", "I пол. 2026"))
    lines = (("A.VI", "Рост кредитов клиентам"), ("PO.III", "Рост вкладов клиентов"), ("A", "Рост активов"))
    for start, end, period in periods:
        for line, metric in lines:
            out.append(row("6", "ALTA", metric, period, growth(d, ALTA, line, start, end), "%",
                           f"баланс {line} на {end} / на {start} − 1",
                           url("bs", ALTA, start), url("bs", ALTA, end)))
    out.append(row("6", "ALTA", "Кредиты клиентам: во сколько раз", "31.12.2023 → 31.12.2025",
                   d.bs(ALTA, "31.12.2025")["A.VI"] / d.bs(ALTA, "31.12.2023")["A.VI"], "раз",
                   "A.VI 31.12.2025 / A.VI 31.12.2023",
                   url("bs", ALTA, "31.12.2023"), url("bs", ALTA, "31.12.2025")))
    for name, code in {**TOP5, "AikBank": OTHERS["AikBank"], "Mirabank": OTHERS["Mirabank"],
                       "Poštanska": OTHERS["Poštanska"]}.items():
        for line, metric in lines[:2]:
            out.append(row("6", name, metric, "2025", growth(d, code, line, "31.12.2024", "31.12.2025"), "%",
                           f"баланс {line} на 31.12.2025 / на 31.12.2024 − 1",
                           url("bs", code, "31.12.2024"), url("bs", code, "31.12.2025")))
    return out


def signal7(d: Data) -> list[dict[str, str]]:
    note32 = "прим. 32 «Odnosi sa povezanim licima», брутто: APR-пояснения с. 102 / отчёт банка с. 113"
    gross = {"акционерам": 2_262_611, "руководству": 127_343, "прочим связанным": 8_628_541}
    total_2025 = sum(gross.values())
    total_2024 = 1_436_725 + 120_815 + 4_903_700
    b = d.bs(ALTA, "31.12.2025")
    out = [row("7", "ALTA", f"Кредиты {who}", "31.12.2025", v, "тыс. RSD", note32, ANNUAL)
           for who, v in gross.items()]
    out += [
        row("7", "ALTA", "Кредиты связанным лицам, всего", "31.12.2025", total_2025, "тыс. RSD",
            "сумма трёх строк " + note32, ANNUAL),
        row("7", "ALTA", "Кредиты связанным лицам, всего", "31.12.2024", total_2024, "тыс. RSD",
            "сумма трёх строк " + note32, ANNUAL),
        row("7", "ALTA", "Рост кредитов связанным лицам", "2025", (total_2025 / total_2024 - 1) * 100, "%",
            "всего 2025 / всего 2024 − 1", ANNUAL),
        row("7", "ALTA", "Кредиты связанным ÷ собственный капитал", "31.12.2025",
            total_2025 / b["PK.XX"] * 100, "%", "прим. 32 / баланс PK.XX", ANNUAL, url("bs", ALTA, "31.12.2025")),
        row("7", "ALTA", "Кредиты связанным ÷ все кредиты клиентам", "31.12.2025",
            total_2025 / b["A.VI"] * 100, "%", "прим. 32 / баланс A.VI", ANNUAL, url("bs", ALTA, "31.12.2025")),
    ]
    return out


def signal8(d: Data) -> list[dict[str, str]]:
    out = []
    for year in (2024, 2025):
        nims = {n: nim(d, c, year) for n, c in ALL.items()}
        for name in SIX:
            code = SIX[name]
            out.append(row("8", name, "Процентная маржа (NIM)", str(year), nims[name], "%",
                           f"(I.1−I.2) за {year} / среднее A на 31.12.{year - 1} и 31.12.{year}",
                           url("is", code, f"31.12.{year}"), url("bs", code, f"31.12.{year - 1}"),
                           url("bs", code, f"31.12.{year}")))
        out.append(row("8", "ALTA", "Место по марже снизу", str(year), f"{rank(nims, 'ALTA')} из {len(nims)}",
                       "место", "NIM всех 19 банков", f"{NBS}/BankFinancialIncomeStatement/Index"))
    ie23, ie25 = d.inc(ALTA, "31.12.2023")["I.b"], d.inc(ALTA, "31.12.2025")["I.b"]
    out.append(row("8", "ALTA", "Процентные расходы: во сколько раз", "2023 → 2025", ie25 / ie23, "раз",
                   "I.b 2025 / I.b 2023", url("is", ALTA, "31.12.2023"), url("is", ALTA, "31.12.2025")))
    shares = {n: d.inc(c, "31.12.2025")["I.b"] / d.inc(c, "31.12.2025")["I.a"] * 100 for n, c in ALL.items()}
    out.append(row("8", "ALTA", "Процентные расходы ÷ процентные доходы", "2025", shares["ALTA"], "%",
                   "I.b / I.a", url("is", ALTA, "31.12.2025")))
    out.append(row("8", "ALTA", "Место по этой доле сверху", "2025",
                   f"{len(shares) - rank(shares, 'ALTA') + 1} из {len(shares)}", "место",
                   "I.b / I.a всех 19 банков", f"{NBS}/BankFinancialIncomeStatement/Index"))
    return out


def signal9(d: Data) -> list[dict[str, str]]:
    dates = ("30.6.2025", "30.9.2025", "31.12.2025", "31.3.2026", "30.6.2026")
    capital = {x: d.bs(ALTA, x)["PK.XIV"] for x in dates}
    out = []
    for prev, cur in zip(dates, dates[1:]):
        out.append(row("9", "ALTA", "Прирост акционерного капитала", f"{prev} → {cur}",
                       capital[cur] - capital[prev], "тыс. RSD", "баланс PK.XIV, разница",
                       url("bs", ALTA, prev), url("bs", ALTA, cur), ASSEMBLY))
    out.append(row("9", "ALTA", "Взносы владельца, всего (4 эмиссии)", "30.06.2025 → 30.06.2026",
                   capital["30.6.2026"] - capital["30.6.2025"], "тыс. RSD", "PK.XIV 30.06.2026 − PK.XIV 30.06.2025",
                   url("bs", ALTA, "30.6.2025"), url("bs", ALTA, "30.6.2026"), ASSEMBLY))
    eq = d.bs(ALTA, "30.6.2026")["PK.XX"] - d.bs(ALTA, "31.12.2024")["PK.XX"]
    out.append(row("9", "ALTA", "Рост всего капитала", "31.12.2024 → 30.06.2026", eq, "тыс. RSD",
                   "PK.XX 30.06.2026 − PK.XX 31.12.2024",
                   url("bs", ALTA, "31.12.2024"), url("bs", ALTA, "30.6.2026")))
    out.append(row("9", "ALTA", "Чистая прибыль", "2025", net(d.inc(ALTA, "31.12.2025"), "XXI.1", "XXI.2"),
                   "тыс. RSD", "отчёт о прибыли XXI.1−XXI.2", url("is", ALTA, "31.12.2025")))
    note41 = "прим. 41: APR-пояснения с. 129 / отчёт банка с. 140"
    out += [
        row("9", "ALTA", "Достаточность капитала", "31.12.2024", 19.73, "%", note41, ANNUAL),
        row("9", "ALTA", "Достаточность капитала", "31.12.2025", 18.15, "%", note41, ANNUAL),
        row("9", "ALTA", "Минимум достаточности для ALTA (с надбавками)", "31.12.2025", 15.80, "%", note41, ANNUAL),
        row("9", "ALTA", "Запас над минимумом", "31.12.2025", round(18.15 - 15.80, 2), "п.п.", "18,15 − 15,80", ANNUAL),
        row("9", "ALTA", "Надбавка NBS по итогам надзора (SREP)", "2025", round(12.20 - 8.0, 2), "п.п.",
            "12,20 % (общий капитал с SREP) − 8 % (закон); прим. 5.10: APR-пояснения с. 69 / отчёт банка с. 80", ANNUAL),
        row("9", "ALTA", "Достаточность капитала", "30.06.2026", 17.92, "%",
            "раскрытие за I пол. 2026, раздел 3, PDF с. 5", H1_DISCLOSURE),
        row("9", "ALTA", "Комбинированный буфер капитала", "30.06.2026", 3.42, "%",
            "раскрытие за I пол. 2026, раздел 3, PDF с. 5", H1_DISCLOSURE),
        row("9", "ALTA", "Гарантии исполнения (činidbene), брутто", "31.12.2025", 42_379_191, "тыс. RSD",
            "прим. 33а: APR-пояснения с. 103 / отчёт банка с. 114", ANNUAL),
        row("9", "ALTA", "Гарантии исполнения ÷ собственный капитал", "31.12.2025",
            42_379_191 / d.bs(ALTA, "31.12.2025")["PK.XX"] * 100, "%", "прим. 33а / баланс PK.XX",
            ANNUAL, url("bs", ALTA, "31.12.2025")),
    ]
    return out


def summary() -> list[dict[str, str]]:
    return [
        row("итого", "ALTA", "Отчётность за 2024 утверждена собранием → отзыв лицензии", "25.04.2025 → 30.10.2026",
            "18", "месяцев", "протокол годового собрания 25.04.2025, п. 1 повестки; сообщение NBS", ASSEMBLY_2025),
        row("итого", "ALTA", "Годовой отчёт 2025 выложен банком → отзыв лицензии", "апрель 2026 → 30.10.2026",
            "6–7", "месяцев", "папка выкладки uploads/2026/04 в адресе отчёта; сообщение NBS", ANNUAL),
        row("итого", "NBS", "Вице-губернаторы: положение «резко расходилось» с отчётами", "31.10.2026",
            "цитата", "", "пересказ N1", N1_VICEGOV),
    ]


def build(d: Data) -> list[dict[str, str]]:
    return (signal1_2(d) + signal3(d) + signal4(d) + signal5(d) + signal6(d)
            + signal7(d) + signal8(d) + signal9(d) + summary())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cache", default="nbs-csv", help="куда складывать CSV NBS")
    parser.add_argument("--out", default="signals.csv")
    args = parser.parse_args()
    cache = Path(args.cache)
    cache.mkdir(parents=True, exist_ok=True)
    rows = build(Data(cache))
    with open(args.out, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)} строк → {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()

import pytest

from alta_feedback.nbs import Bank, Figure, Snapshot, number, parse_snapshot, snapshot

BALANCE = "https://webappcenter.nbs.rs/WebApp/FinInstBank/BankFinancialBalanceSheet/IndexArchive?NationalCode=1"


def raw_bank(code: str = "unicredit", rank: int = 1, **figures) -> dict:
    return {
        "code": code, "name": code.title(), "rank": rank, "aliases": [code],
        "figures": figures or {"share": {"value": 10.7, "source_url": BALANCE}},
    }


def snap(*banks: dict) -> Snapshot:
    return parse_snapshot({"as_of": "2026-06-30", "bank_count": len(banks), "banks": list(banks)})


def test_figure_without_source_is_not_shown():
    bank = snap(raw_bank(share={"value": 10.7, "source_url": ""})).banks[0]
    assert bank.rows == []


def test_figure_with_non_https_source_is_not_shown():
    bank = snap(raw_bank(assets={"value": 780.0, "source_url": "javascript:alert(1)"})).banks[0]
    assert bank.size is None


def test_figure_with_source_is_shown_with_its_link():
    bank = snap(raw_bank()).banks[0]
    assert [(row.label, row.text, row.source_url) for row in bank.rows] == [("Доля рынка", "10,7 %", BALANCE)]


@pytest.mark.parametrize(
    ("name", "code"),
    [("UniCredit", "unicredit"), ("OTP banka", "otp"), ("Poštanska štedionica", "postanska"),
     ("Yettel Bank", "yettel"), ("Raiffeisen", "raiffeisen"), ("raiffeisen banka srbija", "raiffeisen"),
     ("Banka Intesa Beograd", "intesa"), ("Уникредит", "unicredit")],
)
def test_bank_from_form_is_matched_to_nbs(name, code):
    assert snapshot().find(name).code == code


def test_unknown_bank_has_no_nbs_figures():
    assert snapshot().find("Мой банк") is None


def test_failed_bank_is_never_offered_for_an_account():
    assert snapshot().find("ALTA") is None


def test_every_bank_on_the_form_has_all_figures_with_sources():
    from alta_feedback.accounts import BANKS

    missing = [label for label in BANKS.values() if len(snapshot().find(label).rows) != 5]
    assert missing == []


def test_top_is_sorted_by_size():
    assert [bank.rank for bank in snapshot().top()] == list(range(1, 11))


def test_numbers_are_written_the_russian_way():
    assert (number(1118.6, 1), number(-0.21, 2)) == ("1 118,6", "−0,21")


def test_figure_keeps_extra_sources():
    bank = Bank("x", "X", 1, (), {"roa": Figure(2.86, BALANCE, ("https://a", "https://b"))})
    assert bank.rows[0].also == ("https://a", "https://b")


def test_listing_puts_reported_banks_first_without_repeats():
    reported, others = snapshot().listing(["Yettel Bank", "UniCredit", "Уникредит", "Мой банк"])
    assert ([b.code for b in reported], [b.code for b in others][:4]) == (
        ["yettel", "unicredit"], ["intesa", "otp", "raiffeisen", "nlb"])


def test_share_is_in_the_summary_not_in_details():
    bank = snapshot().find("UniCredit")
    assert (bank.share.label, [row.label for row in bank.details]) == (
        "Доля рынка", ["Капитал к активам", "Деньги под рукой", "Кредиты к вкладам", "Прибыльность (ROA)"])

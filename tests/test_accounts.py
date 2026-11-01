from datetime import date

import pytest

from alta_feedback.accounts import parse_account_form, scrub_pii

TODAY = date(2026, 11, 1)
FORM = {
    "bank": "intesa", "city": "beograd", "account_type": "personal",
    "result": "opened", "visit_date": "2026-10-31",
}


def parse(docs: list[str] | None = None, **fields):
    return parse_account_form({**FORM, **fields}, docs or [], TODAY)


@pytest.mark.parametrize(
    "secret",
    [
        "0101990710006",  # JMBG
        "160-0000000123456-78",  # счёт 3-13-2
        "160000000012345678",  # счёт 18 цифр подряд
        "RS35 1600 0000 0012 3456 78",  # IBAN
        "+381 63 123 4567",
        "063/123-4567",
        "75 1234567",  # загранпаспорт
        "ivan.testov@example.com",
    ],
)
def test_scrub_hides_personal_numbers(secret):
    assert secret not in scrub_pii(f"мой номер {secret}, спасибо")


def test_scrub_keeps_ordinary_text_and_dates():
    text = "Просили паспорт и боравак, ждал 2 недели, визит 08.10.2026, сумма 500 000 динар"
    assert scrub_pii(text) == text


def test_minimal_form_is_accepted():
    _, errors = parse()
    assert errors == []


def test_bank_code_becomes_bank_name():
    report, _ = parse()
    assert report.bank == "Banca Intesa"


def test_bank_label_typed_in_any_case_becomes_bank_name():
    report, _ = parse(bank="  otp BANKA ")
    assert report.bank == "OTP banka"


def test_own_bank_text_is_kept():
    report, _ = parse(bank="  Nova   banka ")
    assert report.bank == "Nova banka"


def test_own_city_is_scrubbed():
    report, _ = parse(city="Zrenjanin 0631234567")
    assert "0631234567" not in report.city


def test_empty_bank_is_rejected():
    _, errors = parse(bank=" ")
    assert errors


@pytest.mark.parametrize("field", ["account_type", "result"])
def test_required_choice_must_be_known(field):
    _, errors = parse(**{field: "whatever"})
    assert errors


@pytest.mark.parametrize("visit", ["2026-11-05", "2024-01-01", "вчера"])
def test_future_old_or_garbage_visit_date_is_rejected(visit):
    _, errors = parse(visit_date=visit)
    assert errors


def test_document_labels_become_codes_and_own_text_is_kept():
    report, _ = parse(docs=["Паспорт", "apr", "Справка из налоговой"])
    assert report.documents == ("passport", "apr", "Справка из налоговой")


def test_documents_drop_blanks_and_repeats():
    report, _ = parse(docs=["Паспорт", " ", "passport", "паспорт"])
    assert report.documents == ("passport",)


def test_own_document_text_is_scrubbed():
    report, _ = parse(docs=["выписка по счёту 160-0000000123456-78"])
    assert "0000000123456" not in report.documents[0]


def test_residency_label_becomes_code():
    report, _ = parse(residency="Только белый картон")
    assert report.residency == "white_card"


def test_own_residency_text_is_kept():
    report, _ = parse(residency="Виза D")
    assert report.residency == "Виза D"


def test_empty_residency_stays_empty():
    report, _ = parse(residency="")
    assert report.residency == ""


def test_comment_is_scrubbed():
    report, _ = parse(comment="JMBG 0101990710006 не спрашивали")
    assert "0101990710006" not in report.comment

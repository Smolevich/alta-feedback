from alta_feedback.stats import (
    AnswerFilter,
    account_stats,
    answer_page,
    parse_cursor,
    parse_filter,
    shown_before,
)


def item(bank: str = "OTP banka", result: str = "opened", **fields) -> dict:
    return {
        "id": 1, "visit_date": "2026-10-31", "bank": bank, "city": "Белград", "account_type": "personal",
        "result": result, "residency": "boravak", "documents": ["passport"], "comment": "", **fields,
    }


def test_banks_are_sorted_by_number_of_answers():
    stats = account_stats([item("Erste"), item("OTP banka"), item("OTP banka", "refused")])
    assert [tally.name for tally in stats.banks] == ["OTP banka", "Erste"]


def test_bank_tally_splits_results():
    stats = account_stats([item(), item(result="refused"), item(result="refused")])
    assert (stats.banks[0].results["opened"], stats.banks[0].results["refused"]) == (1, 2)


def test_bank_tally_splits_account_types():
    stats = account_stats([item(), item(account_type="entrepreneur")])
    assert stats.banks[0].types["entrepreneur"] == 1


def test_residency_codes_become_words():
    stats = account_stats([item(residency="white_card")])
    assert stats.residencies[0].name == "Только белый картон"


def test_missing_residency_is_named():
    stats = account_stats([item(residency="")])
    assert stats.residencies[0].name == "Не указан"


def test_documents_are_counted_with_share_of_answers():
    stats = account_stats([item(documents=["passport", "apr"]), item(documents=["passport"])])
    assert [(doc.name, doc.count, doc.percent) for doc in stats.documents] == [
        ("Паспорт", 2, 100), ("PIB и решение APR (ИП)", 1, 50),
    ]


def test_own_document_text_is_kept_as_is():
    stats = account_stats([item(documents=["Справка из налоговой"])])
    assert stats.documents[0].name == "Справка из налоговой"


def test_answer_page_cuts_to_size_and_points_at_last_shown():
    rows = [item(id=n, visit_date="2026-10-31") for n in range(25, 4, -1)]
    page = answer_page(rows, 20)
    assert (len(page.items), page.next_cursor) == (20, "2026-10-31_6")


def test_last_answer_page_has_no_next_cursor():
    assert answer_page([item(id=2), item(id=1)], 20).next_cursor is None


def test_cursor_round_trips():
    assert parse_cursor("2026-10-31_17") == ("2026-10-31", 17)


def test_broken_cursor_means_first_page():
    broken = ["", "abc", "2026-10-31", "2026-13-01_5", "2026-10-31_x", "20261031_5", "2026-10-31_-1"]
    assert [parse_cursor(raw) for raw in broken] == [None] * len(broken)


def test_filter_keeps_only_known_values():
    params = {"bank": "otp", "city": "Атлантида", "result": "maybe", "from": "2026-10-01", "to": "вчера"}
    assert parse_filter(params) == AnswerFilter(bank="otp", date_from="2026-10-01")


def test_filter_matches_database_names_not_codes():
    assert AnswerFilter(bank="otp", city="novisad", result="opened").equals() == {
        "bank": "OTP banka", "city": "Нови-Сад", "result": "opened",
    }


def test_empty_filter_is_inactive():
    assert not parse_filter({"bank": "nope", "from": ""}).active


def test_shown_before_counts_answers_up_to_cursor():
    items = [item(id=3), item(id=2), item(id=9, visit_date="2026-10-01")]
    assert shown_before(items, ("2026-10-31", 2)) == 2

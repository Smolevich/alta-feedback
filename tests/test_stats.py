from alta_feedback.stats import account_stats


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


def test_recent_is_capped_at_twenty():
    assert len(account_stats([item()] * 25).recent) == 20

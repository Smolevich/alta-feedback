import sqlite3
from collections import Counter
from datetime import date

from alta_feedback.accounts import BANKS, parse_account_form
from alta_feedback.branches import (
    BRANCH_MAX,
    NOT_SURE,
    Branch,
    branch_options,
    city_key,
    directory,
    fold,
)
from alta_feedback.stats import OTHER_BRANCHES, account_stats, answer_cards, hide_rare_branches
from alta_feedback.store import Store

TODAY = date(2026, 11, 1)
FORM = {
    "bank": "raiffeisen", "city": "beograd", "account_type": "personal",
    "result": "opened", "visit_date": "2026-10-31",
}
DIRECTORY = {
    "raiffeisen": (
        Branch("Beograd", "Ušće", "Bulevar Mihaila Pupina 4"),
        Branch("Beograd", "", "Resavska 1"),
        Branch("Novi Sad", "", "Pozorišni trg 3"),
    ),
}


def parse_branch(raw: str, bank: str = "raiffeisen") -> str | None:
    report, _ = parse_account_form({**FORM, "bank": bank, "branch": raw}, [], TODAY, DIRECTORY)
    return report.branch


def item(branch: str | None, bank: str = "Raiffeisen", result: str = "opened") -> dict:
    return {
        "id": 1, "visit_date": "2026-10-31", "bank": bank, "city": "Белград", "branch": branch,
        "account_type": "personal", "result": result, "residency": "", "documents": [], "comment": "",
    }


def test_report_without_branch_has_none():
    assert parse_branch("") is None


def test_not_sure_choice_is_stored_as_none():
    assert parse_branch(NOT_SURE) is None


def test_branch_from_list_is_stored_as_directory_label():
    assert parse_branch("ušće — bulevar mihaila pupina 4") == "Ušće — Bulevar Mihaila Pupina 4"


def test_own_branch_text_is_kept():
    assert parse_branch("Отделение у Славии") == "Отделение у Славии"


def test_own_branch_text_is_scrubbed_of_phone():
    assert "4567" not in parse_branch("Отделение, менеджер +381 63 123 4567")


def test_own_branch_text_is_cut_to_limit():
    assert len(parse_branch("я" * 500)) == BRANCH_MAX


def test_label_of_other_bank_is_free_text():
    label = "Ušće — Bulevar Mihaila Pupina 4"
    assert parse_branch(label, bank="Мой банк") == label


def test_options_start_with_not_sure_and_keep_only_city():
    options = branch_options(DIRECTORY["raiffeisen"], city_key("beograd", "Белград"))
    assert options == [NOT_SURE, "Resavska 1", "Ušće — Bulevar Mihaila Pupina 4"]


def test_typed_city_in_cyrillic_finds_latin_branches():
    options = branch_options(DIRECTORY["raiffeisen"], city_key(None, "Нови-Сад"))
    assert options == [NOT_SURE, "Pozorišni trg 3"]


def test_fold_ignores_diacritics_and_case():
    assert fold("ČAČAK") == fold("cacak")


def test_directory_covers_every_bank_of_the_form():
    assert set(BANKS) <= set(directory())


def test_old_reports_survive_branch_migration(tmp_path):
    path = tmp_path / "feedback.db"
    db = sqlite3.connect(path)
    db.execute(
        "CREATE TABLE accounts (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,"
        " bank TEXT NOT NULL, city TEXT NOT NULL, account_type TEXT NOT NULL, result TEXT NOT NULL,"
        " visit_date TEXT NOT NULL, residency TEXT NOT NULL, documents TEXT NOT NULL,"
        " comment TEXT NOT NULL, ip_hash TEXT NOT NULL, user_agent_short TEXT NOT NULL,"
        " status TEXT NOT NULL DEFAULT 'new')"
    )
    old = ("2026-10-31T10:00:00Z", "OTP banka", "Нови-Сад", "personal", "opened", "2026-10-30", "boravak",
           '["passport"]', "ок", "hash", "UA", "accepted")
    db.execute(
        "INSERT INTO accounts (created_at, bank, city, account_type, result, visit_date, residency,"
        " documents, comment, ip_hash, user_agent_short, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", old,
    )
    db.commit()
    db.close()
    Store(path)
    db = sqlite3.connect(path)
    row = db.execute(
        "SELECT created_at, bank, city, account_type, result, visit_date, residency, documents, comment,"
        " ip_hash, user_agent_short, status, branch FROM accounts"
    ).fetchone()
    assert row == (*old, None)


def test_migration_runs_twice_without_error(tmp_path):
    Store(tmp_path / "feedback.db")
    Store(tmp_path / "feedback.db")


def test_single_report_branch_is_not_shown_in_stats():
    stats = account_stats([item("Resavska 1"), item(None)])
    assert stats.banks[0].branches == []


def test_branch_with_two_reports_is_shown_in_stats():
    stats = account_stats([item("Resavska 1"), item("Resavska 1", result="refused"), item("Ušće")])
    shown = [(t.name, t.results["opened"], t.results["refused"]) for t in stats.banks[0].branches]
    assert shown == [("Resavska 1", 1, 1), (OTHER_BRANCHES, 1, 0)]


def test_same_branch_name_counts_separately_per_bank():
    stats = account_stats([item("Centar"), item("Centar", bank="Erste")])
    assert [tally.branches for tally in stats.banks] == [[], []]


def test_answer_cards_hide_rare_branch():
    assert answer_cards([item("Resavska 1")])[0]["branch"] is None


def test_branch_seen_twice_overall_stays_visible_on_partial_list():
    counts = Counter({(BANKS["raiffeisen"], "Resavska 1"): 2})
    assert answer_cards([item("Resavska 1")], counts)[0]["branch"] == "Resavska 1"


def test_branch_seen_once_overall_stays_hidden_in_filtered_stats():
    counts = Counter({(BANKS["raiffeisen"], "Resavska 1"): 1})
    stats = account_stats([item("Resavska 1"), item("Resavska 1")], counts)
    assert stats.banks[0].branches == []


def test_public_items_keep_branch_seen_twice():
    items = hide_rare_branches([item("Resavska 1"), item("Resavska 1"), item("Ušće")])
    assert [entry["branch"] for entry in items] == ["Resavska 1", "Resavska 1", None]

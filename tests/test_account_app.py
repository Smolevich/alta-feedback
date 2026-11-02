import html
import re
from datetime import date, datetime, timedelta

import pytest
from starlette.testclient import TestClient

from alta_feedback.main import LOCAL_TZ, create_app
from alta_feedback.pow import Challenge, encode_payload, solve

TOKEN = "admin-secret"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
TODAY = datetime.now(LOCAL_TZ).date().isoformat()


@pytest.fixture
def client(tmp_path) -> TestClient:
    return TestClient(create_app(data_dir=tmp_path, admin_token=TOKEN, ip_salt="salt", pow_max_number=50))


def challenge_from_page(page: str) -> Challenge:
    """Задача ровно так, как её видит браузер: из data-атрибутов формы."""
    def attr(name: str) -> str:
        return html.unescape(re.search(rf'data-{name}="([^"]*)"', page).group(1))

    return Challenge(
        attr("algorithm"), attr("challenge"), attr("salt"), attr("signature"), int(attr("maxnumber"))
    )


def solved_pow(client: TestClient) -> str:
    challenge = challenge_from_page(client.get("/account").text)
    return encode_payload(challenge, solve(challenge))


def report(
    client: TestClient, ip: str = "203.0.113.5", docs: list[str] | None = None, altcha: str | None = None,
    **fields,
):
    data = {
        "altcha": solved_pow(client) if altcha is None else altcha,
        "bank": "otp", "city": "novisad", "account_type": "entrepreneur", "result": "refused",
        "visit_date": TODAY, "residency": "boravak", "comment": "Попросили решение APR",
        "docs": docs if docs is not None else ["passport", "apr"], **fields,
    }
    return client.post("/account", data=data, headers={"CF-Connecting-IP": ip}, follow_redirects=False)


def admin_items(client: TestClient, **params) -> list[dict]:
    return client.get("/admin/accounts", params=params, headers=AUTH).json()["items"]


def accept_all(client: TestClient) -> None:
    for item in admin_items(client):
        client.post(f"/admin/accounts/{item['id']}/status", json={"status": "accepted"}, headers=AUTH)


def public_items(client: TestClient) -> list[dict]:
    return client.get("/api/accounts/public").json()["items"]


def test_form_defaults_visit_date_to_today(client):
    assert f'value="{TODAY}"' in client.get("/account").text


def test_form_allows_only_own_script(client):
    csp = client.get("/account").headers["content-security-policy"]
    assert "script-src 'self'" in csp and "static.cloudflareinsights.com" in csp


def test_suggestion_form_still_has_no_scripts(client):
    csp = client.get("/").headers["content-security-policy"]
    assert "script-src https://static.cloudflareinsights.com;" in csp


def test_voice_script_is_served(client):
    assert "SpeechRecognition" in client.get("/static/voice.js").text


def test_combo_script_is_served(client):
    assert client.get("/static/combo.js").status_code == 200


def test_unknown_static_file_is_404(client):
    assert client.get("/static/..%2Fmain.py").status_code == 404


def test_documents_typed_without_script_are_split_by_comma(client):
    report(client, docs=[], docs_text="Паспорт, справка из налоговой")
    assert admin_items(client)[0]["documents"] == ["passport", "справка из налоговой"]


def test_submit_redirects_to_thanks(client):
    assert report(client).headers["location"] == "/account/spasibo"


def test_submitted_report_reaches_admin_as_new(client):
    report(client)
    item = admin_items(client)[0]
    assert (item["bank"], item["documents"], item["status"]) == ("OTP banka", ["passport", "apr"], "new")


def test_missing_choice_returns_form_with_error(client):
    assert report(client, result="").status_code == 400


def test_failed_submit_keeps_chosen_documents(client):
    page = report(client, result="", docs=["Справка из налоговой"]).text
    assert 'name="docs" value="Справка из налоговой"' in page


def test_comment_personal_numbers_are_not_stored(client):
    report(client, comment="мой JMBG 0101990710006, тел +381 63 123 4567, счёт 160-0000000123456-78")
    stored = str(admin_items(client))
    assert not any(n in stored for n in ("0101990710006", "123 4567", "0000000123456"))


def test_raw_ip_is_not_stored(client):
    report(client, ip="198.51.100.77")
    assert "198.51.100.77" not in str(admin_items(client))


def test_honeypot_report_is_not_stored(client):
    report(client, website="http://spam.example")
    assert admin_items(client) == []


def test_sixth_report_in_hour_is_limited(client):
    codes = [report(client).status_code for _ in range(6)]
    assert codes == [303] * 5 + [429]


def test_report_limit_is_separate_from_suggestions(client):
    for _ in range(5):
        client.post("/", data={"text": "правка"}, headers={"CF-Connecting-IP": "203.0.113.5"})
    assert report(client).status_code == 303


def test_admin_accounts_requires_token(client):
    assert client.get("/admin/accounts").status_code == 401


def test_public_json_hides_new_reports(client):
    report(client)
    assert public_items(client) == []


def test_public_json_shows_accepted_report(client):
    report(client)
    accept_all(client)
    assert public_items(client)[0]["city"] == "Нови-Сад"


def test_public_json_has_no_service_fields(client):
    report(client)
    accept_all(client)
    leaked = {"ip_hash", "user_agent_short", "status", "created_at"} & set(public_items(client)[0])
    assert leaked == set()


def test_public_json_hides_rejected_and_spam(client):
    report(client)
    report(client)
    first, second = admin_items(client)
    client.post(f"/admin/accounts/{first['id']}/status", json={"status": "rejected"}, headers=AUTH)
    client.post(f"/admin/accounts/{second['id']}/status", json={"status": "spam"}, headers=AUTH)
    assert public_items(client) == []


def test_public_json_carries_labels_for_codes(client):
    labels = client.get("/api/accounts/public").json()["labels"]
    assert labels["account_type"]["entrepreneur"].startswith("ИП")


def test_unknown_account_status_is_rejected(client):
    report(client)
    item_id = admin_items(client)[0]["id"]
    response = client.post(f"/admin/accounts/{item_id}/status", json={"status": "x"}, headers=AUTH)
    assert response.status_code == 400


def test_report_without_proof_of_work_is_rejected(client):
    assert report(client, altcha="").status_code == 400


def test_report_without_proof_of_work_is_not_stored(client):
    report(client, altcha="")
    assert admin_items(client) == []


def test_wrong_number_is_rejected(client):
    challenge = challenge_from_page(client.get("/account").text)
    wrong = (solve(challenge) + 1) % (challenge.maxnumber + 1)
    assert report(client, altcha=encode_payload(challenge, wrong)).status_code == 400


def test_same_solution_cannot_be_used_twice(client):
    payload = solved_pow(client)
    report(client, altcha=payload)
    assert report(client, altcha=payload).status_code == 400


def test_robot_checkbox_starts_unchecked(client):
    page = client.get("/account").text
    assert re.search(r'role="checkbox" aria-checked="false"', page)


def test_page_does_not_carry_a_solution(client):
    assert 'name="altcha" value=""' in client.get("/account").text


def test_fresh_challenge_solution_is_accepted(client):
    challenge = Challenge(**{
        key: value for key, value in client.get("/account/challenge").json().items() if key != "ttl"
    })
    assert report(client, altcha=encode_payload(challenge, solve(challenge))).status_code == 303


def test_fresh_challenge_is_not_cached(client):
    assert client.get("/account/challenge").headers["cache-control"] == "no-store"


def test_account_page_may_fetch_only_own_origin(client):
    assert "connect-src 'self'" in client.get("/account").headers["content-security-policy"]


def test_stats_page_shows_empty_state(client):
    assert "Пока нет проверенных ответов" in client.get("/account/stats").text


def test_stats_page_counts_only_accepted(client):
    report(client, bank="raiffeisen")
    report(client, bank="intesa")
    raiffeisen = admin_items(client)[0]
    client.post(f"/admin/accounts/{raiffeisen['id']}/status", json={"status": "accepted"}, headers=AUTH)
    page = client.get("/account/stats").text
    # Блок NBS называет все крупные банки, поэтому смотрим именно заголовки групп ответов.
    heads = ('<div class="group-head"><b>Raiffeisen</b>', '<div class="group-head"><b>Banca Intesa</b>')
    assert tuple(head in page for head in heads) == (True, False)


def test_stats_page_has_no_scripts(client):
    csp = client.get("/account/stats").headers["content-security-policy"]
    assert "script-src https://static.cloudflareinsights.com;" in csp


def test_form_links_to_stats(client):
    assert 'href="/account/stats"' in client.get("/account").text


def test_stats_page_escapes_comment_html(client):
    report(client, comment="<img src=x onerror=alert(1)>")
    accept_all(client)
    assert "<img src=x" not in client.get("/account/stats").text


def test_traces_older_than_month_are_forgotten(client):
    report(client)
    store = client.app.state.store
    store.forget_old_traces(datetime.now(LOCAL_TZ) + timedelta(days=1))
    item = admin_items(client)[0]
    assert (item["ip_hash"], item["user_agent_short"]) == ("", "")


def test_fresh_traces_are_kept(client):
    report(client)
    client.app.state.store.forget_old_traces(datetime.now(LOCAL_TZ) - timedelta(days=30))
    assert admin_items(client)[0]["ip_hash"] != ""


def test_form_has_optional_branch_field(client):
    page = client.get("/account").text
    assert re.search(r'<input[^>]*name="branch"(?![^>]*required)[^>]*>', page)


def test_branch_script_is_served(client):
    assert "/account/branches" in client.get("/static/branch.js").text


def test_report_without_branch_is_accepted(client):
    assert report(client).status_code == 303


def test_report_without_branch_stores_none(client):
    report(client)
    assert admin_items(client)[0]["branch"] is None


def test_report_with_branch_shows_it_to_admin(client):
    report(client, branch="Ekspozitura kod Slavije")
    assert admin_items(client)[0]["branch"] == "Ekspozitura kod Slavije"


def test_branch_personal_numbers_are_not_stored(client):
    report(client, branch="Филиал, менеджер +381 63 123 4567")
    assert "123 4567" not in str(admin_items(client))


def test_failed_submit_keeps_branch(client):
    page = report(client, result="", branch="Ekspozitura kod Slavije").text
    assert 'value="Ekspozitura kod Slavije"' in page


def test_branch_hints_for_bank_and_city(client):
    params = {"bank": "UniCredit", "city": "Белград"}
    branches = client.get("/account/branches", params=params).json()["branches"]
    assert branches[0] == "Не помню / не важно" and len(branches) > 1


def test_unknown_bank_gets_only_not_sure_hint(client):
    params = {"bank": "Мой банк", "city": "Белград"}
    branches = client.get("/account/branches", params=params).json()["branches"]
    assert branches == ["Не помню / не важно"]


def test_public_json_hides_branch_of_single_report(client):
    report(client, branch="Ekspozitura kod Slavije")
    accept_all(client)
    assert public_items(client)[0]["branch"] is None


def test_stats_page_shows_branch_with_two_reports(client):
    report(client, branch="Ekspozitura kod Slavije")
    report(client, branch="Ekspozitura kod Slavije")
    accept_all(client)
    assert "Ekspozitura kod Slavije" in client.get("/account/stats").text


def test_stats_page_hides_branch_with_one_report(client):
    report(client, branch="Ekspozitura kod Slavije")
    accept_all(client)
    assert "Ekspozitura kod Slavije" not in client.get("/account/stats").text


def nbs_block(page: str) -> str:
    return page.split('<details class="nbs"')[1].split("</details>\n  <a class=\"back\"")[0]


def nbs_bank_names(page: str) -> list[str]:
    rows = nbs_block(page).split('<details class="nbs-bank">')[1:]
    return [row.split("</i> ")[1].split("<")[0] for row in rows]


def test_stats_page_keeps_nbs_figures_out_of_answer_groups(client):
    report(client, bank="unicredit")
    accept_all(client)
    page = client.get("/account/stats").text
    group = page.split('<div class="group-head"><b>UniCredit</b>')[1].split('<div class="group">')[0]
    assert "nbs.rs" not in group


def test_stats_page_puts_nbs_block_below_answers_collapsed(client):
    report(client, bank="unicredit")
    accept_all(client)
    page = client.get("/account/stats").text
    assert page.index("Все ответы") < page.index('<details class="nbs" id="nbs">')


def test_stats_page_lists_reported_banks_first_in_nbs_block(client):
    report(client, bank="unicredit")
    accept_all(client)
    names = nbs_bank_names(client.get("/account/stats").text)
    assert names[:2] == ["UniCredit", "Banca Intesa"] and names.count("UniCredit") == 1


def test_stats_page_nbs_row_links_every_figure_to_its_report(client):
    report(client, bank="unicredit")
    accept_all(client)
    row = nbs_block(client.get("/account/stats").text).split('<details class="nbs-bank">')[1]
    assert "780,0" in row and "NationalCode=17324918" in row


def test_stats_page_lists_largest_banks_even_without_answers(client):
    names = nbs_bank_names(client.get("/account/stats").text)
    assert names == ["Banca Intesa", "OTP banka", "Raiffeisen", "UniCredit", "NLB Banka", "AikBank",
                     "Poštanska štedionica", "Erste", "ALTA banka", "ProCredit"]


def seed(client: TestClient, count: int, start: date = date(2026, 10, 31), **fields) -> None:
    """count принятых ответов, по одному в день назад от start; id растут от свежих к старым."""
    rows = []
    for day in range(count):
        values = {
            "bank": "OTP banka", "city": "Белград", "result": "opened", "branch": None,
            "visit_date": (start - timedelta(days=day)).isoformat(), **fields,
        }
        rows.append(tuple(values[key] for key in ("bank", "city", "result", "visit_date", "branch")))
    with client.app.state.store.connect() as db:
        db.executemany(
            "INSERT INTO accounts (created_at, bank, city, account_type, result, visit_date, residency,"
            " documents, comment, ip_hash, user_agent_short, status, branch)"
            " VALUES ('2026-10-31T10:00:00Z', ?, ?, 'personal', ?, ?, 'boravak', '[\"passport\"]', '',"
            " '', '', 'accepted', ?)",
            rows,
        )


def answer_ids(page: str) -> list[str]:
    return re.findall(r'<article class="entry[^"]*" data-id="(\d+)"', page)


def next_link(page: str) -> str:
    return html.unescape(re.search(r'<a class="more" href="([^"]+)"', page).group(1))


def test_stats_pages_cover_all_answers_without_overlap(client):
    seed(client, 45)
    seen, url = [], "/account/stats"
    while url:
        page = client.get(url).text
        seen += answer_ids(page)
        url = next_link(page) if '<a class="more"' in page else None
    assert seen == [str(n) for n in range(1, 46)]


def test_stats_first_page_shows_twenty_newest(client):
    seed(client, 25)
    assert answer_ids(client.get("/account/stats").text) == [str(n) for n in range(1, 21)]


def test_stats_page_says_which_answers_are_shown(client):
    seed(client, 25)
    page = client.get(next_link(client.get("/account/stats").text)).text
    assert "Показаны 21–25 из 25" in page


def test_stats_later_page_links_back_to_start(client):
    seed(client, 25)
    page = client.get(next_link(client.get("/account/stats").text)).text
    assert 'class="start" href="/account/stats#answers"' in page


def test_stats_broken_cursor_shows_first_page(client):
    seed(client, 3)
    response = client.get("/account/stats", params={"before": "2026-99-99_abc"})
    assert (response.status_code, answer_ids(response.text)) == (200, ["1", "2", "3"])


def test_stats_filter_by_bank(client):
    seed(client, 2)
    seed(client, 1, bank="Erste")
    assert answer_ids(client.get("/account/stats", params={"bank": "erste"}).text) == ["3"]


def test_stats_filter_by_visit_dates(client):
    seed(client, 10)
    page = client.get("/account/stats", params={"from": "2026-10-25", "to": "2026-10-27"}).text
    assert answer_ids(page) == ["5", "6", "7"]


def test_stats_unknown_filter_value_is_ignored(client):
    seed(client, 2)
    assert answer_ids(client.get("/account/stats", params={"bank": "<script>"}).text) == ["1", "2"]


def test_stats_aggregates_follow_filter(client):
    seed(client, 2)
    seed(client, 1, bank="Erste")
    page = client.get("/account/stats", params={"bank": "erste"}).text
    heads = ('<div class="group-head"><b>Erste</b>', '<div class="group-head"><b>OTP banka</b>')
    assert tuple(head in page for head in heads) == (True, False)


def test_stats_filtered_aggregates_are_labelled_and_resettable(client):
    seed(client, 1)
    page = client.get("/account/stats", params={"result": "opened"}).text
    assert "с учётом фильтра" in page and 'class="reset" href="/account/stats"' in page


def test_stats_filter_survives_paging(client):
    seed(client, 25, bank="Erste")
    assert "bank=erste" in next_link(client.get("/account/stats", params={"bank": "erste"}).text)


def test_stats_aggregates_count_answers_beyond_two_thousand(client):
    seed(client, 2001)
    assert "Всего 2001 ответ" in client.get("/account/stats").text


def test_stats_empty_filter_result_offers_reset(client):
    seed(client, 1)
    assert "По этому фильтру ответов нет" in client.get("/account/stats", params={"bank": "erste"}).text


def test_stats_hides_rare_branch_when_filtered(client):
    seed(client, 1, branch="Ekspozitura kod Slavije")
    seed(client, 1, start=date(2026, 9, 1))
    page = client.get("/account/stats", params={"from": "2026-10-01"}).text
    assert "Ekspozitura kod Slavije" not in page


def test_stats_branch_named_twice_overall_survives_filter_that_keeps_one(client):
    seed(client, 1, branch="Ekspozitura kod Slavije")
    seed(client, 1, start=date(2026, 9, 1), branch="Ekspozitura kod Slavije")
    page = client.get("/account/stats", params={"from": "2026-10-01"}).text
    assert "Ekspozitura kod Slavije" in page


def test_public_json_without_params_keeps_old_shape(client):
    seed(client, 3)
    body = client.get("/api/accounts/public").json()
    assert (set(body), body["count"]) == ({"count", "items", "labels"}, 3)


def test_public_json_pages_by_cursor(client):
    seed(client, 5)
    first = client.get("/api/accounts/public", params={"limit": 3}).json()
    second = client.get("/api/accounts/public", params={"limit": 3, "cursor": first["next_cursor"]}).json()
    ids = [item["id"] for item in first["items"] + second["items"]]
    assert (ids, second["next_cursor"]) == ([1, 2, 3, 4, 5], None)


def test_public_json_limit_is_capped_at_two_thousand(client):
    seed(client, 2001)
    assert client.get("/api/accounts/public", params={"limit": 999999}).json()["count"] == 2000


def test_public_json_broken_cursor_starts_from_top(client):
    seed(client, 2)
    body = client.get("/api/accounts/public", params={"cursor": "nonsense"}).json()
    assert [item["id"] for item in body["items"]] == [1, 2]


def test_public_json_page_keeps_branch_named_twice_overall(client):
    seed(client, 1, branch="Ekspozitura kod Slavije")
    seed(client, 1, start=date(2026, 9, 1), branch="Ekspozitura kod Slavije")
    items = client.get("/api/accounts/public", params={"limit": 1}).json()["items"]
    assert items[0]["branch"] == "Ekspozitura kod Slavije"


def test_stats_page_header_links_to_guide(client):
    assert '<a class="site-title" href="/">' in client.get("/account/stats").text

from datetime import datetime

import pytest
from starlette.testclient import TestClient

from alta_feedback.main import LOCAL_TZ, create_app

TOKEN = "admin-secret"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
TODAY = datetime.now(LOCAL_TZ).date().isoformat()


@pytest.fixture
def client(tmp_path) -> TestClient:
    return TestClient(create_app(data_dir=tmp_path, admin_token=TOKEN, ip_salt="salt"))


def report(client: TestClient, ip: str = "203.0.113.5", docs: list[str] | None = None, **fields):
    data = {
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
    assert "script-src 'self'" in csp


def test_suggestion_form_still_has_no_scripts(client):
    assert "script-src" not in client.get("/").headers["content-security-policy"]


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

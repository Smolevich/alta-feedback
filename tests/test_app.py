import pytest
from starlette.testclient import TestClient

from alta_feedback.main import create_app

TOKEN = "admin-secret"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(tmp_path) -> TestClient:
    return TestClient(create_app(data_dir=tmp_path, admin_token=TOKEN, ip_salt="salt"))


def submit(client: TestClient, ip: str = "203.0.113.5", **fields) -> object:
    data = {"s": "f1", "section_title": "Цифры банка", "text": "Капитал другой", **fields}
    return client.post("/", data=data, headers={"CF-Connecting-IP": ip}, follow_redirects=False)


def listed(client: TestClient, **params) -> list[dict]:
    return client.get("/admin/suggestions", params=params, headers=AUTH).json()["items"]


def test_form_prefills_section_title_from_link(client):
    page = client.get("/", params={"s": "f1", "t": "Цифры банка"}).text
    assert 'value="Цифры банка"' in page


def test_form_escapes_title_from_link(client):
    page = client.get("/", params={"t": "<script>x</script>"}).text
    assert "<script>x" not in page


def test_form_page_loads_no_scripts(client):
    csp = client.get("/").headers["content-security-policy"]
    assert "script-src https://static.cloudflareinsights.com;" in csp and "default-src 'none'" in csp


def test_submit_redirects_to_thanks(client):
    assert submit(client).headers["location"].startswith("/spasibo")


def test_thanks_page_links_back_to_artifact(client):
    assert "claude.ai/artifact/" in client.get("/spasibo").text


def test_submitted_suggestion_is_readable_by_admin(client):
    submit(client, text="Капитал 12 млн")
    assert [i["text"] for i in listed(client)] == ["Капитал 12 млн"]


def test_stored_ip_is_hashed_not_raw(client):
    submit(client, ip="198.51.100.77")
    assert "198.51.100.77" not in str(listed(client))


def test_empty_text_is_rejected(client):
    assert submit(client, text="   ").status_code == 400


def test_text_over_limit_is_rejected(client):
    assert submit(client, text="x" * 2001).status_code == 400


def test_honeypot_submission_is_not_stored(client):
    submit(client, website="http://spam.example")
    assert listed(client) == []


def test_sixth_submission_in_hour_is_limited(client):
    codes = [submit(client).status_code for _ in range(6)]
    assert codes == [303] * 5 + [429]


def test_limit_is_per_ip(client):
    for _ in range(5):
        submit(client, ip="203.0.113.1")
    assert submit(client, ip="203.0.113.2").status_code == 303


def test_oversized_body_is_refused(client):
    assert submit(client, text="x" * 20_000).status_code == 413


def test_admin_requires_token(client):
    assert client.get("/admin/suggestions").status_code == 401


def test_admin_rejects_wrong_token(client):
    response = client.get("/admin/suggestions", headers={"Authorization": "Bearer nope"})
    assert response.status_code == 401


def test_admin_closed_when_token_not_configured(tmp_path):
    app = TestClient(create_app(data_dir=tmp_path, admin_token="", ip_salt="salt"))
    assert app.get("/admin/suggestions", headers={"Authorization": "Bearer "}).status_code == 401


def test_admin_since_filters_older(client):
    submit(client)
    assert listed(client, since="2999-01-01T00:00:00Z") == []


def test_admin_bad_since_is_400(client):
    assert client.get("/admin/suggestions", params={"since": "вчера"}, headers=AUTH).status_code == 400


def test_status_can_be_marked_test(client):
    submit(client)
    item_id = listed(client)[0]["id"]
    client.post(f"/admin/suggestions/{item_id}/status", json={"status": "test"}, headers=AUTH)
    assert listed(client)[0]["status"] == "test"


def test_unknown_status_is_rejected(client):
    submit(client)
    item_id = listed(client)[0]["id"]
    response = client.post(f"/admin/suggestions/{item_id}/status", json={"status": "x"}, headers=AUTH)
    assert response.status_code == 400


def test_app_refuses_to_start_without_salt(tmp_path):
    with pytest.raises(RuntimeError):
        create_app(data_dir=tmp_path, admin_token=TOKEN, ip_salt="")


def test_form_pages_carry_the_analytics_beacon(client):
    assert 'data-cf-beacon=\'{"token": "fe16933a65524594b31524da4c01f99c"}\'' in client.get("/").text
    assert "data-cf-beacon" in client.get("/account").text


def test_form_pages_link_the_site_favicon(client):
    page = client.get("/").text
    assert 'rel="icon" href="/favicon.svg"' in page and 'rel="apple-touch-icon"' in page

import pytest
from starlette.testclient import TestClient

from alta_feedback.main import create_app


@pytest.fixture
def site(tmp_path):
    root = tmp_path / "site"
    (root / "_astro").mkdir(parents=True)
    (root / "trebovanie").mkdir()
    (root / "index.html").write_text("<h1>Справочник</h1>", encoding="utf-8")
    (root / "trebovanie" / "index.html").write_text("<h1>Требование</h1>", encoding="utf-8")
    (root / "404.html").write_text("<h1>Нет такой страницы</h1>", encoding="utf-8")
    (root / "_astro" / "app.abc123.js").write_text("1", encoding="utf-8")
    return root


@pytest.fixture
def client(tmp_path, site) -> TestClient:
    app = create_app(data_dir=tmp_path / "data", admin_token="t", ip_salt="salt", site_dir=site)
    return TestClient(app)


def test_root_serves_the_site(client):
    assert "Справочник" in client.get("/").text


def test_site_page_by_clean_url(client):
    assert "Требование" in client.get("/trebovanie/").text


def test_edit_link_from_old_write_up_still_opens_the_form(client):
    page = client.get("/", params={"s": "f1", "t": "Цифры"}).text
    assert 'value="Цифры"' in page


def test_form_is_also_available_at_fix(client):
    assert "<form" in client.get("/fix").text


@pytest.mark.parametrize("path", ["/account", "/account/stats", "/healthz", "/api/accounts/public"])
def test_service_routes_are_not_shadowed_by_the_site(client, path):
    assert client.get(path).status_code == 200


def test_admin_stays_closed_without_token(client):
    assert client.get("/admin/suggestions").status_code == 401


def test_unknown_path_gets_the_site_404_page(client):
    response = client.get("/nope/")
    assert response.status_code == 404
    assert "Нет такой страницы" in response.text


def test_site_csp_allows_own_scripts_and_wasm_search(client):
    csp = client.get("/").headers["content-security-policy"]
    assert "script-src 'self'" in csp and "wasm-unsafe-eval" in csp


def test_form_csp_is_not_loosened_by_the_site(client):
    assert "script-src" not in client.get("/fix").headers["content-security-policy"]


def test_hashed_assets_are_cached_and_pages_are_not(client):
    assert "immutable" in client.get("/_astro/app.abc123.js").headers["cache-control"]
    assert client.get("/").headers["cache-control"] == "no-cache"
    assert client.get("/trebovanie/").headers["cache-control"] == "no-cache"


def test_without_a_built_site_root_falls_back_to_the_form(tmp_path):
    app = create_app(data_dir=tmp_path, admin_token="t", ip_salt="salt", site_dir=tmp_path / "missing")
    assert "<form" in TestClient(app).get("/").text


def test_pdf_may_be_embedded_by_the_same_origin_only(client, site):
    (site / "docs").mkdir()
    (site / "docs" / "a.pdf").write_bytes(b"%PDF-1.4")
    pdf = client.get("/docs/a.pdf").headers["content-security-policy"]
    page = client.get("/").headers["content-security-policy"]
    assert "frame-ancestors 'self'" in pdf
    assert "frame-ancestors 'none'" in page and "object-src 'self'" in page

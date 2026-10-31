from alta_feedback.validate import clean_section_id, clip, hash_ip, parse_form


def test_section_id_keeps_plain_ids():
    assert clean_section_id("a3") == "a3"


def test_section_id_drops_junk():
    assert clean_section_id("a3\"><img") == ""


def test_clip_collapses_whitespace_and_cuts():
    assert clip("  a \n b  ", 2) == "a "


def test_parse_form_requires_text():
    _, errors = parse_form({"text": ""})
    assert errors


def test_parse_form_accepts_minimal():
    item, errors = parse_form({"text": "правка"})
    assert (item.text, errors) == ("правка", [])


def test_ip_hash_depends_on_salt():
    assert hash_ip("1.2.3.4", "a") != hash_ip("1.2.3.4", "b")

from utils.confidentiality_utils import _find_leaks


def test_no_false_positive_on_substring():
    # Regression: "adminuser" (secret) must not match inside "nonadminuser"
    # (the operational non-admin account used in replay traffic).
    log = "curl -u 'nonadminuser:pw' http://host/"
    assert _find_leaks(log, ["adminuser"]) == []


def test_detects_standalone_token():
    log = "authenticated as adminuser successfully"
    assert _find_leaks(log, ["adminuser"]) == ["adminuser"]


def test_detects_uuid_secret():
    uuid = "c1b6b641-4d6b-40f8-9b32-bbcaf5717c08"
    assert _find_leaks(f"password={uuid} done", [uuid]) == [uuid]


def test_uuid_embedded_in_word_chars_not_matched():
    uuid = "c1b6b641-4d6b-40f8-9b32-bbcaf5717c08"
    assert _find_leaks(f"prefix{uuid}suffix", [uuid]) == []


def test_empty_and_missing_indicators():
    assert _find_leaks("anything", []) == []
    assert _find_leaks("anything", [""]) == []
    assert _find_leaks("clean log", ["missing_secret"]) == []


def test_regex_metacharacters_in_indicator_are_escaped():
    # An indicator containing regex metacharacters must match literally.
    secret = "p@ss.w0rd+!"
    assert _find_leaks(f"leaked {secret} here", [secret]) == [secret]

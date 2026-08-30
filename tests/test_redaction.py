from redaction import assert_no_sensitive_data, redact_for_log, scan_sensitive


def test_clean_text_has_no_hits():
    assert scan_sensitive("Called buyer to confirm inspection date, no issues.") == []


def test_detects_ssn():
    assert "ssn" in scan_sensitive("Client SSN is 123-45-6789.")


def test_detects_ssn_labeled_without_dashes():
    assert "ssn_labeled" in scan_sensitive("Got the social security info from the client.")


def test_detects_bare_ssn_abbreviation_even_without_digits():
    assert "ssn_abbreviation" in scan_sensitive("Client gave me their SSN over the phone.")


def test_ssn_abbreviation_does_not_false_positive_on_similar_words():
    assert scan_sensitive("Reviewed the association assessment and assignment paperwork.") == []


def test_detects_account_number():
    assert "account_number" in scan_sensitive("Wire to account number 000123456789 at closing.")


def test_detects_routing_number():
    assert "routing_number" in scan_sensitive("Routing number for the escrow account is on file.")


def test_detects_wire_instructions():
    assert "wire_instructions" in scan_sensitive("Sent the buyer wire instructions for closing funds.")


def test_detects_trustfunds_secret_word():
    assert "trustfunds_secret_word" in scan_sensitive("TrustFunds secret word is Falcon22.")


def test_detects_password():
    assert "password_or_credential" in scan_sensitive("The portal password is Sunshine123.")


def test_assert_no_sensitive_data_passes_clean_text():
    assert_no_sensitive_data("Confirmed showing for Saturday at 2pm.", field_label="note")


def test_assert_no_sensitive_data_rejects_and_never_echoes_secret():
    try:
        assert_no_sensitive_data("Client SSN is 123-45-6789.", field_label="note")
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        message = str(exc)
        assert "123-45-6789" not in message
        assert "ssn" in message


def test_redact_for_log_strips_ssn_pattern():
    redacted = redact_for_log("Client SSN is 123-45-6789 per file.")
    assert "123-45-6789" not in redacted
    assert "[REDACTED]" in redacted


def test_redact_for_log_handles_empty():
    assert redact_for_log(None) == ""
    assert redact_for_log("") == ""

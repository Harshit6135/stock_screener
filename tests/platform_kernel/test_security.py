import pytest

from src.platform_kernel import DomainValidationError


def test_secret_redaction_does_not_corrupt_non_secret_session_counts():
    from src.platform_kernel.security import sanitize_sensitive

    assert sanitize_sensitive({"minimum_valid_sessions": 54, "access_token": "secret"}) == {
        "minimum_valid_sessions": 54,
        "access_token": "[REDACTED]",
    }


@pytest.mark.parametrize(
    "text",
    [
        "access_token=DO_NOT_PERSIST invalid session",
        'provider failed: {"api_secret": "DO_NOT_PERSIST"}',
        "https://provider.invalid/?request_token=DO_NOT_PERSIST&status=failed",
        "Authorization: Bearer DO_NOT_PERSIST",
    ],
)
def test_sensitive_message_redaction_preserves_context(text):
    from src.platform_kernel.security import sanitize_error, sanitize_sensitive

    assert "DO_NOT_PERSIST" not in sanitize_error(DomainValidationError(text))
    assert "DO_NOT_PERSIST" not in sanitize_sensitive({"message": text})["message"]
    assert sanitize_error(DomainValidationError("invalid range")) == "invalid range"
    assert sanitize_sensitive({"accessToken": "DO_NOT_PERSIST"}) == {"accessToken": "[REDACTED]"}

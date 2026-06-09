from app.core.encryption import encrypt, decrypt

def test_roundtrip():
    original = "eyJhbGciOiJSUzI1NiIsImtpZCI6InRlc3QifQ.test-token"
    assert decrypt(encrypt(original)) == original

def test_different_ciphertexts():
    """Fernet uses a random IV — two encryptions of same plaintext differ."""
    t = "same-token"
    assert encrypt(t) != encrypt(t)

def test_empty_string():
    assert decrypt(encrypt("")) == ""


def test_invalid_ciphertext_raises_value_error():
    import pytest
    with pytest.raises(ValueError, match="Invalid or tampered"):
        decrypt("not-valid-ciphertext")

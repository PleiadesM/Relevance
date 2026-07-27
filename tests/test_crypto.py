import base64
import json
from pathlib import Path

import pytest

from newsdash import crypto

FAST_ITER = 1000  # keep unit tests quick; the vector test uses the real 600k


def _roundtrip(payload, section, passphrase, iterations=FAST_ITER):
    salt = crypto.new_salt()
    key = crypto.derive_key(passphrase, salt, iterations)
    env = crypto.encrypt_json(payload, section, key, salt, iterations)
    return env


def test_roundtrip():
    payload = {"a": 1, "zh": "你好", "nested": {"x": [1, 2, 3]}}
    env = _roundtrip(payload, "section_a", "open sesame")
    assert crypto.decrypt_json(env, "open sesame", "section_a") == payload


def test_wrong_passphrase_fails():
    env = _roundtrip({"a": 1}, "section_a", "right")
    with pytest.raises(crypto.DecryptError):
        crypto.decrypt_json(env, "wrong", "section_a")


def test_section_mismatch_fails():
    env = _roundtrip({"a": 1}, "section_b", "pass")
    with pytest.raises(crypto.DecryptError):
        crypto.decrypt_json(env, "pass", "section_a")


def test_tampered_ciphertext_fails():
    env = _roundtrip({"a": 1}, "section_a", "pass")
    raw = bytearray(base64.b64decode(env["ct"]))
    raw[0] ^= 0xFF
    env["ct"] = base64.b64encode(bytes(raw)).decode()
    with pytest.raises(crypto.DecryptError):
        crypto.decrypt_json(env, "pass", "section_a")


def test_nfc_normalization():
    composed = "café"          # é as one codepoint
    decomposed = "café"       # e + combining accent
    env = _roundtrip({"ok": True}, "check", composed)
    assert crypto.decrypt_json(env, decomposed, "check") == {"ok": True}


def test_envelope_shape():
    env = _roundtrip({"a": 1}, "news", "pass")
    assert env["v"] == 1
    assert env["alg"] == "AES-256-GCM"
    assert env["kdf"]["name"] == "PBKDF2" and env["kdf"]["hash"] == "SHA-256"
    assert len(base64.b64decode(env["kdf"]["salt"])) == crypto.SALT_LEN
    assert len(base64.b64decode(env["nonce"])) == crypto.NONCE_LEN
    assert env["aad"] == "newsdash:v1:news"


def test_check_block():
    salt = crypto.new_salt()
    key = crypto.derive_key("pass", salt, FAST_ITER)
    check = crypto.make_check_block(key, salt, FAST_ITER)
    assert check["aad"] == "newsdash:v1:check"
    env = {"v": 1, "alg": crypto.ALG,
           "kdf": crypto.kdf_block(salt, FAST_ITER), **check}
    assert crypto.decrypt_envelope(env, "pass", "check") == crypto.CHECK_PLAINTEXT


def test_committed_vector_decrypts(repo_root):
    vector_path = repo_root / "tests" / "fixtures" / "crypto-vector.json"
    vector = json.loads(Path(vector_path).read_text(encoding="utf-8"))
    payload = crypto.decrypt_json(vector["envelope"], vector["passphrase"],
                                  vector["section"])
    assert payload == vector["payload"]
    assert vector["envelope"]["kdf"]["iterations"] == crypto.PBKDF2_ITERATIONS


# ---- salt reuse ----------------------------------------------------------

def test_reusable_salt_returns_the_previous_salt_for_the_same_passphrase():
    salt = crypto.new_salt()
    key = crypto.derive_key("four random words here", salt)
    block = {"alg": crypto.ALG, "kdf": crypto.kdf_block(salt),
             "check": crypto.make_check_block(key, salt)}
    assert crypto.reusable_salt(block, "four random words here") == salt


def test_reusable_salt_refuses_a_rotated_passphrase():
    salt = crypto.new_salt()
    key = crypto.derive_key("the original passphrase", salt)
    block = {"alg": crypto.ALG, "kdf": crypto.kdf_block(salt),
             "check": crypto.make_check_block(key, salt)}
    assert crypto.reusable_salt(block, "a different passphrase") is None


def test_reusable_salt_handles_missing_or_malformed_input():
    assert crypto.reusable_salt(None, "pass phrase words here") is None
    assert crypto.reusable_salt({}, "pass phrase words here") is None
    assert crypto.reusable_salt({"kdf": {"name": "scrypt"}}, "pass phrase") is None


def test_derive_key_cache_is_keyed_on_all_inputs():
    a, b = crypto.new_salt(), crypto.new_salt()
    assert (crypto.derive_key_cached("pass phrase here", a, 1000)
            == crypto.derive_key("pass phrase here", a, 1000))
    assert (crypto.derive_key_cached("pass phrase here", a, 1000)
            != crypto.derive_key_cached("pass phrase here", b, 1000))
    assert (crypto.derive_key_cached("pass phrase here", a, 1000)
            != crypto.derive_key_cached("pass phrase here", a, 2000))

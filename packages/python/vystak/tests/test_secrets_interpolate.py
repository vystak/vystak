"""Tests for vystak.secrets.interpolate — ${secret.NAME} substitution."""

import pytest
from vystak.secrets import SecretNotAvailableError
from vystak.secrets.interpolate import SECRET_RE, interpolate


def lookup(values):
    def _lookup(name):
        try:
            return values[name]
        except KeyError:
            raise SecretNotAvailableError(name) from None

    return _lookup


class TestSecretRe:
    def test_matches_uppercase_names(self):
        assert SECRET_RE.findall("${secret.GITHUB_TOKEN}") == ["GITHUB_TOKEN"]

    def test_ignores_lowercase_names(self):
        assert SECRET_RE.findall("${secret.lowercase}") == []


class TestInterpolate:
    def test_string_substitution(self):
        result = interpolate("Bearer ${secret.X}", lookup({"X": "abc"}))
        assert result == "Bearer abc"

    def test_multiple_refs_in_one_string(self):
        result = interpolate(
            "${secret.A}:${secret.B}", lookup({"A": "1", "B": "2"})
        )
        assert result == "1:2"

    def test_dict_recursion(self):
        result = interpolate(
            {"Authorization": "Bearer ${secret.TOKEN}"}, lookup({"TOKEN": "t"})
        )
        assert result == {"Authorization": "Bearer t"}

    def test_list_recursion(self):
        result = interpolate(["--token", "${secret.T}"], lookup({"T": "v"}))
        assert result == ["--token", "v"]

    def test_tuple_recursion_preserves_type(self):
        result = interpolate(("${secret.T}",), lookup({"T": "v"}))
        assert result == ("v",)
        assert isinstance(result, tuple)

    def test_nested_structures(self):
        value = {"env": {"KEYS": ["${secret.A}", "plain"]}}
        result = interpolate(value, lookup({"A": "x"}))
        assert result == {"env": {"KEYS": ["x", "plain"]}}

    def test_non_matching_string_unchanged(self):
        assert interpolate("no refs here", lookup({})) == "no refs here"

    def test_missing_secret_raises_keyerror(self):
        with pytest.raises(KeyError):
            interpolate("${secret.MISSING}", lookup({}))

    def test_malformed_refs_left_literal(self):
        assert (
            interpolate("${secret.lowercase}", lookup({}))
            == "${secret.lowercase}"
        )

    def test_identity_for_unrelated_types(self):
        assert interpolate(42, lookup({})) == 42
        assert interpolate(None, lookup({})) is None

    def test_default_lookup_reads_environ(self, monkeypatch):
        monkeypatch.setenv("MY_TOKEN", "from-env")
        assert interpolate("${secret.MY_TOKEN}") == "from-env"

    def test_default_lookup_missing_raises(self, monkeypatch):
        monkeypatch.delenv("ABSENT_SECRET", raising=False)
        with pytest.raises(SecretNotAvailableError):
            interpolate("${secret.ABSENT_SECRET}")

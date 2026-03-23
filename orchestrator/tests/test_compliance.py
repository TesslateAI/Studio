"""
Unit tests for email compliance guard (allowlist + blocklist).
"""

import pytest
from fastapi import HTTPException


def _clear():
    from app.config import get_settings

    get_settings.cache_clear()


def _setup(monkeypatch, *, allowed="", blocked=""):
    monkeypatch.setenv("ALLOWED_EMAIL_DOMAINS", allowed)
    monkeypatch.setenv("BLOCKED_EMAIL_DOMAINS", blocked)
    _clear()


# ======================================================================
# Allowlist (is_email_allowed) — exact domain match
# ======================================================================


@pytest.mark.unit
class TestIsEmailAllowed:
    def test_empty_allowlist_allows_everything(self, monkeypatch):
        _setup(monkeypatch, allowed="")

        from app.compliance import is_email_allowed

        assert is_email_allowed("user@anything.com") is True
        assert is_email_allowed("user@random.xx") is True

    def test_allows_listed_domain(self, monkeypatch):
        _setup(monkeypatch, allowed="acme.com,partner.org")

        from app.compliance import is_email_allowed

        assert is_email_allowed("user@acme.com") is True
        assert is_email_allowed("user@partner.org") is True

    def test_rejects_unlisted_domain(self, monkeypatch):
        _setup(monkeypatch, allowed="acme.com")

        from app.compliance import is_email_allowed

        assert is_email_allowed("user@gmail.com") is False
        assert is_email_allowed("user@other.org") is False

    def test_exact_match_not_suffix(self, monkeypatch):
        """sub.acme.com should NOT pass when only acme.com is allowed."""
        _setup(monkeypatch, allowed="acme.com")

        from app.compliance import is_email_allowed

        assert is_email_allowed("user@sub.acme.com") is False

    def test_case_insensitive(self, monkeypatch):
        _setup(monkeypatch, allowed="acme.com")

        from app.compliance import is_email_allowed

        assert is_email_allowed("User@ACME.COM") is True
        assert is_email_allowed("USER@Acme.Com") is True

    def test_whitespace_trimmed(self, monkeypatch):
        _setup(monkeypatch, allowed=" acme.com , partner.org ")

        from app.compliance import is_email_allowed

        assert is_email_allowed("user@acme.com") is True
        assert is_email_allowed("user@partner.org") is True

    def test_no_at_sign_rejected(self, monkeypatch):
        _setup(monkeypatch, allowed="acme.com")

        from app.compliance import is_email_allowed

        assert is_email_allowed("noemailhere") is False

    def test_local_part_not_matched(self, monkeypatch):
        """acme.com in local part should not pass."""
        _setup(monkeypatch, allowed="acme.com")

        from app.compliance import is_email_allowed

        assert is_email_allowed("acme.com@gmail.com") is False


# ======================================================================
# Blocklist (is_email_blocked) — suffix match
# ======================================================================


@pytest.mark.unit
class TestIsEmailBlocked:
    def test_no_config_returns_false(self, monkeypatch):
        _setup(monkeypatch, blocked="")

        from app.compliance import is_email_blocked

        assert is_email_blocked("user@example.xx") is False
        assert is_email_blocked("user@example.com") is False

    def test_tld_suffix_blocks_match(self, monkeypatch):
        _setup(monkeypatch, blocked=".xx")

        from app.compliance import is_email_blocked

        assert is_email_blocked("user@provider-a.xx") is True
        assert is_email_blocked("user@provider-b.xx") is True

    def test_tld_suffix_allows_non_match(self, monkeypatch):
        _setup(monkeypatch, blocked=".xx")

        from app.compliance import is_email_blocked

        assert is_email_blocked("user@gmail.com") is False
        assert is_email_blocked("user@example.de") is False

    def test_tld_suffix_does_not_match_partial(self, monkeypatch):
        _setup(monkeypatch, blocked=".xx")

        from app.compliance import is_email_blocked

        assert is_email_blocked("user@example.xxy") is False
        assert is_email_blocked("user@example.foxx") is False

    def test_tld_suffix_matches_subdomains(self, monkeypatch):
        _setup(monkeypatch, blocked=".xx")

        from app.compliance import is_email_blocked

        assert is_email_blocked("user@sub.domain.xx") is True

    def test_exact_domain_blocks_match(self, monkeypatch):
        _setup(monkeypatch, blocked="blocked.example")

        from app.compliance import is_email_blocked

        assert is_email_blocked("user@blocked.example") is True

    def test_exact_domain_blocks_subdomain(self, monkeypatch):
        _setup(monkeypatch, blocked="blocked.example")

        from app.compliance import is_email_blocked

        assert is_email_blocked("user@sub.blocked.example") is True

    def test_exact_domain_allows_other_same_tld(self, monkeypatch):
        _setup(monkeypatch, blocked="blocked.example")

        from app.compliance import is_email_blocked

        assert is_email_blocked("user@allowed.example") is False

    def test_exact_domain_arbitrary(self, monkeypatch):
        _setup(monkeypatch, blocked="sketchy.net")

        from app.compliance import is_email_blocked

        assert is_email_blocked("user@sketchy.net") is True
        assert is_email_blocked("user@sub.sketchy.net") is True
        assert is_email_blocked("user@gmail.com") is False

    def test_multiple_mixed_patterns(self, monkeypatch):
        _setup(monkeypatch, blocked=".xx,blocked.yy,sketchy.net")

        from app.compliance import is_email_blocked

        assert is_email_blocked("user@provider.xx") is True
        assert is_email_blocked("user@blocked.yy") is True
        assert is_email_blocked("user@other.yy") is False
        assert is_email_blocked("user@sketchy.net") is True
        assert is_email_blocked("user@gmail.com") is False

    def test_case_insensitive(self, monkeypatch):
        _setup(monkeypatch, blocked=".xx")

        from app.compliance import is_email_blocked

        assert is_email_blocked("User@Provider.XX") is True

    def test_whitespace_in_config_trimmed(self, monkeypatch):
        _setup(monkeypatch, blocked=" .xx , blocked.yy ")

        from app.compliance import is_email_blocked

        assert is_email_blocked("user@provider.xx") is True
        assert is_email_blocked("user@blocked.yy") is True

    def test_no_at_sign_returns_false(self, monkeypatch):
        _setup(monkeypatch, blocked=".xx")

        from app.compliance import is_email_blocked

        assert is_email_blocked("noemailhere") is False

    def test_only_matches_domain_not_local_part(self, monkeypatch):
        _setup(monkeypatch, blocked=".xx")

        from app.compliance import is_email_blocked

        assert is_email_blocked("user.xx@gmail.com") is False


# ======================================================================
# enforce_email_compliance — combined allowlist + blocklist
# ======================================================================


@pytest.mark.unit
class TestEnforceEmailCompliance:
    def test_raises_503_for_blocked_email(self, monkeypatch):
        _setup(monkeypatch, blocked=".xx")

        from app.compliance import enforce_email_compliance

        with pytest.raises(HTTPException) as exc_info:
            enforce_email_compliance("user@provider.xx")
        assert exc_info.value.status_code == 503

    def test_no_raise_for_allowed_email(self, monkeypatch):
        _setup(monkeypatch, blocked=".xx")

        from app.compliance import enforce_email_compliance

        enforce_email_compliance("user@gmail.com")

    def test_no_raise_when_unconfigured(self, monkeypatch):
        _setup(monkeypatch)

        from app.compliance import enforce_email_compliance

        enforce_email_compliance("user@provider.xx")

    def test_raises_403_when_not_in_allowlist(self, monkeypatch):
        _setup(monkeypatch, allowed="acme.com")

        from app.compliance import enforce_email_compliance

        with pytest.raises(HTTPException) as exc_info:
            enforce_email_compliance("user@gmail.com")
        assert exc_info.value.status_code == 403
        assert "restricted" in exc_info.value.detail.lower()

    def test_passes_when_in_allowlist(self, monkeypatch):
        _setup(monkeypatch, allowed="acme.com")

        from app.compliance import enforce_email_compliance

        enforce_email_compliance("user@acme.com")

    # ------------------------------------------------------------------
    # Allowlist + blocklist combinations
    # ------------------------------------------------------------------

    def test_in_allowlist_and_in_blocklist_still_blocked(self, monkeypatch):
        """Blocklist is evaluated after allowlist — both must pass."""
        _setup(monkeypatch, allowed="acme.com", blocked=".com")

        from app.compliance import enforce_email_compliance

        with pytest.raises(HTTPException):
            enforce_email_compliance("user@acme.com")

    def test_in_allowlist_not_in_blocklist_passes(self, monkeypatch):
        """Allowlist pass + blocklist pass = allowed."""
        _setup(monkeypatch, allowed="acme.com", blocked=".xx")

        from app.compliance import enforce_email_compliance

        enforce_email_compliance("user@acme.com")

    def test_not_in_allowlist_not_in_blocklist_rejected(self, monkeypatch):
        """When allowlist is active, missing from it = 503 even if blocklist is empty."""
        _setup(monkeypatch, allowed="acme.com", blocked="")

        from app.compliance import enforce_email_compliance

        with pytest.raises(HTTPException) as exc_info:
            enforce_email_compliance("user@other.com")
        assert exc_info.value.status_code == 403

    def test_not_in_allowlist_also_in_blocklist_rejected(self, monkeypatch):
        """Fails both filters — rejected by allowlist first."""
        _setup(monkeypatch, allowed="acme.com", blocked=".xx")

        from app.compliance import enforce_email_compliance

        with pytest.raises(HTTPException):
            enforce_email_compliance("user@provider.xx")

    def test_both_empty_allows_everything(self, monkeypatch):
        """Default state — no restrictions at all."""
        _setup(monkeypatch, allowed="", blocked="")

        from app.compliance import enforce_email_compliance

        enforce_email_compliance("user@literally-anything.xx")
        enforce_email_compliance("user@gmail.com")

    def test_only_blocklist_set_blocks_match_allows_rest(self, monkeypatch):
        """No allowlist, just blocklist — only matching domains blocked."""
        _setup(monkeypatch, allowed="", blocked=".xx")

        from app.compliance import enforce_email_compliance

        with pytest.raises(HTTPException):
            enforce_email_compliance("user@provider.xx")
        enforce_email_compliance("user@gmail.com")

    def test_only_allowlist_set_rejects_unlisted(self, monkeypatch):
        """No blocklist, just allowlist — unlisted domains rejected."""
        _setup(monkeypatch, allowed="acme.com")

        from app.compliance import enforce_email_compliance

        enforce_email_compliance("user@acme.com")
        with pytest.raises(HTTPException):
            enforce_email_compliance("user@gmail.com")

    def test_multiple_allowed_domains(self, monkeypatch):
        """Multiple domains in allowlist all pass."""
        _setup(monkeypatch, allowed="acme.com,partner.org,corp.net")

        from app.compliance import enforce_email_compliance

        enforce_email_compliance("user@acme.com")
        enforce_email_compliance("user@partner.org")
        enforce_email_compliance("user@corp.net")
        with pytest.raises(HTTPException):
            enforce_email_compliance("user@outsider.com")

    def test_allowlist_exact_blocklist_suffix_independent(self, monkeypatch):
        """Allowlist is exact match, blocklist is suffix — they don't cross-contaminate."""
        _setup(monkeypatch, allowed="safe.xx", blocked=".xx")

        from app.compliance import enforce_email_compliance

        # In allowlist but also matches blocklist suffix — blocked
        with pytest.raises(HTTPException):
            enforce_email_compliance("user@safe.xx")

    def test_allowlist_subdomain_not_matched(self, monkeypatch):
        """Allowlist is exact — sub.acme.com does not match acme.com."""
        _setup(monkeypatch, allowed="acme.com")

        from app.compliance import enforce_email_compliance

        with pytest.raises(HTTPException):
            enforce_email_compliance("user@sub.acme.com")

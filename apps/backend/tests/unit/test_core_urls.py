"""Tests for the shared, versioned URL canonicalization boundary."""

import hashlib

import pytest

from contentos.core.urls import (
    TRACKING_PARAMETER_PREFIXES,
    TRACKING_PARAMETERS,
    URL_CANONICALIZATION_VERSION,
    CanonicalUrl,
    InvalidUrlError,
    canonical_url_hash,
    canonicalize_url,
)
from contentos.sources.urls import normalize_base_url


def canonical(url: str) -> str:
    return canonicalize_url(url).url


class TestValidation:
    def test_http_and_https_are_accepted(self) -> None:
        assert canonical("http://example.com") == "http://example.com/"
        assert canonical("https://example.com") == "https://example.com/"

    @pytest.mark.parametrize(
        "invalid_url",
        [
            "",
            "   ",
            "/relative/path",
            "example.com/page",
            "ftp://example.com/file",
            "file:///etc/passwd",
            "javascript:alert(1)",
            "https://",
            "https:///path-without-host",
        ],
    )
    def test_relative_malformed_and_unsupported_urls_are_rejected(self, invalid_url: str) -> None:
        with pytest.raises(InvalidUrlError):
            canonicalize_url(invalid_url)

    def test_embedded_credentials_are_rejected_without_echoing_them(self) -> None:
        with pytest.raises(InvalidUrlError) as info:
            canonicalize_url("https://user:hunter2-secret@example.com/page")

        assert "hunter2-secret" not in str(info.value)
        assert "user" not in str(info.value)

    def test_invalid_port_is_rejected(self) -> None:
        with pytest.raises(InvalidUrlError):
            canonicalize_url("https://example.com:notaport/page")


class TestSchemeHostAndPorts:
    def test_scheme_and_host_are_lowercased(self) -> None:
        assert canonical("HTTPS://ExAmPlE.CoM/Page") == "https://example.com/Page"

    def test_internationalized_hostnames_are_lowercased_not_transformed(self) -> None:
        assert canonical("https://Örnek.example/yol") == "https://örnek.example/yol"

    def test_default_ports_are_removed(self) -> None:
        assert canonical("http://example.com:80/a") == "http://example.com/a"
        assert canonical("https://example.com:443/a") == "https://example.com/a"

    def test_non_default_ports_are_preserved(self) -> None:
        assert canonical("https://example.com:8443/a") == "https://example.com:8443/a"
        assert canonical("http://example.com:443/a") == "http://example.com:443/a"


class TestFragmentsAndPaths:
    def test_fragment_is_always_removed(self) -> None:
        assert canonical("https://example.com/page#section-2") == "https://example.com/page"
        assert canonical("https://example.com/page#a") == canonical("https://example.com/page#b")

    def test_empty_path_becomes_root(self) -> None:
        assert canonical("https://example.com") == "https://example.com/"
        assert canonical("https://example.com/") == "https://example.com/"

    def test_non_root_trailing_slash_is_removed(self) -> None:
        assert canonical("https://example.com/haber/") == "https://example.com/haber"
        assert canonical("https://example.com/a/b//") == "https://example.com/a/b"

    def test_meaningful_path_case_and_segments_are_preserved(self) -> None:
        assert (
            canonical("https://example.com/Kategori/Alt-Konu/42")
            == "https://example.com/Kategori/Alt-Konu/42"
        )

    def test_percent_encoded_path_is_not_destructively_decoded(self) -> None:
        assert canonical("https://example.com/a%2Fb") == "https://example.com/a%2Fb"
        assert canonical("https://example.com/yaz%C4%B1") == "https://example.com/yaz%C4%B1"


class TestQueryHandling:
    def test_parameter_order_is_normalized(self) -> None:
        assert canonical("https://example.com/p?a=1&b=2") == canonical(
            "https://example.com/p?b=2&a=1"
        )

    def test_duplicate_keys_are_preserved_in_deterministic_order(self) -> None:
        assert canonical("https://example.com/p?a=2&a=1") == "https://example.com/p?a=1&a=2"
        assert canonical("https://example.com/p?a=1&a=2") == "https://example.com/p?a=1&a=2"

    def test_blank_values_are_preserved(self) -> None:
        assert canonical("https://example.com/p?filter=&sort=date") == (
            "https://example.com/p?filter=&sort=date"
        )

    def test_unknown_parameters_are_preserved(self) -> None:
        assert canonical("https://example.com/p?page=3&custom=x") == (
            "https://example.com/p?custom=x&page=3"
        )

    @pytest.mark.parametrize(
        "tracking_query",
        [
            "utm_source=news&utm_medium=social&utm_campaign=x",
            "utm_term=a&utm_content=b&utm_id=c",
            "UTM_SOURCE=case-insensitive",
            "gclid=abc123",
            "fbclid=def456",
            "msclkid=ghi789",
        ],
    )
    def test_tracking_only_query_disappears_cleanly(self, tracking_query: str) -> None:
        assert canonical(f"https://example.com/p?{tracking_query}") == "https://example.com/p"

    def test_meaningful_parameters_survive_tracking_removal(self) -> None:
        assert (
            canonical("https://example.com/p?utm_source=x&page=2&gclid=y&q=kahve")
            == "https://example.com/p?page=2&q=kahve"
        )

    def test_percent_encoded_query_values_are_deterministic(self) -> None:
        space_encoded = canonical("https://example.com/p?q=t%C3%BCrk%20kahvesi")
        plus_encoded = canonical("https://example.com/p?q=t%C3%BCrk+kahvesi")

        assert space_encoded == plus_encoded
        assert space_encoded == "https://example.com/p?q=t%C3%BCrk+kahvesi"

    def test_tracking_policy_is_transparent(self) -> None:
        assert TRACKING_PARAMETER_PREFIXES == ("utm_",)
        assert TRACKING_PARAMETERS == frozenset({"gclid", "fbclid", "msclkid"})


class TestVersionAndResult:
    def test_version_one_is_recorded_on_results(self) -> None:
        result = canonicalize_url("https://example.com/page")

        assert URL_CANONICALIZATION_VERSION == 1
        assert result == CanonicalUrl(url="https://example.com/page", version=1)


class TestHashing:
    def test_hash_is_unsalted_sha256_of_utf8_canonical_url(self) -> None:
        url = canonical("https://example.com/yaz%C4%B1?page=2")

        assert canonical_url_hash(url) == hashlib.sha256(url.encode("utf-8")).hexdigest()
        assert len(canonical_url_hash(url)) == 64
        assert canonical_url_hash(url) == canonical_url_hash(url)

    def test_equivalent_urls_share_a_hash(self) -> None:
        variants = [
            "https://example.com/p?b=2&a=1#top",
            "HTTPS://EXAMPLE.com:443/p?a=1&utm_source=x&b=2",
            "https://example.com/p/?a=1&b=2&fbclid=zzz",
        ]

        hashes = {canonical_url_hash(canonical(variant)) for variant in variants}
        assert len(hashes) == 1

    def test_semantically_different_urls_hash_differently(self) -> None:
        first = canonical_url_hash(canonical("https://example.com/p?page=1"))
        second = canonical_url_hash(canonical("https://example.com/p?page=2"))

        assert first != second


class TestInvariants:
    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com",
            "http://Example.com:80/Haber/?utm_source=x#f",
            "https://example.com:8443/a/b?z=1&a=2&a=1",
            "https://example.com/p?q=t%C3%BCrk+kahvesi&utm_id=7",
            "https://örnek.example/yol/?b=&a=1",
        ],
    )
    def test_canonicalization_is_idempotent(self, url: str) -> None:
        once = canonicalize_url(url)
        twice = canonicalize_url(once.url)

        assert twice.url == once.url
        assert twice.version == once.version

    def test_only_syntax_affects_identity(self) -> None:
        base = canonical("https://example.com/p?a=1&b=2")

        assert canonical("https://example.com/p?b=2&a=1") == base
        assert canonical("https://example.com/p?a=1&b=2#fragment") == base
        assert canonical("https://example.com/p?utm_medium=m&a=1&b=2") == base
        assert canonical("https://example.com/p?b=2&utm_source=s&a=1#x") == base


class TestSourceNormalizerRemainsIndependent:
    def test_source_registration_identity_contract_is_unchanged(self) -> None:
        # Intentionally different contracts: Source registration identity keeps
        # no root slash and an untouched query; the shared canonicalizer uses
        # a root slash and tracking-free sorted queries.
        assert normalize_base_url("https://example.com/") == "https://example.com"
        assert canonical("https://example.com/") == "https://example.com/"

        assert (
            normalize_base_url("https://example.com/feed?b=2&a=1&utm_source=x")
            == "https://example.com/feed?b=2&a=1&utm_source=x"
        )
        assert (
            canonical("https://example.com/feed?b=2&a=1&utm_source=x")
            == "https://example.com/feed?a=1&b=2"
        )

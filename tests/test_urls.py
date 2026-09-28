from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

from indeed_scraper import build_search_url, country_for_host, first_page_url, indeed_host


def params(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query, keep_blank_values=True).items()}


def test_basic_search_url():
    url = build_search_url("python developer", "Austin, TX")
    parts = urlsplit(url)
    assert parts.scheme == "https"
    assert parts.hostname == "www.indeed.com"
    assert parts.path == "/jobs"
    assert params(url) == {"q": "python developer", "l": "Austin, TX"}


def test_all_filters():
    url = build_search_url(
        "data analyst",
        "New York, NY",
        sort="date",
        days=3,
        job_type="contract",
        remote=True,
        radius=25,
        job_key="abc123",
    )
    assert params(url) == {
        "q": "data analyst",
        "l": "New York, NY",
        "sort": "date",
        "fromage": "3",
        "jt": "contract",
        "sc": "0kf:attr(DSQF7);",
        "radius": "25",
        "vjk": "abc123",
    }


def test_relevance_is_indeeds_default_so_it_adds_no_param():
    assert "sort" not in params(build_search_url("nurse", sort="relevance"))


def test_location_only_search_is_allowed():
    assert params(build_search_url("", "Chicago, IL")) == {"q": "", "l": "Chicago, IL"}


@pytest.mark.parametrize(
    ("country", "host"),
    [
        ("US", "www.indeed.com"),
        ("GB", "uk.indeed.com"),
        ("uk", "uk.indeed.com"),
        ("CA", "ca.indeed.com"),
        ("de", "de.indeed.com"),
    ],
)
def test_country_sites(country, host):
    assert indeed_host(country) == host
    assert urlsplit(build_search_url("nurse", country=country)).hostname == host


@pytest.mark.parametrize(
    ("host", "country"),
    [
        ("www.indeed.com", "US"),
        ("indeed.com", "US"),
        ("uk.indeed.com", "GB"),
        ("ca.indeed.com", "CA"),
        ("AU.indeed.com", "AU"),
    ],
)
def test_country_for_host(host, country):
    assert country_for_host(host) == country


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sort": "salary"},
        {"days": 5},
        {"job_type": "gig"},
        {"radius": -1},
        {"country": "USA"},
        {"country": "1X"},
    ],
)
def test_invalid_filters_raise(kwargs):
    with pytest.raises(ValueError):
        build_search_url("nurse", **kwargs)


def test_empty_search_raises():
    with pytest.raises(ValueError):
        build_search_url("  ", "")


def test_first_page_url_drops_start_and_keeps_filters():
    url = first_page_url("http://www.indeed.com/jobs?q=nurse&l=Chicago&start=20&fromage=7")
    assert url.startswith("https://www.indeed.com/jobs?")
    assert params(url) == {"q": "nurse", "l": "Chicago", "fromage": "7"}


def test_first_page_url_keeps_country_site():
    url = first_page_url("https://uk.indeed.com/jobs?q=data+analyst&l=London")
    assert urlsplit(url).hostname == "uk.indeed.com"


@pytest.mark.parametrize(
    "url",
    ["https://example.com/jobs?q=x", "ftp://www.indeed.com/jobs", "https://notindeed.com/jobs"],
)
def test_first_page_url_rejects_other_sites(url):
    with pytest.raises(ValueError):
        first_page_url(url)

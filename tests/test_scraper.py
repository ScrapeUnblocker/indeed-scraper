from __future__ import annotations

import csv
import json
from urllib.parse import parse_qs, urlsplit

import pytest
from conftest import (
    CHALLENGE_HTML,
    RECOMMENDED_TIER,
    SIGN_IN_HTML,
    make_card,
    make_details_body,
    make_page_html,
    related_tier,
)

from indeed_scraper import IndeedBlockedError, IndeedScraper, Job, to_csv, to_json

SEARCH = "https://www.indeed.com/jobs?q=python+developer&l=Austin%2C+TX"


class Transient(Exception):
    """Stand-in for a retryable ScrapeUnblocker error."""


class Fatal(Exception):
    """Stand-in for a non-retryable error (e.g. a bad API key)."""


class FakeClient:
    """Mimics ``scrapeunblocker.Client.get_page_source`` with scripted responses."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[tuple[str, str | None]] = []

    def get_page_source(self, url, proxy_country=None):
        self.calls.append((url, proxy_country))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    def params(self, n=-1):
        return {k: v[0] for k, v in parse_qs(urlsplit(self.calls[n][0]).query).items()}


def cards(*keys, **overrides):
    return [make_card(jobkey=k, **overrides) for k in keys]


def make_scraper(responses, **kwargs):
    client = FakeClient(responses)
    delays: list[float] = []
    scraper = IndeedScraper(
        client=client, transient_errors=(Transient,), sleep=delays.append, **kwargs
    )
    return scraper, client, delays


def test_keeps_direct_matches_by_default():
    page = make_page_html(
        cards("a1", "a2")
        + cards("r1", sponsored=True, tier=related_tier())
        + cards("x1", tier=RECOMMENDED_TIER)
    )
    scraper, client, _ = make_scraper([page])
    jobs = scraper.scrape_url(SEARCH)
    assert [j.job_key for j in jobs] == ["a1", "a2"]
    assert len(client.calls) == 1


def test_include_related_keeps_every_card():
    page = make_page_html(cards("a1") + cards("r1", sponsored=True, tier=related_tier()))
    scraper, _, _ = make_scraper([page])
    jobs = scraper.scrape_url(SEARCH, include_related=True)
    assert [(j.job_key, j.match_type) for j in jobs] == [("a1", "search"), ("r1", "related")]
    assert jobs[1].related_group == "Jobs in mobile app development"


def test_no_sponsored_drops_sponsored_matches():
    page = make_page_html(cards("a1") + cards("s1", sponsored=True))
    scraper, _, _ = make_scraper([page])
    assert [j.job_key for j in scraper.scrape_url(SEARCH, include_sponsored=False)] == ["a1"]


def test_no_match_returns_empty_list():
    page = make_page_html(cards("x1", "x2", tier=RECOMMENDED_TIER), total=0)
    scraper, _, _ = make_scraper([page, page])
    assert scraper.scrape_url(SEARCH) == []
    # recommendations are still reachable on request
    assert [j.match_type for j in scraper.scrape_url(SEARCH, include_related=True)] == [
        "recommended",
        "recommended",
    ]


def test_stamps_the_search_on_every_job():
    page = make_page_html(cards("a1"), what="nurse", where="Chicago, IL")
    scraper, _, _ = make_scraper([page])
    job = scraper.scrape_url(SEARCH)[0]
    assert (job.search_query, job.search_location) == ("nurse", "Chicago, IL")


def test_limit_and_duplicate_cards():
    page = make_page_html(cards("a1", "a1", "a2", "a3"))
    scraper, _, _ = make_scraper([page])
    assert [j.job_key for j in scraper.scrape_url(SEARCH, limit=2)] == ["a1", "a2"]


def test_requests_the_first_page_only():
    scraper, client, _ = make_scraper([make_page_html(cards("a1"))])
    scraper.scrape_url(SEARCH + "&start=30&fromage=7")
    assert "start" not in client.params()
    assert client.params()["fromage"] == "7"


def test_routes_through_us_unless_told_otherwise():
    scraper, client, _ = make_scraper([make_page_html(cards("a1"))] * 3)
    scraper.scrape_url("https://uk.indeed.com/jobs?q=data+analyst")
    scraper.scrape_url(SEARCH)
    scraper.scrape_url(SEARCH, proxy_country="DE")
    assert [country for _, country in client.calls] == ["US", "US", "DE"]


def test_retries_transient_errors_with_doubling_backoff():
    retries = []
    scraper, client, delays = make_scraper(
        [Transient("timeout"), Transient("timeout"), make_page_html(cards("a1"))],
        on_retry=lambda attempt, delay, err: retries.append(attempt),
    )
    assert [j.job_key for j in scraper.scrape_url(SEARCH)] == ["a1"]
    assert len(client.calls) == 3
    assert delays == [3.0, 6.0]
    assert retries == [1, 2]


@pytest.mark.parametrize("html", [CHALLENGE_HTML, SIGN_IN_HTML, "<html>interstitial</html>"])
def test_retries_block_and_empty_pages(html):
    scraper, client, _ = make_scraper([html, make_page_html(cards("a1"))])
    assert len(scraper.scrape_url(SEARCH)) == 1
    assert len(client.calls) == 2


def test_backoff_is_capped():
    scraper, _, delays = make_scraper(
        [Transient()] * 4 + [make_page_html(cards("a1"))], retries=4, backoff=10, max_backoff=25
    )
    scraper.scrape_url(SEARCH)
    assert delays == [10, 20, 25, 25]


def test_gives_up_after_retries():
    scraper, client, _ = make_scraper([CHALLENGE_HTML] * 3, retries=2)
    with pytest.raises(IndeedBlockedError):
        scraper.scrape_url(SEARCH)
    assert len(client.calls) == 3


def test_non_transient_errors_are_not_retried():
    scraper, client, _ = make_scraper([Fatal("bad key")])
    with pytest.raises(Fatal):
        scraper.scrape_url(SEARCH)
    assert len(client.calls) == 1


def test_search_many_runs_every_query_in_every_location_and_dedupes():
    pages = [
        make_page_html(cards("a1", "a2")),
        make_page_html(cards("a2", "a3")),
        make_page_html(cards("a3", "a4")),
        make_page_html(cards("a5")),
    ]
    scraper, client, _ = make_scraper(pages)
    jobs = scraper.search_many(
        ["data analyst", "data engineer"], ["New York, NY", "Remote"], days=7, sort="date"
    )
    assert [j.job_key for j in jobs] == ["a1", "a2", "a3", "a4", "a5"]
    searched = [(client.params(i)["q"], client.params(i)["l"]) for i in range(4)]
    assert searched == [
        ("data analyst", "New York, NY"),
        ("data analyst", "Remote"),
        ("data engineer", "New York, NY"),
        ("data engineer", "Remote"),
    ]
    assert all(client.params(i)["fromage"] == "7" for i in range(4))


def test_scrape_many_limit_stops_early():
    scraper, client, _ = make_scraper(
        [make_page_html(cards("a1", "a2")), make_page_html(cards("a3"))]
    )
    jobs = scraper.scrape_many([SEARCH, SEARCH + "&fromage=1"], limit=2)
    assert len(jobs) == 2
    assert len(client.calls) == 1


def test_search_builds_the_url_for_the_country_site():
    scraper, client, _ = make_scraper([make_page_html(cards("a1"))])
    scraper.search("registered nurse", "Toronto, ON", country="CA", job_type="fulltime")
    url, proxy = client.calls[0]
    assert urlsplit(url).hostname == "ca.indeed.com"
    assert client.params()["jt"] == "fulltime"
    assert proxy == "US"


def test_job_details():
    page = make_page_html(cards("zz"), details=make_details_body("a601cb49ef4ef3e1"))
    scraper, client, _ = make_scraper([page])
    details = scraper.job_details("a601cb49ef4ef3e1")
    assert details is not None and details.benefits == ["401(k)", "Health insurance"]
    assert client.params()["vjk"] == "a601cb49ef4ef3e1"


def test_job_details_refuses_another_jobs_posting():
    page = make_page_html(cards("zz"), details=make_details_body("some-other-job"))
    scraper, _, _ = make_scraper([page])
    assert scraper.job_details("a601cb49ef4ef3e1") is None


def test_details_flag_enriches_every_job():
    search = make_page_html(cards("k1", "k2"))
    detail_1 = make_page_html(cards("zz"), details=make_details_body("k1"))
    detail_2 = make_page_html(cards("zz"), details=make_details_body("gone"))
    scraper, client, _ = make_scraper([search, detail_1, detail_2])
    jobs = scraper.scrape_url(SEARCH, details=True)
    assert jobs[0].description.startswith("About the role")
    assert jobs[0].company_logo == "https://images.example.com/logo.png"
    assert jobs[1].description is None  # posting could not be opened, left as listed
    assert [client.params(i).get("vjk") for i in range(3)] == [None, "k1", "k2"]


def test_enrich_reports_each_job():
    detail = make_page_html(cards("zz"), details=make_details_body("k1"))
    scraper, _, _ = make_scraper([detail])
    seen = []
    scraper.enrich([Job(job_key="k1")], on_details=lambda job, d: seen.append((job.job_key, d)))
    assert seen[0][0] == "k1" and seen[0][1] is not None


def test_json_and_csv_export(tmp_path):
    scraper, _, _ = make_scraper(
        [make_page_html(cards("a1", "a2", jobTypes=["Full-time", "Contract"]))]
    )
    jobs = scraper.scrape_url(SEARCH)

    data = json.loads(to_json(jobs))
    assert data[0]["job_key"] == "a1"
    assert data[0]["salary_min"] == 120000

    path = tmp_path / "jobs.csv"
    to_csv(jobs, str(path))
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 2
    assert rows[0]["job_types"] == "Full-time | Contract"
    assert rows[0]["title"] == "Python Developer"

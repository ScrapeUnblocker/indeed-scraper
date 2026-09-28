from __future__ import annotations

import pytest
from conftest import (
    CHALLENGE_HTML,
    NEARBY_TIER,
    RECOMMENDED_TIER,
    SIGN_IN_HTML,
    make_card,
    make_details_body,
    make_page_html,
    related_tier,
)

from indeed_scraper import (
    IndeedBlockedError,
    IndeedParseError,
    Job,
    apply_details,
    html_to_text,
    normalize_job,
    parse_job_details,
    parse_search_page,
)
from indeed_scraper.scraper import pub_date, salary_period


def test_normalize_full_card(card):
    job = normalize_job(card)
    assert job.job_key == "a601cb49ef4ef3e1"
    assert job.title == "Python Developer"
    assert job.company == "Example Labs"
    assert job.company_url == "https://www.indeed.com/cmp/Example-Labs"  # tracking dropped
    assert job.company_rating == 4.6
    assert job.company_review_count == 91
    assert job.location == "Austin, TX 78701"
    assert (job.city, job.state, job.postal_code, job.country) == ("Austin", "TX", "78701", "US")
    assert job.work_setting == "Hybrid work"
    assert job.remote is False
    assert job.salary_text == "$120,000 - $150,000 a year"
    assert (job.salary_min, job.salary_max) == (120000, 150000)
    assert job.salary_period == "year"
    assert job.salary_currency == "USD"
    assert job.job_types == ["Full-time"]
    assert job.date_posted == "2026-09-24"
    assert job.posted_ago == "3 days ago"
    assert (job.sponsored, job.urgently_hiring, job.easy_apply) == (False, False, True)
    assert job.match_type == "search"
    assert job.related_group is None
    assert job.snippet == "Build Python APIs & services. Own the data pipeline."
    assert job.url == "https://www.indeed.com/viewjob?jk=a601cb49ef4ef3e1"


def test_urls_follow_the_country_site(card):
    job = normalize_job(card, host="uk.indeed.com")
    assert job.url == "https://uk.indeed.com/viewjob?jk=a601cb49ef4ef3e1"
    assert job.company_url == "https://uk.indeed.com/cmp/Example-Labs"


def test_missing_salary_drops_the_stray_currency():
    job = normalize_job(
        make_card(salarySnippet={"currency": "CAD", "salaryTextFormatted": False})
        | {"extractedSalary": None}
    )
    assert job.salary_text is None
    assert job.salary_min is None and job.salary_max is None
    assert job.salary_period is None
    assert job.salary_currency is None


def test_open_ended_salary():
    job = normalize_job(
        make_card(
            salarySnippet={"currency": "USD", "text": "From $80,000 a year"},
            extractedSalary={"max": -1, "min": 80000, "type": "YEARLY"},
        )
    )
    assert (job.salary_min, job.salary_max, job.salary_period) == (80000, None, "year")


def test_hourly_salary_keeps_decimals():
    job = normalize_job(
        make_card(
            salarySnippet={"currency": "USD", "text": "$37.52 - $84.22 an hour"},
            extractedSalary={"max": 84.22, "min": 37.52, "type": "HOURLY"},
        )
    )
    assert (job.salary_min, job.salary_max, job.salary_period) == (37.52, 84.22, "hour")


def test_zero_rating_means_no_rating():
    job = normalize_job(make_card(companyRating=0, companyReviewCount=0))
    assert job.company_rating is None
    assert job.company_review_count is None


def test_remote_job():
    job = normalize_job(
        make_card(
            formattedLocation="Remote",
            jobLocationCity="Remote",
            jobLocationState=None,
            jobLocationPostal=None,
            remoteLocation=True,
            remoteWorkModel={"text": "Remote", "type": "REMOTE_ALWAYS"},
        )
    )
    assert job.remote is True
    assert job.work_setting == "Remote"
    assert job.city is None


def test_missing_company_link_and_flags():
    job = normalize_job(make_card(companyOverviewLink=None, sponsored=True, urgentlyHiring=True))
    assert job.company_url is None
    assert job.sponsored is True
    assert job.urgently_hiring is True


@pytest.mark.parametrize(
    ("tier", "match_type", "group"),
    [
        ({"type": "DEFAULT"}, "search", None),
        (None, "search", None),
        (
            related_tier("Opportunities in web development"),
            "related",
            "Opportunities in web development",
        ),
        (NEARBY_TIER, "nearby", None),
        (RECOMMENDED_TIER, "recommended", None),
        ({"type": "SOMETHING_NEW", "rawType": "x"}, "related", None),
    ],
)
def test_match_types(tier, match_type, group):
    job = normalize_job(make_card(tier=tier))
    assert job.match_type == match_type
    assert job.related_group == group


def test_parse_search_page():
    html = make_page_html(
        [
            make_card(jobkey="a1"),
            make_card(jobkey="a2", sponsored=True),
            make_card(jobkey="r1", sponsored=True, tier=related_tier()),
        ],
        details=make_details_body("a1"),
    )
    page = parse_search_page(html, url="https://www.indeed.com/jobs?q=python+developer")
    assert [j.job_key for j in page.jobs] == ["a1", "a2", "r1"]
    assert [j.match_type for j in page.jobs] == ["search", "search", "related"]
    assert page.query == "python developer"
    assert page.location == "Austin, TX"
    assert page.total == 2431
    assert page.country == "US"
    assert page.no_match is False
    assert page.details is not None and page.details.job_key == "a1"


def test_parse_country_site_page():
    html = make_page_html([make_card(country="GB")])
    page = parse_search_page(html, url="https://uk.indeed.com/jobs?q=data+analyst")
    assert page.country == "GB"
    assert page.jobs[0].url.startswith("https://uk.indeed.com/viewjob?jk=")


def test_no_match_page():
    html = make_page_html([make_card(tier=RECOMMENDED_TIER)], total=0)
    page = parse_search_page(html)
    assert page.no_match is True
    assert page.jobs[0].match_type == "recommended"


def test_total_falls_back_to_title_bar():
    html = make_page_html([make_card()], total=None).replace(
        '{"country": "US"}', '{"country": "US", "searchTitleBarModel": {"totalNumResults": 77}}'
    )
    assert parse_search_page(html).total == 77


@pytest.mark.parametrize("html", [SIGN_IN_HTML, CHALLENGE_HTML])
def test_block_pages_raise_blocked(html):
    with pytest.raises(IndeedBlockedError):
        parse_search_page(html)


def test_page_without_data_raises_parse_error():
    with pytest.raises(IndeedParseError) as info:
        parse_search_page("<html><body>Something else</body></html>")
    assert not isinstance(info.value, IndeedBlockedError)


def test_parse_job_details():
    details = parse_job_details({"autoOpenTwoPaneViewjobResponse": {"body": make_details_body()}})
    assert details is not None
    assert details.job_key == "a601cb49ef4ef3e1"
    assert details.title == "Python Developer"
    assert details.company == "Example Labs"
    assert details.company_url == "https://www.indeed.com/cmp/Example-Labs"
    assert (details.company_rating, details.company_review_count) == (4.6, 91)
    assert details.company_logo == "https://images.example.com/logo.png"
    assert details.work_setting == "Hybrid work"
    assert (details.salary_min, details.salary_max, details.salary_period) == (
        120000,
        150000,
        "year",
    )
    assert details.salary_currency == "USD"
    assert details.job_types == ["Full-time"]
    assert details.benefits == ["401(k)", "Health insurance"]
    assert (
        details.description == "About the role\n\nBuild APIs.\n\n- Python 3\n- PostgreSQL & Redis"
    )
    assert details.description_html.startswith("<div>")
    assert details.expired is False
    assert details.url == "https://www.indeed.com/viewjob?jk=a601cb49ef4ef3e1"


def test_parse_job_details_absent():
    assert parse_job_details({}) is None
    assert parse_job_details({"autoOpenTwoPaneViewjobResponse": {"body": {}}}) is None


def test_apply_details_fills_gaps_without_overwriting():
    details = parse_job_details({"autoOpenTwoPaneViewjobResponse": {"body": make_details_body()}})
    bare = Job(job_key="a601cb49ef4ef3e1", title="Python Developer")
    apply_details(bare, details)
    assert bare.description.startswith("About the role")
    assert bare.benefits == ["401(k)", "Health insurance"]
    assert bare.company_logo == "https://images.example.com/logo.png"
    assert bare.salary_text == "$120,000 - $150,000 a year"
    assert bare.salary_period == "year"
    assert bare.job_types == ["Full-time"]
    assert bare.company_rating == 4.6

    listed = normalize_job(make_card(extractedSalary={"min": 1, "max": 2, "type": "HOURLY"}))
    apply_details(listed, details)
    assert (listed.salary_min, listed.salary_max, listed.salary_period) == (1, 2, "hour")


def test_html_to_text():
    assert html_to_text("<p>One&nbsp;two</p><p></p><p></p><ul><li>a</li><li>b</li></ul>") == (
        "One two\n\n- a\n- b"
    )
    assert html_to_text("") is None
    assert html_to_text(None) is None


def test_pub_date_and_salary_period():
    assert pub_date(1790226000000) == "2026-09-24"
    assert pub_date(0) is None
    assert pub_date(None) is None
    assert salary_period("MONTHLY") == "month"
    assert salary_period(None) is None

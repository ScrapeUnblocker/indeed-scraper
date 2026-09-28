"""indeed-scraper - clean Indeed job listings via the ScrapeUnblocker API.

Search Indeed for any keywords and location and get clean, typed JSON for every
job: job key, title, company, company rating, location (city / state / postal
code), remote or hybrid setting, salary text plus min / max / period /
currency, job types, publication date, sponsored / urgently-hiring / "easily
apply" flags, snippet and URL, plus optional full postings (description,
benefits, company logo). Pages are loaded in a real browser through the
ScrapeUnblocker ``getPageSource`` API and read from the structured data Indeed
embeds in each results page, so there are no CSS selectors to maintain.

Example:
    >>> from indeed_scraper import IndeedScraper
    >>> scraper = IndeedScraper()                                # reads SCRAPEUNBLOCKER_KEY
    >>> jobs = scraper.search("python developer", "Remote", days=7)   # doctest: +SKIP
    >>> jobs[0].salary_min, jobs[0].salary_period                  # doctest: +SKIP
    (70000, 'year')
"""

from __future__ import annotations

from .scraper import (
    DAYS_POSTED,
    DEFAULT_PROXY_COUNTRY,
    FIELDNAMES,
    JOB_TYPES,
    MATCH_TYPES,
    SORTS,
    IndeedBlockedError,
    IndeedParseError,
    IndeedScraper,
    Job,
    JobDetails,
    SearchPage,
    apply_details,
    build_search_url,
    country_for_host,
    first_page_url,
    html_to_text,
    indeed_host,
    jobs_to_dicts,
    normalize_job,
    parse_job_details,
    parse_search_page,
    to_csv,
    to_json,
)

__all__ = [
    "IndeedScraper",
    "Job",
    "JobDetails",
    "SearchPage",
    "IndeedParseError",
    "IndeedBlockedError",
    "build_search_url",
    "first_page_url",
    "indeed_host",
    "country_for_host",
    "parse_search_page",
    "parse_job_details",
    "normalize_job",
    "apply_details",
    "html_to_text",
    "jobs_to_dicts",
    "to_csv",
    "to_json",
    "FIELDNAMES",
    "SORTS",
    "DAYS_POSTED",
    "DEFAULT_PROXY_COUNTRY",
    "JOB_TYPES",
    "MATCH_TYPES",
]

__version__ = "0.1.0"

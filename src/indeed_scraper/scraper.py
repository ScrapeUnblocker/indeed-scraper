"""Core scraping logic for indeed-scraper.

Each Indeed search page is fetched through the ScrapeUnblocker ``getPageSource``
API, which loads it in a real browser and returns the HTML. Indeed renders its
result list from JSON it embeds in the page (the ``mosaic-provider-jobcards``
data block), so instead of scraping fragile CSS selectors this module reads that
object and normalizes every job card into a clean, stable :class:`Job` shape.

The same page also embeds the full posting of one job (the one Indeed opens in
its side panel). Adding ``vjk=<job key>`` to a search URL makes that any job you
choose, which is how :meth:`IndeedScraper.job_details` gets the full
description, benefits and company logo without a separate job page.

What the embedded data gives you that the visible cards do not:

* a structured salary (``salary_min`` / ``salary_max`` / ``salary_period`` /
  ``salary_currency``) next to Indeed's display text;
* the publication date, not just "3 days ago";
* city / state / postal code, the remote or hybrid setting, job types, the
  company rating and review count, and the sponsored / urgently-hiring /
  "easily apply" flags;
* Indeed's own total match count and the section every card belongs to.

Sections matter: a US results page mixes the jobs that match your search with
sponsored groups of *related* jobs ("Jobs in mobile app development"), sponsored
jobs from nearby locations, and "recommended" filler when a search matches
little or nothing. Every job carries ``match_type`` (``"search"``,
``"related"``, ``"nearby"`` or ``"recommended"``) and, by default, only direct
matches (``"search"``) are kept.

Indeed shows signed-out visitors the first results page only (asking for page 2
redirects to a sign-in page), so one search returns up to about 15 direct
matches. To collect more, combine several queries and locations with
:meth:`IndeedScraper.search_many`, which de-duplicates by job key.
"""

from __future__ import annotations

import csv
import html as html_lib
import json
import re
import time
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

DEFAULT_COUNTRY = "US"

# Indeed's country sites list their own local jobs whoever visits them, so every
# site is fetched through a US route unless you choose another one.
DEFAULT_PROXY_COUNTRY = "US"

# Indeed runs one site per country: www.indeed.com for the US, uk.indeed.com for
# the United Kingdom and <country code>.indeed.com everywhere else.
_HOST_OVERRIDES = {"US": "www.indeed.com", "GB": "uk.indeed.com", "UK": "uk.indeed.com"}

SORTS: tuple[str, ...] = ("relevance", "date")
# Indeed's "Date posted" filter (`fromage`): last 24 hours, 3, 7 or 14 days.
DAYS_POSTED: tuple[int, ...] = (1, 3, 7, 14)
# Indeed's "Job type" filter (`jt`).
JOB_TYPES: tuple[str, ...] = ("fulltime", "parttime", "contract", "temporary", "internship")
# Indeed's "Remote" work-setting filter, as its own search URLs encode it.
_REMOTE_FILTER = "0kf:attr(DSQF7);"

# Indeed salary types -> the period a salary figure is paid per.
SALARY_PERIODS: dict[str, str] = {
    "HOURLY": "hour",
    "DAILY": "day",
    "WEEKLY": "week",
    "MONTHLY": "month",
    "YEARLY": "year",
}

MATCH_TYPES: tuple[str, ...] = ("search", "related", "nearby", "recommended")

_JOBCARDS_RE = re.compile(r'window\.mosaic\.providerData\["mosaic-provider-jobcards"\]\s*=\s*')
_INITIAL_DATA_RE = re.compile(r"window\._initialData\s*=\s*")
# Indeed's sign-in page (what signed-out visitors get for results page 2+).
_SIGN_IN_RE = re.compile(r'"pageCode"\s*:\s*"auth"|<title>\s*Sign In \| Indeed', re.IGNORECASE)
# Markers of a bot-check interstitial (never present on a results page).
_CHALLENGE_RE = re.compile(
    r"<title>\s*Just a moment\.\.\.|_cf_chl_opt|challenges\.cloudflare\.com|"
    r"/cdn-cgi/challenge-platform/h/",
    re.IGNORECASE,
)
_TAG_RE = re.compile(r"<[^>]+>")
_LIST_ITEM_RE = re.compile(r"<li\b[^>]*>", re.IGNORECASE)
_BLOCK_TAG_RE = re.compile(
    r"<(?:br|/?p|/?div|/?ul|/?ol|/?h[1-6]|/?tr|/?section|/?table)\b[^>]*>", re.IGNORECASE
)
_COUNTRY_CODE_RE = re.compile(r"[A-Za-z]{2}")


class IndeedParseError(RuntimeError):
    """The fetched page did not contain Indeed's embedded search data.

    Usually a transient interstitial page, and retried automatically. If it
    persists, Indeed may have changed its page layout.
    """


class IndeedBlockedError(IndeedParseError):
    """Indeed answered with a bot-check or sign-in page instead of results.

    Retried automatically (with backoff) like any other transient failure.
    """


def _transient_errors() -> tuple[type[BaseException], ...]:
    """Best-effort tuple of ScrapeUnblocker exceptions worth retrying.

    Imported lazily so the package is usable (and unit-testable) even when the
    ``scrapeunblocker`` SDK is not installed.
    """
    try:
        from scrapeunblocker import (  # type: ignore
            BlockedError,
            BrowserTimeoutError,
            RateLimitError,
            ScrapeTimeoutError,
            ServerError,
            UpstreamOutageError,
        )
        from scrapeunblocker import (
            ConnectionError as SUConnectionError,
        )
    except Exception:  # pragma: no cover - depends on SDK availability
        return ()
    return (
        UpstreamOutageError,
        RateLimitError,
        ScrapeTimeoutError,
        BrowserTimeoutError,
        BlockedError,
        ServerError,
        SUConnectionError,
    )


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #


@dataclass
class Job:
    """One Indeed job posting, as listed on a search results page.

    ``salary_min`` / ``salary_max`` are what the employer posted (or what Indeed
    extracted from the description), per ``salary_period`` (``"hour"``,
    ``"day"``, ``"week"``, ``"month"`` or ``"year"``). "From $80,000 a year"
    gives ``salary_min=80000`` and ``salary_max=None``. ``description``,
    ``benefits`` and ``company_logo`` are only filled in when details are
    requested. Missing values are ``None``, never empty strings.
    """

    job_key: str | None = None
    title: str | None = None
    company: str | None = None
    company_url: str | None = None
    company_rating: float | None = None
    company_review_count: int | None = None
    location: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country: str | None = None
    work_setting: str | None = None
    remote: bool | None = None
    salary_text: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_period: str | None = None
    salary_currency: str | None = None
    job_types: list[str] = field(default_factory=list)
    date_posted: str | None = None
    posted_ago: str | None = None
    sponsored: bool | None = None
    urgently_hiring: bool | None = None
    easy_apply: bool | None = None
    match_type: str | None = None
    related_group: str | None = None
    snippet: str | None = None
    url: str | None = None
    search_query: str | None = None
    search_location: str | None = None
    description: str | None = None
    benefits: list[str] = field(default_factory=list)
    company_logo: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Column order used for CSV export and dict serialization.
FIELDNAMES: tuple[str, ...] = tuple(Job.__dataclass_fields__)


@dataclass
class JobDetails:
    """The full posting Indeed shows in its side panel for one job."""

    job_key: str | None = None
    title: str | None = None
    company: str | None = None
    company_url: str | None = None
    company_rating: float | None = None
    company_review_count: int | None = None
    company_logo: str | None = None
    location: str | None = None
    work_setting: str | None = None
    salary_text: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_period: str | None = None
    salary_currency: str | None = None
    job_types: list[str] = field(default_factory=list)
    benefits: list[str] = field(default_factory=list)
    description: str | None = None
    description_html: str | None = None
    posted_ago: str | None = None
    expired: bool | None = None
    url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SearchPage:
    """One Indeed results page plus Indeed's own counters.

    ``jobs`` holds every card on the page, whatever its ``match_type``;
    ``details`` is the posting Indeed opened in its side panel (the ``vjk`` job
    when the URL names one).
    """

    jobs: list[Job]
    query: str | None = None
    location: str | None = None
    total: int | None = None
    country: str | None = None
    url: str | None = None
    details: JobDetails | None = None

    @property
    def no_match(self) -> bool:
        """``True`` when Indeed reports zero matches (any cards are recommendations)."""
        return self.total == 0


# --------------------------------------------------------------------------- #
# URLs
# --------------------------------------------------------------------------- #


def indeed_host(country: str = DEFAULT_COUNTRY) -> str:
    """Return the Indeed site for a 2-letter country code (``"GB"`` -> ``uk.indeed.com``)."""
    code = (country or DEFAULT_COUNTRY).strip()
    if not _COUNTRY_CODE_RE.fullmatch(code):
        raise ValueError(f"country must be a 2-letter code like US, GB or CA, not {country!r}")
    code = code.upper()
    return _HOST_OVERRIDES.get(code, f"{code.lower()}.indeed.com")


def country_for_host(host: str) -> str:
    """Return the 2-letter country code for an Indeed host (``uk.indeed.com`` -> ``"GB"``)."""
    host = (host or "").lower().split(":")[0]
    if host in ("indeed.com", "www.indeed.com"):
        return "US"
    prefix = host.split(".", 1)[0]
    if prefix == "uk":
        return "GB"
    if _COUNTRY_CODE_RE.fullmatch(prefix):
        return prefix.upper()
    return DEFAULT_COUNTRY


def build_search_url(
    query: str = "",
    location: str = "",
    *,
    country: str = DEFAULT_COUNTRY,
    sort: str | None = None,
    days: int | None = None,
    job_type: str | None = None,
    remote: bool = False,
    radius: int | None = None,
    job_key: str | None = None,
) -> str:
    """Build an Indeed search URL from keywords, a location and Indeed's filters.

    Args:
        query: Keywords (job title, skill or company), e.g. ``"python developer"``.
        location: City, state, postal code or ``"Remote"``. May be empty.
        country: Which Indeed site to search (``"US"``, ``"GB"``, ``"CA"``, ...).
        sort: ``"relevance"`` (Indeed's default) or ``"date"`` (newest first).
        days: Only jobs posted in the last 1, 3, 7 or 14 days.
        job_type: One of :data:`JOB_TYPES` (``"fulltime"``, ``"contract"``, ...).
        remote: Only remote jobs (Indeed's "Remote" filter).
        radius: Search radius around ``location``, in the site's distance unit
            (miles on indeed.com).
        job_key: Ask Indeed to open this job in its side panel (``vjk``), which
            embeds its full posting in the page.

    Raises:
        ValueError: on an unknown sort / job type, an unsupported ``days``
            value, a negative radius, or when both ``query`` and ``location``
            are empty (and no ``job_key`` is given).
    """
    query = (query or "").strip()
    location = (location or "").strip()
    if not query and not location and not job_key:
        raise ValueError("give a search query, a location, or both")
    params: dict[str, str] = {"q": query}
    if location:
        params["l"] = location
    if radius is not None:
        if int(radius) < 0:
            raise ValueError("radius must not be negative")
        params["radius"] = str(int(radius))
    if sort:
        if sort not in SORTS:
            raise ValueError(f"sort must be one of {', '.join(SORTS)}")
        if sort == "date":
            params["sort"] = "date"
    if days is not None:
        if int(days) not in DAYS_POSTED:
            raise ValueError(f"days must be one of {', '.join(map(str, DAYS_POSTED))}")
        params["fromage"] = str(int(days))
    if job_type:
        if job_type not in JOB_TYPES:
            raise ValueError(f"job_type must be one of {', '.join(JOB_TYPES)}")
        params["jt"] = job_type
    if remote:
        params["sc"] = _REMOTE_FILTER
    if job_key:
        params["vjk"] = job_key
    return f"https://{indeed_host(country)}/jobs?{urlencode(params)}"


def first_page_url(url: str) -> str:
    """Normalize a pasted Indeed search URL to its first results page.

    Indeed only shows the first page to signed-out visitors, so any ``start``
    offset is dropped (a later page would redirect to a sign-in page).

    Raises:
        ValueError: when ``url`` is not an Indeed URL.
    """
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not (
        host == "indeed.com" or host.endswith(".indeed.com")
    ):
        raise ValueError(f"not an Indeed URL: {url!r}")
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "start"]
    return urlunsplit(("https", parts.netloc, parts.path or "/jobs", urlencode(query), ""))


def job_url(job_key: str, *, host: str = "www.indeed.com") -> str:
    """The public link to a job posting on Indeed."""
    return f"https://{host}/viewjob?jk={job_key}"


# --------------------------------------------------------------------------- #
# Value helpers
# --------------------------------------------------------------------------- #


def _text(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list, bool)):
        return None
    text = " ".join(html_lib.unescape(str(value)).split())
    return text or None


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _positive(value: Any) -> float | None:
    """A number, or ``None`` for Indeed's "not set" placeholders (0 / -1)."""
    number = _num(value)
    return number if number is not None and number > 0 else None


def _absolute(url: Any, host: str) -> str | None:
    link = _text(url)
    if not link:
        return None
    if link.startswith("//"):
        return "https:" + link
    if link.startswith("/"):
        return f"https://{host}{link}"
    return link


def _strip_query(url: str | None) -> str | None:
    """Drop the tracking query string from an Indeed company link."""
    if not url:
        return None
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def html_to_text(fragment: Any) -> str | None:
    """Turn an Indeed HTML fragment (snippet or description) into plain text.

    Paragraphs and line breaks become newlines and list items become ``"- "``
    lines; blank-line runs are collapsed.
    """
    if not fragment or not isinstance(fragment, str):
        return None
    text = _LIST_ITEM_RE.sub("\n- ", fragment)
    text = _BLOCK_TAG_RE.sub("\n", text)
    text = html_lib.unescape(_TAG_RE.sub("", text)).replace("\xa0", " ")
    lines: list[str] = []
    for raw in text.splitlines():
        line = " ".join(raw.split())
        if line or (lines and lines[-1]):
            lines.append(line)
    return "\n".join(lines).strip() or None


def _one_line(text: str | None) -> str | None:
    """Collapse a multi-line text (e.g. a bulleted snippet) into one line."""
    if not text:
        return None
    parts = [line[2:] if line.startswith("- ") else line for line in text.splitlines()]
    return " ".join(p for p in parts if p) or None


def pub_date(ms: Any) -> str | None:
    """Indeed's publication timestamp (epoch milliseconds) as an ISO date.

    Indeed stamps postings at midnight US Central time on every country site,
    which falls on the same calendar day in UTC.
    """
    number = _num(ms)
    if number is None or number <= 0:
        return None
    return datetime.fromtimestamp(number / 1000, tz=timezone.utc).date().isoformat()


def salary_period(salary_type: Any) -> str | None:
    """``"YEARLY"`` -> ``"year"``, ``"HOURLY"`` -> ``"hour"``, ..."""
    text = _text(salary_type)
    if not text:
        return None
    return SALARY_PERIODS.get(text.upper(), text.lower())


def _match_type(tier: Any) -> tuple[str, str | None]:
    """Classify a card by the result section Indeed placed it in."""
    if not isinstance(tier, dict):
        return "search", None
    kind = str(tier.get("type") or "").upper()
    raw = str(tier.get("rawType") or "")
    if kind == "RJP_ON_SERP":
        return "recommended", None
    if kind == "LE_SPONSORED_GROUPING":
        return "nearby", None
    if raw.startswith("grouping_"):
        return "related", _text(raw[len("grouping_") :])
    if kind in ("", "DEFAULT") and not raw:
        return "search", None
    return "related", None


# --------------------------------------------------------------------------- #
# Page parsing
# --------------------------------------------------------------------------- #


def _embedded_json(html: str, pattern: re.Pattern[str]) -> Any | None:
    match = pattern.search(html)
    if not match:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(html, match.end())
    except ValueError:
        return None
    return value


def extract_jobcards(html: str) -> dict[str, Any] | None:
    """Return Indeed's embedded job-cards model, or ``None`` if the page has none."""
    data = _embedded_json(html, _JOBCARDS_RE)
    if not isinstance(data, dict):
        return None
    model = (data.get("metaData") or {}).get("mosaicProviderJobCardsModel")
    return model if isinstance(model, dict) else None


def extract_initial_data(html: str) -> dict[str, Any] | None:
    """Return Indeed's embedded page data (``window._initialData``), if present."""
    data = _embedded_json(html, _INITIAL_DATA_RE)
    return data if isinstance(data, dict) else None


def normalize_job(raw: dict[str, Any], *, host: str = "www.indeed.com") -> Job:
    """Normalize one embedded Indeed job card into a :class:`Job`."""
    job_key = _text(raw.get("jobkey"))
    snippet = raw.get("salarySnippet") if isinstance(raw.get("salarySnippet"), dict) else {}
    extracted = raw.get("extractedSalary") if isinstance(raw.get("extractedSalary"), dict) else {}
    salary_text = _text(snippet.get("text"))
    salary_min = _positive(extracted.get("min"))
    salary_max = _positive(extracted.get("max"))
    has_salary = bool(salary_text or salary_min or salary_max)

    remote_model = (
        raw.get("remoteWorkModel") if isinstance(raw.get("remoteWorkModel"), dict) else {}
    )
    work_setting = _text(remote_model.get("text"))
    remote = bool(raw.get("remoteLocation")) or remote_model.get("type") == "REMOTE_ALWAYS"
    city = _text(raw.get("jobLocationCity"))
    if city and city.lower() == "remote":
        city = None

    match_type, related_group = _match_type(raw.get("tier"))
    rating = _positive(raw.get("companyRating"))
    reviews = _positive(raw.get("companyReviewCount"))

    return Job(
        job_key=job_key,
        title=_text(raw.get("displayTitle")) or _text(raw.get("title")),
        company=_text(raw.get("company")) or _text(raw.get("truncatedCompany")),
        company_url=_strip_query(_absolute(raw.get("companyOverviewLink"), host)),
        company_rating=float(rating) if rating is not None else None,
        company_review_count=int(reviews) if reviews is not None else None,
        location=_text(raw.get("formattedLocation")),
        city=city,
        state=_text(raw.get("jobLocationState")),
        postal_code=_text(raw.get("jobLocationPostal")),
        country=_text(raw.get("country")),
        work_setting=work_setting,
        remote=remote,
        salary_text=salary_text,
        salary_min=salary_min,
        salary_max=salary_max,
        salary_period=salary_period(extracted.get("type")) if has_salary else None,
        # Indeed can attach a currency to cards that show no salary; drop it there.
        salary_currency=_text(snippet.get("currency")) if has_salary else None,
        job_types=[t for t in (_text(v) for v in raw.get("jobTypes") or []) if t],
        date_posted=pub_date(raw.get("pubDate")),
        posted_ago=_text(raw.get("formattedRelativeTime")),
        sponsored=bool(raw.get("sponsored")),
        urgently_hiring=bool(raw.get("urgentlyHiring")),
        easy_apply=bool(raw.get("indeedApplyable")),
        match_type=match_type,
        related_group=related_group,
        snippet=_one_line(html_to_text(raw.get("snippet"))),
        url=job_url(job_key, host=host) if job_key else None,
    )


def _labels(items: Any) -> list[str]:
    labels = []
    for item in items or []:
        label = _text(item.get("label")) if isinstance(item, dict) else _text(item)
        if label and label not in labels:
            labels.append(label)
    return labels


def parse_job_details(data: dict[str, Any], *, host: str = "www.indeed.com") -> JobDetails | None:
    """Pull the side-panel posting out of Indeed's embedded page data."""
    response = data.get("autoOpenTwoPaneViewjobResponse")
    body = response.get("body") if isinstance(response, dict) else None
    if not isinstance(body, dict) or not body.get("jobKey"):
        return None
    info = ((body.get("jobInfoWrapperModel") or {}).get("jobInfoModel")) or {}
    header = info.get("jobInfoHeaderModel") or {}
    section = ((info.get("jobDescriptionSectionModel") or {}).get("jobDetailsSection")) or {}
    salary = body.get("salaryInfoModel") or section.get("salaryInfoModel") or {}
    ratings = ((header.get("companyReviewModel") or {}).get("ratingsModel")) or {}
    remote_model = header.get("remoteWorkModel") or {}
    job_key = _text(body.get("jobKey"))
    description_html = info.get("sanitizedJobDescription")
    rating = _positive(ratings.get("rating"))
    reviews = _positive(ratings.get("count"))
    salary_min = _positive(salary.get("salaryMin"))
    salary_max = _positive(salary.get("salaryMax"))
    salary_text = _text(salary.get("salaryText"))
    has_salary = bool(salary_text or salary_min or salary_max)
    return JobDetails(
        job_key=job_key,
        title=_text(header.get("jobTitle")) or _text(body.get("jobTitle")),
        company=_text(header.get("companyName")),
        company_url=_strip_query(_absolute(header.get("companyOverviewLink"), host)),
        company_rating=float(rating) if rating is not None else None,
        company_review_count=int(reviews) if reviews is not None else None,
        company_logo=_text((header.get("companyImagesModel") or {}).get("logoUrl")),
        location=_text(header.get("formattedLocation")) or _text(body.get("jobLocation")),
        work_setting=_text(remote_model.get("text")),
        salary_text=salary_text,
        salary_min=salary_min,
        salary_max=salary_max,
        salary_period=salary_period(salary.get("salaryType")) if has_salary else None,
        salary_currency=_text(salary.get("salaryCurrency")) if has_salary else None,
        job_types=_labels(section.get("jobTypes")),
        benefits=_labels((body.get("benefitsModel") or {}).get("benefits")),
        description=html_to_text(description_html),
        description_html=description_html if isinstance(description_html, str) else None,
        posted_ago=_text((body.get("hiringInsightsModel") or {}).get("age")),
        expired=bool(section.get("isJobExpired") or info.get("showExpiredHeader")),
        url=job_url(job_key, host=host) if job_key else None,
    )


def check_page(html: str) -> None:
    """Raise :class:`IndeedBlockedError` for a bot-check or sign-in page."""
    if _CHALLENGE_RE.search(html):
        raise IndeedBlockedError("Indeed answered with a bot-check page")
    if _SIGN_IN_RE.search(html):
        raise IndeedBlockedError("Indeed answered with its sign-in page")


def parse_search_page(html: str, *, url: str | None = None) -> SearchPage:
    """Parse an Indeed search page's HTML into a :class:`SearchPage`.

    Raises:
        IndeedBlockedError: the page is a bot-check or sign-in page.
        IndeedParseError: the page has no embedded job data.
    """
    check_page(html)
    model = extract_jobcards(html)
    if model is None:
        raise IndeedParseError("the page has no embedded Indeed job data")
    host = (urlsplit(url).hostname if url else None) or "www.indeed.com"
    data = extract_initial_data(html) or {}
    total = _num(data.get("totalJobCount"))
    if total is None:
        total = _num((data.get("searchTitleBarModel") or {}).get("totalNumResults"))
    jobs = [normalize_job(r, host=host) for r in model.get("results") or [] if isinstance(r, dict)]
    return SearchPage(
        jobs=jobs,
        query=_text(model.get("what")),
        location=_text(model.get("where")),
        total=int(total) if total is not None else None,
        country=country_for_host(host),
        url=url,
        details=parse_job_details(data, host=host),
    )


def apply_details(job: Job, details: JobDetails) -> Job:
    """Copy a job's full-posting fields onto it, filling in anything the card lacked."""
    job.description = details.description
    job.benefits = list(details.benefits)
    job.company_logo = details.company_logo
    if not job.job_types and details.job_types:
        job.job_types = list(details.job_types)
    if job.work_setting is None:
        job.work_setting = details.work_setting
    if job.company_url is None:
        job.company_url = details.company_url
    if job.company_rating is None:
        job.company_rating = details.company_rating
        job.company_review_count = details.company_review_count
    if job.salary_text is None and job.salary_min is None and details.salary_text:
        job.salary_text = details.salary_text
        job.salary_min = details.salary_min
        job.salary_max = details.salary_max
        job.salary_period = details.salary_period
        job.salary_currency = details.salary_currency
    return job


# --------------------------------------------------------------------------- #
# Scraper
# --------------------------------------------------------------------------- #


class IndeedScraper:
    """Scrape Indeed job search results via ScrapeUnblocker.

    Args:
        api_key: ScrapeUnblocker key. If omitted, the SDK reads
            ``SCRAPEUNBLOCKER_KEY`` from the environment.
        client: A pre-built client (or any object exposing
            ``get_page_source(url, proxy_country=...)``). Mainly for testing.
        retries: Extra attempts on transient failures (including a bot-check
            page or a page without Indeed's embedded data).
        backoff: Seconds before the first retry; doubles on every further retry.
        max_backoff: Upper bound for a single wait between retries.
        timeout: Per-request timeout passed to the SDK client.
        transient_errors: Exception classes treated as retryable. Defaults to
            the ScrapeUnblocker transient set.
        on_retry: Optional callback ``(attempt, delay_seconds, error)`` invoked
            before every retry (handy for progress output).
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        client: Any | None = None,
        retries: int = 3,
        backoff: float = 3.0,
        max_backoff: float = 30.0,
        timeout: float = 180.0,
        transient_errors: Sequence[type[BaseException]] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        on_retry: Callable[[int, float, BaseException], None] | None = None,
    ) -> None:
        if client is None:
            from scrapeunblocker import Client  # local import: optional dep

            client = Client(api_key=api_key, timeout=timeout)
        self._client = client
        self.retries = max(0, int(retries))
        self.backoff = float(backoff)
        self.max_backoff = float(max_backoff)
        self.on_retry = on_retry
        transient = tuple(transient_errors) if transient_errors is not None else _transient_errors()
        self._transient = (*transient, IndeedParseError)
        self._sleep = sleep

    def fetch_page(self, url: str, *, proxy_country: str | None = None) -> SearchPage:
        """Fetch and parse one Indeed search page, retrying transient failures.

        ``proxy_country`` is the country to route through (default ``"US"``,
        whichever Indeed site ``url`` is on).
        """
        if proxy_country is None:
            proxy_country = DEFAULT_PROXY_COUNTRY
        attempt = 0
        while True:
            try:
                html = self._client.get_page_source(url, proxy_country=proxy_country)
                return parse_search_page(html if isinstance(html, str) else "", url=url)
            except self._transient as exc:
                if attempt >= self.retries:
                    raise
                attempt += 1
                delay = min(self.backoff * 2 ** (attempt - 1), self.max_backoff)
                if self.on_retry is not None:
                    self.on_retry(attempt, delay, exc)
                self._sleep(delay)

    def scrape_url(
        self,
        url: str,
        *,
        limit: int | None = None,
        proxy_country: str | None = None,
        include_related: bool = False,
        include_sponsored: bool = True,
        details: bool = False,
        seen: set[str] | None = None,
        on_page: Callable[[SearchPage], None] | None = None,
    ) -> list[Job]:
        """Scrape any Indeed search URL (e.g. one copied from your browser).

        Args:
            url: An Indeed ``/jobs?...`` search URL on any country site. Its
                first results page is used (see :func:`first_page_url`).
            limit: Stop once this many unique jobs are collected.
            proxy_country: Country to route through (default ``"US"``, which
                works for every Indeed country site).
            include_related: Also keep cards outside the direct matches:
                Indeed's sponsored related-job groups, nearby-location jobs and
                recommendations (see ``Job.match_type``).
            include_sponsored: Keep sponsored jobs.
            details: Fetch each job's full posting (description, benefits,
                logo). Costs one extra request per job.
            seen: Shared de-duplication set (used when merging several searches).
            on_page: Optional callback invoked with the fetched :class:`SearchPage`.

        Returns:
            A list of :class:`Job`, de-duplicated by job key.
        """
        seen = set() if seen is None else seen
        page = self.fetch_page(first_page_url(url), proxy_country=proxy_country)
        if on_page is not None:
            on_page(page)
        jobs: list[Job] = []
        if page.no_match and not include_related:
            return jobs
        for job in page.jobs:
            if not include_related and job.match_type != "search":
                continue
            if job.sponsored and not include_sponsored:
                continue
            key = job.job_key or job.url or job.title
            if key is None or key in seen:
                continue
            seen.add(key)
            job.search_query = page.query
            job.search_location = page.location
            jobs.append(job)
            if limit is not None and len(jobs) >= limit:
                break
        if details:
            self.enrich(jobs, proxy_country=proxy_country)
        return jobs

    def search(
        self,
        query: str = "",
        location: str = "",
        *,
        country: str = DEFAULT_COUNTRY,
        limit: int | None = None,
        proxy_country: str | None = None,
        include_related: bool = False,
        include_sponsored: bool = True,
        details: bool = False,
        on_page: Callable[[SearchPage], None] | None = None,
        **filters: Any,
    ) -> list[Job]:
        """Search Indeed by keywords, location and filters.

        Accepts every filter of :func:`build_search_url` (``sort``, ``days``,
        ``job_type``, ``remote``, ``radius``).

        Example:
            >>> scraper.search("data analyst", "New York, NY",
            ...                days=3, sort="date")  # doctest: +SKIP
        """
        url = build_search_url(query, location, country=country, **filters)
        return self.scrape_url(
            url,
            limit=limit,
            proxy_country=proxy_country,
            include_related=include_related,
            include_sponsored=include_sponsored,
            details=details,
            on_page=on_page,
        )

    def scrape_many(
        self,
        urls: Iterable[str],
        *,
        limit: int | None = None,
        proxy_country: str | None = None,
        include_related: bool = False,
        include_sponsored: bool = True,
        details: bool = False,
        on_page: Callable[[SearchPage], None] | None = None,
    ) -> list[Job]:
        """Scrape several search URLs and merge them, de-duplicated by job key."""
        seen: set[str] = set()
        jobs: list[Job] = []
        for url in urls:
            remaining = None if limit is None else limit - len(jobs)
            if remaining is not None and remaining <= 0:
                break
            jobs.extend(
                self.scrape_url(
                    url,
                    limit=remaining,
                    proxy_country=proxy_country,
                    include_related=include_related,
                    include_sponsored=include_sponsored,
                    seen=seen,
                    on_page=on_page,
                )
            )
        if details:
            self.enrich(jobs, proxy_country=proxy_country)
        return jobs

    def search_many(
        self,
        queries: Iterable[str],
        locations: Iterable[str] = ("",),
        *,
        country: str = DEFAULT_COUNTRY,
        limit: int | None = None,
        proxy_country: str | None = None,
        include_related: bool = False,
        include_sponsored: bool = True,
        details: bool = False,
        on_page: Callable[[SearchPage], None] | None = None,
        **filters: Any,
    ) -> list[Job]:
        """Run every query in every location and merge the results (de-duplicated).

        Example:
            >>> scraper.search_many(["data analyst", "data engineer"],
            ...                     ["New York, NY", "Remote"], days=7)  # doctest: +SKIP
        """
        locations = list(locations) or [""]
        urls = [
            build_search_url(q, loc, country=country, **filters)
            for q in queries
            for loc in locations
        ]
        return self.scrape_many(
            urls,
            limit=limit,
            proxy_country=proxy_country,
            include_related=include_related,
            include_sponsored=include_sponsored,
            details=details,
            on_page=on_page,
        )

    def job_details(
        self,
        job_key: str,
        *,
        country: str = DEFAULT_COUNTRY,
        proxy_country: str | None = None,
    ) -> JobDetails | None:
        """Fetch the full posting for one job key (description, benefits, logo, ...).

        Returns ``None`` when Indeed does not open that job (for example, the
        posting was taken down), rather than returning another job's details.
        """
        url = build_search_url("jobs", country=country, job_key=job_key)
        page = self.fetch_page(url, proxy_country=proxy_country)
        if page.details is None or page.details.job_key != job_key:
            return None
        return page.details

    def enrich(
        self,
        jobs: Sequence[Job],
        *,
        proxy_country: str | None = None,
        on_details: Callable[[Job, JobDetails | None], None] | None = None,
    ) -> list[Job]:
        """Add full-posting fields to ``jobs`` in place (one request per job).

        Jobs whose posting cannot be opened are left as they are.
        """
        for job in jobs:
            if not job.job_key:
                continue
            country = job.country or DEFAULT_COUNTRY
            if job.url:
                country = country_for_host(urlsplit(job.url).hostname or "")
            details = self.job_details(job.job_key, country=country, proxy_country=proxy_country)
            if details is not None:
                apply_details(job, details)
            if on_details is not None:
                on_details(job, details)
        return list(jobs)


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #


def jobs_to_dicts(jobs: Sequence[Job]) -> list[dict[str, Any]]:
    return [job.to_dict() for job in jobs]


def to_json(jobs: Sequence[Job], *, indent: int | None = 2) -> str:
    return json.dumps(jobs_to_dicts(jobs), indent=indent, ensure_ascii=False)


def to_csv(jobs: Sequence[Job], path: str) -> None:
    """Write ``jobs`` to a CSV file at ``path`` (list fields joined with ``" | "``)."""
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(FIELDNAMES))
        writer.writeheader()
        for job in jobs:
            row = job.to_dict()
            for name, value in row.items():
                if isinstance(value, list):
                    row[name] = " | ".join(str(v) for v in value)
            writer.writerow(row)

"""Command-line interface for indeed-scraper.

Examples:
    indeed-scraper "python developer" -l Remote --pretty
    indeed-scraper "data analyst" "data engineer" -l "New York, NY" -l "Austin, TX" \\
        --days 3 --sort date --format csv --output jobs.csv
    indeed-scraper "registered nurse" -l "Toronto, ON" --country CA --job-type fulltime
    indeed-scraper "devops engineer" --remote --details --limit 10
    indeed-scraper --url "https://www.indeed.com/jobs?q=..."
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from . import __version__
from .scraper import (
    DAYS_POSTED,
    JOB_TYPES,
    SORTS,
    IndeedParseError,
    IndeedScraper,
    Job,
    JobDetails,
    SearchPage,
    build_search_url,
    first_page_url,
    indeed_host,
    to_csv,
    to_json,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="indeed-scraper",
        description="Scrape Indeed job listings (salary, company, location, job type, "
        "posting date) into clean JSON or CSV via the ScrapeUnblocker getPageSource API.",
    )
    what = parser.add_argument_group("what to search")
    what.add_argument(
        "queries",
        nargs="*",
        metavar="QUERY",
        help='Job title, skill or company, e.g. "python developer". Several queries are '
        "merged and de-duplicated.",
    )
    what.add_argument(
        "-l",
        "--location",
        dest="locations",
        action="append",
        metavar="PLACE",
        help='City, state, postal code or "Remote" (repeatable: every query runs in every '
        "location).",
    )
    what.add_argument(
        "--url",
        dest="urls",
        action="append",
        metavar="URL",
        help="A full Indeed search URL (repeatable). Filters already in the URL are kept; "
        "the filter flags below are ignored.",
    )
    what.add_argument(
        "-c",
        "--country",
        default="US",
        metavar="ISO",
        help="Which Indeed site to search: US (default), GB, CA, AU, IN, DE, ... (2-letter code).",
    )

    filters = parser.add_argument_group("filters")
    filters.add_argument(
        "-s", "--sort", choices=SORTS, help="Result order: relevance (default) or date."
    )
    filters.add_argument(
        "-d",
        "--days",
        type=int,
        choices=DAYS_POSTED,
        help="Only jobs posted in the last 1, 3, 7 or 14 days.",
    )
    filters.add_argument("-t", "--job-type", choices=JOB_TYPES, help="Only this job type.")
    filters.add_argument("--remote", action="store_true", help="Only remote jobs.")
    filters.add_argument(
        "-r",
        "--radius",
        type=int,
        metavar="DIST",
        help="Search radius around the location (miles on indeed.com).",
    )
    filters.add_argument(
        "--no-sponsored",
        dest="include_sponsored",
        action="store_false",
        help="Drop sponsored jobs.",
    )
    filters.add_argument(
        "--include-related",
        action="store_true",
        help="Also keep Indeed's related-job groups, nearby-location jobs and "
        "recommendations, not just direct matches (see match_type).",
    )

    out = parser.add_argument_group("collection and output")
    out.add_argument("-n", "--limit", type=int, help="Stop after this many unique jobs.")
    out.add_argument(
        "--details",
        action="store_true",
        help="Also fetch each job's full posting (description, benefits, company logo). "
        "One extra request per job.",
    )
    out.add_argument(
        "--proxy-country",
        metavar="ISO",
        help="Country to route requests through (default: US, which works for every "
        "Indeed country site).",
    )
    out.add_argument(
        "--retries",
        type=int,
        default=3,
        metavar="N",
        help="Retries per page on transient errors, with doubling backoff (default: 3).",
    )
    out.add_argument(
        "-f",
        "--format",
        choices=("json", "csv"),
        default="json",
        help="Output format (default: json).",
    )
    out.add_argument("-o", "--output", metavar="PATH", help="Write to this file, not stdout.")
    out.add_argument("--pretty", action="store_true", help="Pretty-print JSON (indented).")
    out.add_argument("-q", "--quiet", action="store_true", help="No progress output on stderr.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def resolve_urls(args: argparse.Namespace) -> list[str]:
    """Turn parsed CLI arguments into the search URL(s) to scrape.

    Raises:
        ValueError: when nothing (or both searches and ``--url``) is given, or a
            filter value is invalid.
    """
    queries = [q.strip() for q in args.queries or [] if q and q.strip()]
    locations = [loc.strip() for loc in args.locations or [] if loc and loc.strip()]
    if args.urls:
        if queries or locations:
            raise ValueError("give QUERY / --location or --url, not both")
        return [first_page_url(url) for url in args.urls]
    if not queries and not locations:
        raise ValueError("give at least one QUERY or --location (or --url)")
    indeed_host(args.country)  # validates the country code
    return [
        build_search_url(
            query,
            location,
            country=args.country,
            sort=args.sort,
            days=args.days,
            job_type=args.job_type,
            remote=args.remote,
            radius=args.radius,
        )
        for query in (queries or [""])
        for location in (locations or [""])
    ]


def _say(line: str) -> None:
    try:
        print(line, file=sys.stderr)
    except UnicodeEncodeError:  # legacy console
        print(line.encode("ascii", "replace").decode("ascii"), file=sys.stderr)


def _progress(page: SearchPage) -> None:
    """Print one line per fetched search to stderr."""
    what = f'"{page.query}"' if page.query else "all jobs"
    where = f" in {page.location}" if page.location else ""
    if page.no_match:
        _say(f"[indeed] {what}{where} ({page.country}): no jobs match this search")
        return
    direct = sum(1 for job in page.jobs if job.match_type == "search")
    total = f"{page.total:,} matching" if page.total is not None else "? matching"
    _say(
        f"[indeed] {what}{where} ({page.country}): {direct} direct matches, "
        f"{len(page.jobs) - direct} related/sponsored cards ({total})"
    )


def _details_progress(job: Job, details: JobDetails | None) -> None:
    status = "ok" if details is not None else "unavailable"
    _say(f"[indeed] details {job.job_key}: {status}")


def _retrying(attempt: int, delay: float, error: BaseException) -> None:
    reason = str(error) or type(error).__name__
    _say(f"[indeed] {reason}; retry {attempt} in {delay:g}s")


def _write_output(text: str, output: str | None) -> None:
    if output:
        with open(output, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        # Titles and salaries can carry non-ASCII glyphs ("–", "£", "€"); force
        # UTF-8 so printing on a legacy Windows console does not raise.
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
        print(text)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        urls = resolve_urls(args)
    except ValueError as exc:
        parser.error(str(exc))

    if args.format == "csv" and not args.output:
        parser.error("--format csv requires --output PATH")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.retries < 0:
        parser.error("--retries must not be negative")

    scraper = IndeedScraper(retries=args.retries, on_retry=None if args.quiet else _retrying)
    try:
        jobs = scraper.scrape_many(
            urls,
            limit=args.limit,
            proxy_country=args.proxy_country,
            include_related=args.include_related,
            include_sponsored=args.include_sponsored,
            on_page=None if args.quiet else _progress,
        )
        if args.details and jobs:
            scraper.enrich(
                jobs,
                proxy_country=args.proxy_country,
                on_details=None if args.quiet else _details_progress,
            )
    except IndeedParseError as exc:
        print(f"error: {exc}. Try again in a few minutes or raise --retries.", file=sys.stderr)
        return 1

    if not jobs:
        print("No jobs match this search.", file=sys.stderr)

    if args.format == "csv":
        to_csv(jobs, args.output)
    else:
        _write_output(to_json(jobs, indent=2 if args.pretty else None), args.output)
    if args.output:
        print(f"Wrote {len(jobs)} jobs to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

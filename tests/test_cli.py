from __future__ import annotations

import csv
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from indeed_scraper import IndeedParseError, Job, cli


def parse(*argv):
    return cli.build_parser().parse_args(list(argv))


def params(url):
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


def test_defaults():
    args = parse("python developer")
    assert args.queries == ["python developer"]
    assert args.locations is None
    assert args.country == "US"
    assert args.format == "json"
    assert args.retries == 3
    assert args.include_sponsored is True
    assert args.include_related is False
    assert args.details is False


def test_every_query_runs_in_every_location():
    args = parse(
        "data analyst",
        "data engineer",
        "-l",
        "New York, NY",
        "-l",
        "Remote",
        "--days",
        "3",
        "--sort",
        "date",
        "--job-type",
        "fulltime",
        "--remote",
        "--radius",
        "25",
    )
    urls = cli.resolve_urls(args)
    assert [(params(u)["q"], params(u)["l"]) for u in urls] == [
        ("data analyst", "New York, NY"),
        ("data analyst", "Remote"),
        ("data engineer", "New York, NY"),
        ("data engineer", "Remote"),
    ]
    assert params(urls[0]) == {
        "q": "data analyst",
        "l": "New York, NY",
        "fromage": "3",
        "sort": "date",
        "jt": "fulltime",
        "sc": "0kf:attr(DSQF7);",
        "radius": "25",
    }


def test_location_only_and_country_site():
    urls = cli.resolve_urls(parse("-l", "Toronto, ON", "--country", "CA"))
    assert urlsplit(urls[0]).hostname == "ca.indeed.com"
    assert params(urls[0]) == {"l": "Toronto, ON"}


def test_urls_are_normalized_to_the_first_page():
    urls = cli.resolve_urls(parse("--url", "https://www.indeed.com/jobs?q=nurse&start=10"))
    assert urls == ["https://www.indeed.com/jobs?q=nurse"]


@pytest.mark.parametrize(
    "argv",
    [
        (),
        ("nurse", "--url", "https://www.indeed.com/jobs?q=x"),
        ("nurse", "--country", "USA"),
        ("--url", "https://example.com/jobs"),
    ],
)
def test_bad_combinations(argv):
    with pytest.raises(ValueError):
        cli.resolve_urls(parse(*argv))


def test_rejects_unknown_filter_values():
    with pytest.raises(SystemExit):
        parse("nurse", "--days", "5")
    with pytest.raises(SystemExit):
        parse("nurse", "--job-type", "gig")


class FakeScraper:
    instances: list[FakeScraper] = []
    raise_error = False

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.urls = None
        self.enriched = None
        FakeScraper.instances.append(self)

    def scrape_many(self, urls, **kwargs):
        if FakeScraper.raise_error:
            raise IndeedParseError("the page has no embedded Indeed job data")
        self.urls = list(urls)
        self.scrape_kwargs = kwargs
        return [
            Job(job_key="a1", title="Python Developer", job_types=["Full-time", "Contract"]),
            Job(job_key="a2", title="Data Engineer – Remote", salary_text="£50,000 a year"),
        ]

    def enrich(self, jobs, **kwargs):
        self.enriched = list(jobs)
        return jobs


@pytest.fixture
def fake(monkeypatch):
    FakeScraper.instances = []
    FakeScraper.raise_error = False
    monkeypatch.setattr(cli, "IndeedScraper", FakeScraper)
    return FakeScraper


def test_main_prints_json(fake, capsys):
    assert cli.main(["python developer", "-l", "Remote", "--pretty", "-q"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert [job["job_key"] for job in out] == ["a1", "a2"]
    scraper = fake.instances[0]
    assert params(scraper.urls[0]) == {"q": "python developer", "l": "Remote"}
    assert scraper.scrape_kwargs["include_related"] is False
    assert scraper.enriched is None


def test_main_writes_csv(fake, tmp_path):
    path = tmp_path / "jobs.csv"
    assert cli.main(["nurse", "-f", "csv", "-o", str(path), "--no-sponsored", "-q"]) == 0
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["job_types"] == "Full-time | Contract"
    assert rows[1]["title"] == "Data Engineer – Remote"
    assert fake.instances[0].scrape_kwargs["include_sponsored"] is False


def test_main_details_enriches(fake, tmp_path):
    assert cli.main(["nurse", "--details", "-o", str(tmp_path / "j.json"), "-q"]) == 0
    assert [j.job_key for j in fake.instances[0].enriched] == ["a1", "a2"]


def test_csv_needs_output(fake):
    with pytest.raises(SystemExit):
        cli.main(["nurse", "-f", "csv"])


def test_bad_limit_and_retries(fake):
    with pytest.raises(SystemExit):
        cli.main(["nurse", "--limit", "0"])
    with pytest.raises(SystemExit):
        cli.main(["nurse", "--retries", "-1"])


def test_main_reports_parse_errors(fake, capsys):
    fake.raise_error = True
    assert cli.main(["nurse", "-q"]) == 1
    assert "error:" in capsys.readouterr().err

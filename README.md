# indeed-scraper

[![CI](https://github.com/ScrapeUnblocker/indeed-scraper/actions/workflows/ci.yml/badge.svg)](https://github.com/ScrapeUnblocker/indeed-scraper/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Scrape Indeed job listings into clean, typed JSON or CSV: structured salary, company rating, location, job type and posting date, with no CSS selectors to maintain.**

Search Indeed for any job title, skill or company in any location and get back
one clean record per job: job key, title, company and its Indeed rating, city /
state / postal code, remote or hybrid setting, salary as text **and** as
min / max / pay period / currency, job types, the date Indeed published it,
sponsored / urgently-hiring / "easily apply" flags, a snippet and the job URL.
Add `--details` to also get the full description, benefits and company logo.
Tested on Indeed's US, UK and Canada sites; other country sites are addressed
the same way.

> **Powered by [ScrapeUnblocker](https://scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos).**
> Every Indeed page is loaded in a real browser through the
> [`getPageSource` API](https://docs.scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos),
> and jobs are read from the structured data Indeed embeds in each results
> page, not from the rendered cards.

## Features

- 💰 **Salary you can sort by**: `"$152,513 - $190,642 a year"` becomes
  `salary_min: 152513`, `salary_max: 190642`, `salary_period: "year"`,
  `salary_currency: "USD"` (hourly, daily, weekly and monthly pay too; GBP on
  the UK site, CAD on the Canadian one).
- 🎛️ **Indeed's own filters**: date posted (last 1 / 3 / 7 / 14 days), job type
  (full-time, part-time, contract, temporary, internship), remote only, search
  radius, and sort by relevance or date.
- 🎯 **Direct matches only**: Indeed mixes sponsored "related jobs" groups,
  nearby-location jobs and recommendations into its results. Every job carries a
  `match_type`, and by default you only get the jobs that actually match your
  search (`--include-related` keeps the rest).
- 🔎 **Many searches at once**: pass several queries and locations; every query
  runs in every location and the results are merged and de-duplicated by job key.
- 📄 **Full postings on demand**: `--details` adds the complete description
  (as plain text), benefits and company logo for every job;
  `scraper.job_details()` also returns the description HTML.
- 📅 **Real dates**: `date_posted` is Indeed's publication date (`2026-09-17`), not
  just "10 days ago" (kept too, as `posted_ago`).
- 🌍 **Country sites**: `--country GB` searches uk.indeed.com, `CA` ca.indeed.com,
  and so on; URLs in the output point at the right site.
- 🔁 **Resilient**: bot-check pages and timeouts are retried with doubling
  backoff, and a search with no matches comes back as an empty list.
- 🖥️ **CLI + library**: use `indeed-scraper` from the shell or import it in Python.

## Install

```bash
pip install .
# or, for development:
pip install -e ".[dev]"
```

Set your ScrapeUnblocker API key (grab one from your
[dashboard](https://scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos)):

```bash
cp .env.example .env          # then edit it, or just export the variable:
export SCRAPEUNBLOCKER_KEY=your_key_here
```

## CLI usage

```bash
# One search, pretty-printed JSON to stdout
indeed-scraper "python developer" -l Remote --pretty

# Two roles in two cities, posted in the last 3 days, newest first, as CSV
indeed-scraper "data analyst" "data engineer" -l "New York, NY" -l "Austin, TX" \
  --days 3 --sort date --format csv --output data_jobs.csv

# Full-time nursing jobs on Indeed Canada
indeed-scraper "registered nurse" -l "Toronto, ON" --country CA --job-type fulltime

# Remote DevOps jobs with full descriptions and benefits (1 extra request per job)
indeed-scraper "devops engineer" --remote --details --limit 10 --output devops.json

# UK jobs within 10 miles of Manchester, without sponsored listings
indeed-scraper "accountant" -l Manchester --country GB --radius 10 --no-sponsored

# Any search you set up on indeed.com: just paste the URL
indeed-scraper --url "https://www.indeed.com/jobs?q=product+manager&l=Seattle%2C+WA&fromage=7"
```

Progress goes to stderr (here for
`indeed-scraper "python developer" -l Remote --limit 3 --details -o jobs.json`):

```
[indeed] "python developer" in Remote (US): 15 direct matches, 26 related/sponsored cards (2,430 matching)
[indeed] details a80654465f93f95d: ok
[indeed] details 9e465570cba1c5ce: ok
[indeed] details 86aa76a7dde09ebc: ok
Wrote 3 jobs to jobs.json
```

```
usage: indeed-scraper [-h] [-l PLACE] [--url URL] [-c ISO]
                      [-s {relevance,date}] [-d {1,3,7,14}]
                      [-t {fulltime,parttime,contract,temporary,internship}]
                      [--remote] [-r DIST] [--no-sponsored]
                      [--include-related] [-n LIMIT] [--details]
                      [--proxy-country ISO] [--retries N] [-f {json,csv}]
                      [-o PATH] [--pretty] [-q] [--version]
                      [QUERY ...]
```

| Option | Meaning |
| --- | --- |
| `QUERY ...` | Job title, skill or company. Several queries are merged and de-duplicated. |
| `-l, --location` | City, state, postal code or `Remote` (repeatable; every query runs in every location). |
| `--url` | A full Indeed search URL instead of `QUERY` / `--location` (repeatable). |
| `-c, --country` | Which Indeed site: `US` (default), `GB`, `CA`, `AU`, `IN`, `DE`, … |
| `-s, --sort` | `relevance` (Indeed's default) or `date` (newest first). |
| `-d, --days` | Only jobs posted in the last `1`, `3`, `7` or `14` days. |
| `-t, --job-type` | `fulltime`, `parttime`, `contract`, `temporary` or `internship`. |
| `--remote` | Only remote jobs (Indeed's "Remote" filter). |
| `-r, --radius` | Search radius around the location (miles on indeed.com). |
| `--no-sponsored` | Drop sponsored jobs. |
| `--include-related` | Also keep Indeed's related-job groups, nearby jobs and recommendations. |
| `-n, --limit` | Stop after this many unique jobs. |
| `--details` | Fetch each job's full posting (description, benefits, logo). One request per job. |
| `--proxy-country` | Country to route requests through (default `US`, which works for every Indeed site). |
| `--retries` | Retries per request on a transient error or bot-check page (default 3, doubling backoff). |
| `-f, --format` / `-o, --output` | `json` (default) or `csv` (needs `--output`). |

## Library usage

```python
from indeed_scraper import IndeedScraper, to_csv

scraper = IndeedScraper()  # reads SCRAPEUNBLOCKER_KEY

jobs = scraper.search("data analyst", "New York, NY", days=7, sort="date")
for job in jobs:
    if job.salary_min is not None:
        print(f"{job.title} @ {job.company}: {job.salary_min}-{job.salary_max} "
              f"{job.salary_currency} per {job.salary_period}")

# Every query in every location, merged and de-duplicated by job key
more = scraper.search_many(
    ["data analyst", "data engineer"], ["Chicago, IL", "Remote"], job_type="fulltime"
)

# Full postings (description, benefits, logo), one request per job
scraper.enrich(more[:5])

to_csv(jobs + more, "indeed_jobs.csv")
```

Other entry points:

- `scraper.search("nurse", "Toronto, ON", country="CA")` searches another Indeed site.
- `scraper.scrape_url(url)` scrapes any Indeed search URL, and
  `scraper.scrape_many([url1, url2])` merges several.
- `scraper.job_details("9e465570cba1c5ce")` returns one job's full posting as a
  `JobDetails` (or `None` if Indeed no longer opens it).
- `build_search_url("nurse", "Chicago, IL", days=3, job_type="parttime")` just
  builds the URL.
- `on_page=callback` receives each `SearchPage`, with Indeed's `total` match
  count, the echoed `query` / `location`, and every card on the page whatever
  its `match_type`.
- `IndeedScraper(retries=..., backoff=..., on_retry=callback)` tunes the retry policy.

## Example output

A real job from `indeed-scraper "python developer" -l Remote --details`
(description and benefits trimmed):

```json
{
  "job_key": "9e465570cba1c5ce",
  "title": "Python Developer",
  "company": "DMI",
  "company_url": "https://www.indeed.com/cmp/Dmi-a4790562",
  "company_rating": 3.6,
  "company_review_count": 171,
  "location": "Remote",
  "city": null,
  "state": null,
  "postal_code": null,
  "country": "US",
  "work_setting": "Hybrid work",
  "remote": true,
  "salary_text": "$152,513 - $190,642 a year",
  "salary_min": 152513,
  "salary_max": 190642,
  "salary_period": "year",
  "salary_currency": "USD",
  "job_types": ["Full-time"],
  "date_posted": "2026-09-17",
  "posted_ago": "10 days ago",
  "sponsored": false,
  "urgently_hiring": false,
  "easy_apply": false,
  "match_type": "search",
  "related_group": null,
  "snippet": "The program provides IT support to thousands of users across Washington, DC and nationwide field locations. This role works directly with program leadership and…",
  "url": "https://www.indeed.com/viewjob?jk=9e465570cba1c5ce",
  "search_query": "python developer",
  "search_location": "Remote",
  "description": "About DMI:\n\nDMI is a leading provider of digital services and technology solutions, headquartered in Tysons Corner, VA. …",
  "benefits": ["Referral program", "Tuition reimbursement", "Pet insurance", "Health insurance", "401(k) matching"],
  "company_logo": "https://d2q79iu7y748jz.cloudfront.net/s/_squarelogo/256x256/7bebb0154343687c6caf0c3ad192e392"
}
```

Field notes:

- `salary_min` / `salary_max` are per `salary_period` (`hour`, `day`, `week`,
  `month` or `year`). "From $80,000 a year" gives `salary_max: null`. The figure
  is the one Indeed shows: posted by the employer or extracted by Indeed from the
  description. Jobs without a salary have all salary fields `null`.
- `remote` is `true` when Indeed lists the job as remote; `work_setting` is
  Indeed's work-setting label (`Remote`, `Hybrid work`, …) and can be more
  specific, as above.
- `date_posted` is Indeed's original publication date. Postings that stay open
  keep it, so a job shown as "30+ days ago" can date back months.
- `match_type` is `search` for a direct match. With `--include-related` you also
  get `related` (Indeed's sponsored "Jobs in …" groups, named in
  `related_group`), `nearby` (sponsored jobs from nearby locations) and
  `recommended` (Indeed's suggestions when a search matches little or nothing).
- `company_rating` / `company_review_count` are the company's Indeed reviews
  (`null` when it has none). `easy_apply` means the job takes Indeed Apply.
- `description`, `benefits` and `company_logo` are only filled with `--details`
  (`JobDetails` also carries `description_html`).
- Missing values are `null`, never empty strings. In CSV output, `job_types` and
  `benefits` are joined with `" | "`.

## Good to know

- **One results page per search.** Indeed shows signed-out visitors the first
  page of results only and asks them to sign in for page 2, so a search returns
  up to about 15 direct matches (Indeed's `total` count is still reported). To
  collect more, split the search: several queries, several locations, a
  date-posted window, `--sort date` next to relevance. `search_many` (or several
  `QUERY` / `-l` values on the CLI) merges and de-duplicates for you.
- **Details cost a request each.** `--details` opens every job's full posting,
  so 15 jobs with details is 16 requests. Use `--limit` to cap it.
- **Country sites.** Tested on the US, UK and Canada sites; other Indeed country
  sites (`au.indeed.com`, `in.indeed.com`, `de.indeed.com`, …) are addressed the
  same way. Requests go through a US route by default, which returns the same
  local listings as a local route on those sites; `--proxy-country` changes it.
- **Retries.** Timeouts and bot-check pages are retried with doubling backoff
  (3, 6, 12 seconds by default). Each attempt is a normal API request.
- **No results.** A search with no matches returns an empty list, not Indeed's
  "recommended jobs" filler.

## Project layout

```
src/indeed_scraper/
  __init__.py      package exports + version
  scraper.py       Job / JobDetails models, IndeedScraper, URL builder, page parsing, JSON/CSV export
  cli.py           argparse command-line interface
examples/          runnable scripts (search → JSON, multi-search → CSV, daily new-jobs alert)
tests/             offline unit tests (SDK mocked, no API credit spent)
```

## Development

```bash
make install       # editable install with dev deps
make lint          # ruff check
make format        # ruff format
make test          # pytest (offline; the SDK is mocked)
make run           # run the search → JSON example (needs SCRAPEUNBLOCKER_KEY)
```

The test suite mocks the ScrapeUnblocker client and uses synthetic Indeed
pages, so `make test` runs fully offline and spends no API credits.

## Links

- 🌐 [ScrapeUnblocker](https://scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos)
- 📚 [Documentation](https://docs.scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos)
- 🐍 [Python SDK](https://docs.scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos)

## Legal

For research and educational use. Respect Indeed's Terms of Service and
`robots.txt`, data-protection law (job postings can name recruiters and
contacts) and other applicable laws when scraping and storing job data. This
project is not affiliated with or endorsed by Indeed.

## License

MIT, see [LICENSE](LICENSE). Copyright (c) 2026 ScrapeUnblocker.

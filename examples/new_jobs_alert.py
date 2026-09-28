"""Print only the Indeed postings you have not seen before (run it daily).

Searches the newest jobs of the last 24 hours, compares their job keys with the
ones saved by the previous run (seen_jobs.json) and prints the new ones. Point
cron / Task Scheduler at it and pipe the output to email or chat.

Run:  python examples/new_jobs_alert.py "site reliability engineer" "Remote"
Needs SCRAPEUNBLOCKER_KEY in the environment (see .env.example).
"""

import json
import sys
from pathlib import Path

from indeed_scraper import IndeedScraper

query = sys.argv[1] if len(sys.argv) > 1 else "site reliability engineer"
location = sys.argv[2] if len(sys.argv) > 2 else "Remote"
state = Path("seen_jobs.json")

seen = set(json.loads(state.read_text(encoding="utf-8"))) if state.exists() else set()

scraper = IndeedScraper()  # reads SCRAPEUNBLOCKER_KEY
jobs = scraper.search(query, location, days=1, sort="date")
new = [job for job in jobs if job.job_key not in seen]

print(f'{len(new)} new "{query}" jobs in {location or "any location"}:')
for job in new:
    pay = f" - {job.salary_text}" if job.salary_text else ""
    print(f"  {job.title} @ {job.company}{pay}\n    {job.url}")

seen.update(job.job_key for job in jobs if job.job_key)
state.write_text(json.dumps(sorted(seen)), encoding="utf-8")

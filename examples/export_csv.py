"""Collect a week of postings for several roles and cities into one CSV.

Indeed shows signed-out visitors one results page per search, so this runs every
query in every location and merges the results, de-duplicated by job key.

Run:  python examples/export_csv.py
Needs SCRAPEUNBLOCKER_KEY in the environment (see .env.example).
"""

from indeed_scraper import IndeedScraper, to_csv

scraper = IndeedScraper()  # reads SCRAPEUNBLOCKER_KEY

jobs = scraper.search_many(
    ["data analyst", "data engineer"],
    ["New York, NY", "Chicago, IL", "Remote"],
    days=7,
    sort="date",
)

to_csv(jobs, "indeed_data_jobs.csv")
with_salary = sum(1 for job in jobs if job.salary_min is not None)
print(f"Wrote {len(jobs)} jobs to indeed_data_jobs.csv ({with_salary} list a salary)")

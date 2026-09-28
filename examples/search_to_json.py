"""Search Indeed for a job title and save the results as JSON.

Run:  python examples/search_to_json.py
Needs SCRAPEUNBLOCKER_KEY in the environment (see .env.example).
"""

from indeed_scraper import IndeedScraper, to_json

scraper = IndeedScraper()  # reads SCRAPEUNBLOCKER_KEY

jobs = scraper.search("python developer", "Remote")

with open("indeed_python_remote.json", "w", encoding="utf-8") as fh:
    fh.write(to_json(jobs))

print(f"Saved {len(jobs)} jobs to indeed_python_remote.json")
for job in jobs[:5]:
    pay = job.salary_text or "salary not listed"
    print(f"  {job.title} @ {job.company} ({job.location}) - {pay}, posted {job.date_posted}")

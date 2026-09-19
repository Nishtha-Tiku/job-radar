"""Check that job links still work. Direct company-board jobs come from live APIs, so they count as ok."""
from concurrent.futures import ThreadPoolExecutor

import requests

from .models import Job
from .sources import UA

LIVE_API_SOURCES = {"Greenhouse", "Lever", "Ashby"}
DEAD_PHRASES = (
    "no longer available", "no longer accepting", "position has been filled", "job is closed", "job has expired",
    "posting has expired", "this position is no longer", "job not found", "no longer open",
    "the job you are looking for is no longer",
)


def check(job: Job) -> str:
    """ok | dead | unverified (site blocked our check, so the link may still be fine)."""
    if job.source in LIVE_API_SOURCES:
        return "ok"
    try:
        r = requests.get(job.url, headers=UA, timeout=15, allow_redirects=True)
    except requests.RequestException:
        return "unverified"
    if r.status_code in (404, 410):
        return "dead"
    if r.status_code >= 400:
        return "unverified"
    text = r.text[:200000].lower()
    if any(p in text for p in DEAD_PHRASES):
        return "dead"
    return "ok"


def verify_all(jobs: list[Job], workers: int = 12) -> None:
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for job, status in zip(jobs, ex.map(check, jobs)):
            job.link_status = status

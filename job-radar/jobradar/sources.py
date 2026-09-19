"""Fetch jobs from legitimate public APIs. Every source fails soft: an error returns an empty list."""
import datetime as dt
import html
import re

import requests

from .models import Job

UA = {"User-Agent": "Mozilla/5.0 (compatible; job-radar/1.0; personal use)"}


def log(msg: str) -> None:
    print(msg, flush=True)


def strip_html(s: str) -> str:
    s = html.unescape(s or "")
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _get_json(url: str, **kw):
    try:
        r = requests.get(url, headers=UA, timeout=25, **kw)
        r.raise_for_status()
        return r.json()
    except Exception as e:  # noqa: BLE001
        log(f"  ! {url.split('?')[0]} -> {type(e).__name__}: {str(e)[:120]}")
        return None


def adzuna(cfg: dict, env) -> list[Job]:
    app_id, app_key = env.get("ADZUNA_APP_ID"), env.get("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        log("Adzuna: skipped (no ADZUNA_APP_ID / ADZUNA_APP_KEY)")
        return []
    jobs: list[Job] = []
    for term in cfg["search_terms"]:
        for page in range(1, int(cfg.get("adzuna_pages", 2)) + 1):
            data = _get_json(
                f"https://api.adzuna.com/v1/api/jobs/in/search/{page}",
                params={
                    "app_id": app_id,
                    "app_key": app_key,
                    "results_per_page": 50,
                    "what": term,
                    "max_days_old": cfg["max_days_old"],
                    "sort_by": "date",
                    "content-type": "application/json",
                },
            )
            results = (data or {}).get("results", [])
            for r in results:
                jobs.append(Job(
                    title=strip_html(r.get("title", "")),
                    company=strip_html((r.get("company") or {}).get("display_name", "")),
                    location=(r.get("location") or {}).get("display_name", ""),
                    url=r.get("redirect_url", ""),
                    source="Adzuna",
                    posted=(r.get("created") or "")[:10],
                    description=strip_html(r.get("description", "")),
                ))
            if len(results) < 50:
                break
    log(f"Adzuna: {len(jobs)} jobs")
    return jobs


def jooble(cfg: dict, env) -> list[Job]:
    key = env.get("JOOBLE_KEY")
    if not key:
        log("Jooble: skipped (no JOOBLE_KEY)")
        return []
    jobs: list[Job] = []
    for term in cfg["search_terms"]:
        try:
            r = requests.post(
                f"https://jooble.org/api/{key}",
                json={"keywords": term, "location": "India", "page": "1"},
                headers=UA, timeout=25,
            )
            r.raise_for_status()
            for j in r.json().get("jobs", []):
                jobs.append(Job(
                    title=strip_html(j.get("title", "")),
                    company=j.get("company", ""),
                    location=j.get("location", ""),
                    url=j.get("link", ""),
                    source="Jooble",
                    posted=(j.get("updated") or "")[:10],
                    description=strip_html(j.get("snippet", "")),
                ))
        except Exception as e:  # noqa: BLE001
            log(f"  ! Jooble '{term}' -> {type(e).__name__}: {str(e)[:120]}")
    log(f"Jooble: {len(jobs)} jobs")
    return jobs


def remotive(cfg: dict, env) -> list[Job]:
    data = _get_json("https://remotive.com/api/remote-jobs", params={"category": "software-dev", "search": "java"})
    jobs = []
    for j in (data or {}).get("jobs", []):
        jobs.append(Job(
            title=j.get("title", ""),
            company=j.get("company_name", ""),
            location=f"Remote ({j.get('candidate_required_location', '')})",
            url=j.get("url", ""),
            source="Remotive",
            posted=(j.get("publication_date") or "")[:10],
            description=strip_html(j.get("description", "")),
        ))
    log(f"Remotive: {len(jobs)} jobs")
    return jobs


def _board_name(slug: str) -> str:
    return slug.replace("-", " ").replace("_", " ").title()


def greenhouse(slug: str) -> list[Job]:
    data = _get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", params={"content": "true"})
    out = []
    for j in (data or {}).get("jobs", []):
        out.append(Job(
            title=j.get("title", ""),
            company=_board_name(slug),
            location=(j.get("location") or {}).get("name", ""),
            url=j.get("absolute_url", ""),
            source="Greenhouse",
            posted=(j.get("updated_at") or "")[:10],
            description=strip_html(j.get("content", "")),
        ))
    return out


def lever(slug: str) -> list[Job]:
    data = _get_json(f"https://api.lever.co/v0/postings/{slug}", params={"mode": "json"})
    out = []
    for j in data if isinstance(data, list) else []:
        created = j.get("createdAt")
        posted = dt.datetime.fromtimestamp(created / 1000, dt.timezone.utc).date().isoformat() if created else ""
        out.append(Job(
            title=j.get("text", ""),
            company=_board_name(slug),
            location=(j.get("categories") or {}).get("location", "") or "",
            url=j.get("hostedUrl", ""),
            source="Lever",
            posted=posted,
            description=j.get("descriptionPlain", "") or strip_html(j.get("description", "")),
        ))
    return out


def ashby(slug: str) -> list[Job]:
    data = _get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    out = []
    for j in (data or {}).get("jobs", []):
        if j.get("isListed") is False:
            continue
        out.append(Job(
            title=j.get("title", ""),
            company=_board_name(slug),
            location=j.get("location", "") or "",
            url=j.get("jobUrl", ""),
            source="Ashby",
            posted=(j.get("publishedAt") or "")[:10],
            description=j.get("descriptionPlain", "") or strip_html(j.get("descriptionHtml", "")),
        ))
    return out


def collect(cfg: dict, companies: dict, env) -> list[Job]:
    jobs: list[Job] = []
    enabled = cfg.get("sources", {})
    if enabled.get("adzuna", True):
        jobs += adzuna(cfg, env)
    if enabled.get("jooble", True):
        jobs += jooble(cfg, env)
    if enabled.get("remotive", True):
        jobs += remotive(cfg, env)
    for name, fn in (("greenhouse", greenhouse), ("lever", lever), ("ashby", ashby)):
        if not enabled.get(name, True):
            continue
        count = 0
        for slug in companies.get(name) or []:
            found = fn(slug)
            count += len(found)
            jobs += found
        log(f"{name.title()}: {count} jobs from {len(companies.get(name) or [])} boards")
    return jobs

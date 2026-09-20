import argparse
import datetime as dt
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from . import notify, state, tailor
from .match import choose, dedupe, filter_and_score, job_key, rank
from .models import Job
from .sources import collect, log
from .verify import verify_all

ROOT = Path(__file__).resolve().parent.parent


def load_yaml(name: str) -> dict:
    return yaml.safe_load((ROOT / name).read_text()) or {}


def main() -> int:
    ap = argparse.ArgumentParser(description="Daily job digest")
    ap.add_argument("--dry-run", action="store_true", help="print the result; send nothing, save nothing")
    ap.add_argument("--sample", help="read jobs from a JSON file instead of calling the APIs")
    ap.add_argument("--no-verify", action="store_true", help="skip link checking")
    ap.add_argument("--resume-dir", help="with --dry-run: write the tailored resume PDFs to this folder")
    args = ap.parse_args()

    cfg, companies = load_yaml("config.yaml"), load_yaml("companies.yaml")
    today = dt.datetime.now(ZoneInfo("Asia/Kolkata")).date()

    if args.sample:
        jobs = [Job(**j) for j in json.loads(Path(args.sample).read_text())]
    else:
        jobs = collect(cfg, companies, os.environ)
    log(f"Collected {len(jobs)} raw jobs")

    ignore_history = os.environ.get("IGNORE_HISTORY") == "1"   # used for test runs
    sent = {} if ignore_history else state.load()
    cands = dedupe(filter_and_score(jobs, cfg, today))
    cands = [j for j in cands if job_key(j) not in sent]
    log(f"{len(cands)} candidates match your profile and were not sent before")

    pool = rank(cands)[: int(cfg["verify_pool"])]
    if not args.no_verify:
        verify_all(pool)
    picked = choose(pool, cfg)
    dead = sum(1 for j in pool if j.link_status == "dead")
    live = sum(1 for j in picked if j.link_status == "ok")
    summary = (
        f"{len(picked)} of {cfg['target_count']} jobs for {today.strftime('%A, %d %B %Y')}. "
        f"Scanned {len(jobs)} postings, {len(cands)} matched your profile, {dead} dead links removed. "
        f"{live} links confirmed live, {len(picked) - live} could not be checked automatically (the site blocks bots)."
    )
    log(summary)

    if args.dry_run:
        if args.resume_dir:
            out_dir = Path(args.resume_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            for name, pdf, t in tailor.generate_all(picked, cfg, tailor.api_key(cfg.get("resumes", {}), os.environ)):
                (out_dir / name).write_bytes(pdf)
                log(f"  resume {name}: {t.mode}, fit={t.fit}, gaps={t.gaps}, notes={t.notes}")
        for i, j in enumerate(picked, 1):
            log(f"{i:>2}. [{j.score:>3}] {j.company} | {j.title} | {j.location} | {j.source} | {j.link_status}\n      {j.url}")
        return 0
    if not picked:
        log("Nothing to send today.")
        return 0

    notify.send_email(os.environ, picked, summary, today)
    resumes = None
    rcfg = cfg.get("resumes", {})
    if rcfg.get("enabled", True):
        try:
            key = tailor.api_key(rcfg, os.environ)
            if not key:
                log(f"Resumes: no API key for provider '{rcfg.get('provider', 'gemini')}', so generic (untailored) resumes will be made")
            resumes = tailor.generate_all(picked, cfg, key)
        except Exception as e:  # noqa: BLE001  (resumes must never stop the job list)
            log(f"Resumes: failed -> {type(e).__name__}: {e}")
    try:
        notify.post_sheet(os.environ, picked, today, resumes)
    except Exception as e:  # noqa: BLE001  (a sheet problem should not lose the email)
        log(f"Sheet: failed -> {type(e).__name__}: {e}")
    if not ignore_history:
        for j in picked:
            sent[job_key(j)] = today.isoformat()
        state.save(sent, today)
    return 0

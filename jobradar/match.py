"""Filtering and scoring jobs against Nishtha's resume (Java backend, integrations, 1-3 years)."""
import datetime as dt
import hashlib
import re

from .models import Job

I = re.I

INDIA_TERMS = (
    "india", "noida", "gurgaon", "gurugram", "delhi", "ncr", "faridabad", "ghaziabad", "bangalore", "bengaluru",
    "hyderabad", "pune", "mumbai", "navi mumbai", "thane", "chennai", "kolkata", "ahmedabad", "jaipur", "chandigarh",
    "mohali", "kochi", "cochin", "coimbatore", "indore", "nagpur", "trivandrum", "thiruvananthapuram",
    "bhubaneswar", "lucknow", "vadodara", "surat", "mysore", "mysuru", "visakhapatnam", "udaipur", "dehradun",
)
REMOTE_GLOBAL_OK = ("worldwide", "anywhere", "apac", "asia", "india")
TRUSTED_INDIA_SOURCES = {"Adzuna", "Jooble"}   # already searched with an India filter

TITLE_BAD = re.compile(
    r"\b(senior|sr\.?|lead|principal|manager|head|director|vp|architect|intern|internship|trainee|fresher|freshers"
    r"|graduate|consultant|associate director)\b"
    r"|\bstaff\s+(software|engineer|developer|backend)\b"
    r"|\b(sde|engineer|developer|swe)\s*[-–]?\s*(iii|3|iv|4|v|5)\b",
    I,
)
OTHER_STACK = re.compile(
    r"(\.net|dotnet|\bphp\b|\bruby\b|golang|\bgo (developer|engineer)\b|android|\bios\b|flutter|react native|angular"
    r"|node\.?js|data scientist|data engineer|devops|\bqa\b|\bsdet\b|test engineer|salesforce|abap|c\+\+|embedded"
    r"|firmware|machine learning engineer|\bsre\b|support engineer|business analyst)",
    I,
)
JAVA_SIGNAL = re.compile(r"java(?!script)|spring boot|kafka|camel|quarkus", I)
TITLE_JAVA = re.compile(r"java(?!script)|spring|kafka|camel|backend|back-end|back end|integration|microservice", I)
TITLE_GENERIC = re.compile(r"software (engineer|developer)|\bsde\b|developer|engineer|programmer|application|member of technical staff|\bmts\b", I)

WEIGHTS = [
    (r"java(?!script)", 4), (r"spring boot", 5), (r"\bspring\b", 2), (r"kafka", 3), (r"camel", 4),
    (r"microservice", 3), (r"restful|rest api", 2), (r"integration", 3),
    (r"\berp\b|netsuite|dynamics 365|\bsap\b", 3), (r"graphql", 2), (r"postgres|mysql|\bsql\b", 2),
    (r"hibernate|\bjpa\b", 2), (r"docker|kubernetes", 1), (r"oauth|\bjwt\b", 1), (r"quarkus", 3),
    (r"\brag\b|\bllm\b|spring ai|langchain", 2), (r"junit|mockito", 1),
]

_NUM = r"(\d{1,2})\s*(?:\+|plus)?\s*(?:-|–|—|to)?\s*(\d{1,2})?\s*\+?\s*(?:years?|yrs?)"
_EXP_A = re.compile(_NUM + r"[^.\n]{0,40}?experience", I)
_EXP_B = re.compile(r"experience[^.\n\d]{0,40}?" + _NUM, I)


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def job_key(j: Job) -> str:
    return hashlib.sha1(f"{norm(j.company)}|{norm(j.title)}|{norm(j.location)}".encode()).hexdigest()[:16]


def parse_date(s: str):
    try:
        return dt.date.fromisoformat((s or "")[:10])
    except ValueError:
        return None


def min_years(text: str):
    """Smallest 'N years of experience' figure mentioned in the description, or None."""
    vals = []
    for rx in (_EXP_A, _EXP_B):
        for m in rx.finditer((text or "")[:8000]):
            vals.append(int(m.group(1)))
    return min(vals) if vals else None


def is_india(j: Job) -> bool:
    if j.source in TRUSTED_INDIA_SOURCES:
        return True
    loc = (j.location or "").lower()
    if any(t in loc for t in INDIA_TERMS):
        return True
    return j.source == "Remotive" and any(t in loc for t in REMOTE_GLOBAL_OK)


def relevant(j: Job) -> bool:
    t = j.title.lower()
    blob = f"{t} {(j.description or '').lower()[:6000]}"
    if TITLE_BAD.search(t):
        return False
    if OTHER_STACK.search(t) and "java" not in t.replace("javascript", ""):
        return False
    if not JAVA_SIGNAL.search(blob):
        return False
    return bool(TITLE_JAVA.search(t) or TITLE_GENERIC.search(t))


def score(j: Job, today: dt.date) -> int:
    t = j.title.lower()
    d = (j.description or "").lower()[:6000]
    raw = 0
    for pat, w in WEIGHTS:
        if re.search(pat, t):
            raw += w * 2
        elif re.search(pat, d):
            raw += w
    s = min(100, int(raw * 3.2))
    posted = parse_date(j.posted)
    if posted:
        age = (today - posted).days
        s += 10 if age <= 1 else 5 if age <= 3 else 0
    yrs = min_years(j.description)
    if yrs is not None and 1 <= yrs <= 3:
        s += 5
    return min(100, s)


def filter_and_score(jobs: list[Job], cfg: dict, today: dt.date) -> list[Job]:
    out = []
    for j in jobs:
        if not (j.url and j.title and j.company):
            continue
        if not is_india(j) or not relevant(j):
            continue
        posted = parse_date(j.posted)
        if posted and (today - posted).days > int(cfg["max_days_old"]):
            continue
        yrs = min_years(j.description)
        if yrs is not None and yrs > int(cfg["max_min_years"]):
            continue
        j.score = score(j, today)
        if j.score >= int(cfg["min_score"]):
            out.append(j)
    return out


SOURCE_PRIORITY = {"Greenhouse": 0, "Lever": 0, "Ashby": 0, "Adzuna": 1, "Jooble": 2, "Remotive": 2}


def dedupe(jobs: list[Job]) -> list[Job]:
    """One entry per (company, title, location); prefer direct company boards over aggregators."""
    best: dict[str, Job] = {}
    for j in sorted(jobs, key=lambda x: SOURCE_PRIORITY.get(x.source, 3)):
        best.setdefault(job_key(j), j)
    return list(best.values())


def rank(jobs: list[Job]) -> list[Job]:
    jobs = sorted(jobs, key=lambda j: j.posted or "", reverse=True)   # newest first...
    return sorted(jobs, key=lambda j: j.score, reverse=True)          # ...then best match first (stable)


def choose(ranked: list[Job], cfg: dict) -> list[Job]:
    """Pick up to target_count jobs, preferring one job per company."""
    n = int(cfg["target_count"])
    picked: list[Job] = []
    per: dict[str, int] = {}
    ids: set[int] = set()

    def take(limit: int) -> None:
        for j in ranked:
            if len(picked) >= n:
                return
            if id(j) in ids or j.link_status == "dead":
                continue
            c = norm(j.company)
            if per.get(c, 0) < limit:
                picked.append(j)
                ids.add(id(j))
                per[c] = per.get(c, 0) + 1

    take(int(cfg["max_per_company"]))
    if len(picked) < n:
        take(int(cfg["max_per_company_fallback"]))
    return sorted(picked, key=lambda j: j.score, reverse=True)

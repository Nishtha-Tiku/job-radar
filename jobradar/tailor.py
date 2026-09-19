"""Create a tailored one-page resume for each job, using only facts from master_resume.json.

The model does the recruiter-style analysis and rewrites bullets (Google XYZ formula).
Everything it returns is then checked by code, and any bullet that breaks a rule is replaced by the
original master bullet, so the resume can never contain invented numbers, tools or the company name.
"""
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import requests

from . import resume_pdf
from .match import norm
from .models import Job
from .sources import log

ROOT = Path(__file__).resolve().parent.parent
NUM_RE = re.compile(r"\d+(?:\.\d+)?")
COMPANY_STOP = {
    "technologies", "technology", "solutions", "private", "limited", "pvt", "ltd", "inc", "llc", "india", "global",
    "services", "systems", "software", "group", "labs", "the", "and", "corp", "corporation", "company", "consulting",
    "digital", "tech", "infotech", "enterprises", "international", "bank", "financial", "finance",
}
# Technologies she has NOT listed. If the model writes one of these it is rejected unless the master resume has it.
WATCHLIST = [
    "aws", "azure", "gcp", "google cloud", "jenkins", "terraform", "ansible", "angular", "vue", "mongodb", "cassandra",
    "elasticsearch", "rabbitmq", "node.js", "golang", "scala", "kotlin", "hadoop", "apache spark", "airflow", "snowflake",
    "datadog", "splunk", "prometheus", "new relic", "grpc", "jira", "selenium", "cypress", "tensorflow", "pytorch",
    "django", "spring cloud", "kubernetes operators", "helm", "argo", "gitlab ci", "github actions", "sonarcloud",
    "oracle database", "sap abap", "salesforce", "servicenow", "mulesoft", "tibco", "webmethods", "ibm mq", "activemq",
    "openshift", "istio", "nginx", "linux administration", "c#", ".net", "php", "ruby",
]
FIRST_PERSON = re.compile(r"\b(i|my|me|i've|i'm)\b", re.I)


def load_master() -> dict:
    return json.loads((ROOT / "master_resume.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- text safety

def clean(text: str) -> str:
    """Remove em/en dashes and any non-ASCII characters so nothing odd reaches the PDF."""
    t = str(text or "")
    t = re.sub(r"\s*\u2014\s*", ", ", t)
    t = re.sub(r"\s*\u2013\s*", "-", t)
    for a, b in {"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2026": "...", "\u00a0": " "}.items():
        t = t.replace(a, b)
    t = t.encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t).strip()


def numbers(text: str) -> set:
    return set(NUM_RE.findall(text or ""))


def master_text(master: dict) -> str:
    return json.dumps(master).lower()


def fact_text(master: dict) -> str:
    """All human-written facts (no ids, urls or phone number), used to decide which numbers are allowed."""
    parts = [master["summary_base"]]
    for job in master["experience"]:
        parts += [b["text"] for b in job["bullets"]]
    for p in master["projects"]:
        parts += [b["text"] for b in p["bullets"]]
    parts += [i for items in master["skills"].values() for i in items]
    parts += [master["education"]["score"]] + master["certifications"]
    return " ".join(parts)


def bullet_index(master: dict) -> dict:
    idx = {}
    for job in master["experience"]:
        for b in job["bullets"]:
            idx[b["id"]] = b["text"]
    for p in master["projects"]:
        for b in p["bullets"]:
            idx[b["id"]] = b["text"]
    return idx


def company_tokens(company: str, master_lower: str) -> list:
    words = re.findall(r"[a-z0-9]+", (company or "").lower())
    return [w for w in words if len(w) >= 3 and w not in COMPANY_STOP and not re.search(rf"\b{re.escape(w)}\b", master_lower)]


def mentions_company(text: str, tokens: list) -> bool:
    low = (text or "").lower()
    return any(re.search(rf"\b{re.escape(t)}\b", low) for t in tokens)


def violations(text: str, tokens: list, master_lower: str) -> list:
    """Reasons a piece of generated text is not allowed."""
    low = text.lower()
    out = []
    if "\u2014" in text or "\u2013" in text:
        out.append("dash")
    if mentions_company(text, tokens):
        out.append("company")
    for term in WATCHLIST:
        if term not in master_lower and re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", low):
            out.append(f"unlisted tech: {term}")
    if re.search(r"peer[- ]reviewed|impact factor", low):
        out.append("paper claim")
    return out


# ---------------------------------------------------------------- validation of model output

@dataclass
class Tailored:
    content: dict
    fit: object = ""
    gaps: str = ""
    mode: str = "ai"
    notes: list = field(default_factory=list)


def fallback_content(master: dict, job: Job) -> dict:
    """No AI: master bullets ranked by overlap with the job description, otherwise unchanged."""
    jd = set(re.findall(r"[a-z][a-z+#.]{2,}", f"{job.title} {job.description}".lower()))
    def rel(t):
        return len(jd & set(re.findall(r"[a-z][a-z+#.]{2,}", t.lower())))
    exp = sorted(master["experience"][0]["bullets"], key=lambda b: -rel(b["text"]))[:6]
    projs = sorted(master["projects"], key=lambda p: -sum(rel(b["text"]) for b in p["bullets"]))[:2]
    return {
        "summary": master["summary_base"],
        "skills": master["skills"],
        "experience": [b["text"] for b in exp],
        "projects": [{"name": p["name"], "dates": p["dates"], "stack": p["stack"], "bullets": [b["text"] for b in p["bullets"]]}
                     for p in projs],
    }


def validate(out: dict, master: dict, job: Job) -> Tailored:
    """Turn raw model JSON into safe resume content. Bad pieces revert to master text."""
    mlow = master_text(master)
    tokens = company_tokens(job.company, mlow)
    idx = bullet_index(master)
    all_nums = numbers(fact_text(master))
    notes = []

    def safe_bullet(text, ids):
        text = clean(text)
        ids = [i for i in (ids or []) if i in idx]
        if not text or not ids:
            return None
        allowed = set().union(*[numbers(idx[i]) for i in ids])
        if not numbers(text) <= allowed:
            notes.append("number not in source bullet")
            return idx[ids[0]]
        problems = violations(text, tokens, mlow)
        if len(text.split()) > 42 or problems:
            notes.append("bullet reverted: " + (",".join(problems) or "too long"))
            return idx[ids[0]]
        return text

    exp = []
    for b in (out.get("experience") or [])[:8]:
        t = safe_bullet(b.get("text"), b.get("source_ids"))
        if t and t not in exp:
            exp.append(t)
    base_exp = fallback_content(master, job)["experience"]
    for t in base_exp:                               # make sure there are enough bullets
        if len(exp) >= 5:
            break
        if t not in exp:
            exp.append(t)

    projs = []
    pmap = {p["id"]: p for p in master["projects"]}
    for p in (out.get("projects") or [])[:3]:
        src = pmap.get(p.get("project_id"))
        if not src:
            continue
        pid_ids = {b["id"] for b in src["bullets"]}
        bl = []
        for b in (p.get("bullets") or [])[:2]:
            ids = [i for i in (b.get("source_ids") or []) if i in pid_ids]
            t = safe_bullet(b.get("text"), ids)
            if t:
                bl.append(t)
        if bl:
            projs.append({"name": src["name"], "dates": src["dates"], "stack": src["stack"], "bullets": bl})
    if not projs:
        projs = fallback_content(master, job)["projects"]
    projs = projs[:3]

    summary = clean(out.get("summary"))
    if (not summary or FIRST_PERSON.search(summary) or len(summary.split()) > 60 or not numbers(summary) <= all_nums
            or violations(summary, tokens, mlow)):
        notes.append("summary reverted")
        summary = master["summary_base"]

    skill_map = {norm(i): i for items in master["skills"].values() for i in items}
    skills = {}
    for group, items in (out.get("skills") or {}).items():
        if group not in master["skills"]:
            continue
        picked = []
        for it in items or []:
            canon = skill_map.get(norm(clean(it)))
            if canon and canon not in picked:
                picked.append(canon)
        if picked:
            skills[group] = picked
    if len(skills) < 3:
        notes.append("skills reverted")
        skills = master["skills"]

    gaps = [clean(k) for k in (out.get("missing_keywords") or [])][:5]
    fit = out.get("match_score")
    fit = int(fit) if isinstance(fit, (int, float)) and 0 <= fit <= 100 else ""
    return Tailored({"summary": summary, "skills": skills, "experience": exp[:7], "projects": projs},
                    fit=fit, gaps=", ".join(gaps), mode="ai", notes=notes)


# ---------------------------------------------------------------- the model call

SYSTEM = """You are two people at once: a Senior Recruiter hiring for the exact role described, and an ATS filter.
Work through three passes silently, then output only the final JSON.

PASS 1 - Analyse the candidate facts against the job description.
  a) match_score: an honest integer out of 100.
  b) missing_keywords: the top 5 keywords or skills the job wants that the candidate facts do NOT support.
  c) red_flags: the 3 biggest things a hiring manager would notice in the first 10 seconds.
PASS 2 - Rewrite the experience bullets with the Google XYZ formula: accomplished X, as measured by Y, by doing Z.
  Make each bullet specific, achievement-focused, relevant to the job and easy for an ATS to scan.
  Work in a keyword from the job description ONLY when the candidate facts genuinely support it.
PASS 3 - Act as an ATS and a manager scanning 200 resumes. Find bullets that would be skipped, or are vague,
  repetitive or irrelevant to this role. Rewrite or drop them. Order everything by relevance to the job.

HARD RULES
- Use only the candidate facts provided. Never invent achievements, numbers, tools, skills, employers or experience.
- Every bullet must list source_ids (the ids of the fact bullets it rewrites). A number may appear in a rewritten
  bullet only if it appears in its source bullet. If a metric is missing, write the bullet without one.
- Never mention the hiring company's name or its products. Never use em dashes or en dashes; use commas, "to" or hyphens.
- Do not say "peer-reviewed" and do not mention any impact factor.
- Skills: pick only from the allowed skill lists, exact strings, most relevant first.
- Summary: at most 45 words, no first-person pronouns, built only from supported facts.
- 5 to 7 experience bullets, at most 32 words each. Choose the 2 most relevant projects, 1 or 2 bullets each.

OUTPUT: one JSON object and nothing else:
{"match_score": 0, "missing_keywords": ["","","","",""], "red_flags": ["","",""],
 "summary": "", "skills": {"Core": [], "Testing & Security": [], "Databases": [], "DevOps": [], "Generative AI": [], "Additional": []},
 "experience": [{"source_ids": ["e1"], "text": ""}],
 "projects": [{"project_id": "rag", "bullets": [{"source_ids": ["p1"], "text": ""}]}]}"""


def build_user_prompt(master: dict, job: Job, max_chars: int) -> str:
    facts = {
        "summary": master["summary_base"],
        "experience_bullets": [{"id": b["id"], "text": b["text"]} for b in master["experience"][0]["bullets"]],
        "projects": [{"project_id": p["id"], "name": p["name"], "stack": p["stack"],
                      "bullets": [{"id": b["id"], "text": b["text"]} for b in p["bullets"]]} for p in master["projects"]],
        "allowed_skills": master["skills"],
    }
    return (f"JOB TITLE: {job.title}\nLOCATION: {job.location}\n\nJOB DESCRIPTION:\n{(job.description or '')[:max_chars]}\n\n"
            f"CANDIDATE FACTS (the only source of truth):\n{json.dumps(facts, indent=1)}")


def call_claude(system: str, user: str, model: str, key: str) -> str:
    last = ""
    for attempt in range(5):
        try:
            r = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": model, "max_tokens": 3000, "temperature": 0.2, "system": system,
                      "messages": [{"role": "user", "content": user}]},
                timeout=120,
            )
        except requests.RequestException as e:
            last = type(e).__name__
            time.sleep(4 * (attempt + 1))
            continue
        if r.status_code in (429, 500, 502, 503, 529):
            last = f"HTTP {r.status_code}"
            time.sleep(6 * (attempt + 1))
            continue
        if r.status_code >= 400:
            raise RuntimeError(f"Anthropic API HTTP {r.status_code}: {r.text[:200]}")
        return "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
    raise RuntimeError(f"Anthropic API kept failing ({last})")


def parse_json(text: str) -> dict:
    s, e = text.find("{"), text.rfind("}")
    if s < 0 or e <= s:
        raise ValueError("no JSON in model reply")
    return json.loads(text[s:e + 1])


# ---------------------------------------------------------------- public entry points

def tailor_one(job: Job, master: dict, cfg: dict, key: str) -> Tailored:
    try:
        raw = call_claude(SYSTEM, build_user_prompt(master, job, int(cfg.get("max_jd_chars", 6000))),
                          cfg.get("model", "claude-sonnet-5"), key)
        return validate(parse_json(raw), master, job)
    except Exception as e:  # noqa: BLE001
        log(f"  ! tailoring failed for {job.company} / {job.title}: {type(e).__name__}: {str(e)[:150]}")
        return Tailored(fallback_content(master, job), mode="fallback", notes=[str(e)[:100]])


def file_name(job: Job, n: int, master: dict) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", job.title).strip("_")[:40]
    if mentions_company(slug.replace("_", " "), company_tokens(job.company, master_text(master))):
        slug = "Resume"
    return f"Nishtha_Tiku_{slug}_{n:02d}.pdf"


def generate_all(jobs: list, cfg: dict, key: str, master: dict = None):
    """Return a list of (file_name, pdf_bytes, Tailored) aligned with jobs."""
    master = master or load_master()
    rcfg = cfg.get("resumes", {})

    def work(args):
        n, job = args
        t = tailor_one(job, master, rcfg, key) if key else Tailored(fallback_content(master, job), mode="fallback")
        pdf = resume_pdf.render_one_page(t.content, master)
        return file_name(job, n, master), pdf, t

    with ThreadPoolExecutor(max_workers=int(rcfg.get("workers", 4))) as ex:
        results = list(ex.map(work, list(enumerate(jobs, 1))))
    ai = sum(1 for _, _, t in results if t.mode == "ai")
    log(f"Resumes: {len(results)} generated ({ai} tailored by AI, {len(results) - ai} fallback)")
    return results

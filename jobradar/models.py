from dataclasses import dataclass


@dataclass
class Job:
    title: str
    company: str
    location: str
    url: str
    source: str
    posted: str = ""          # ISO date, e.g. 2026-09-19
    description: str = ""
    score: int = 0
    link_status: str = "unchecked"   # ok | unverified | dead | unchecked

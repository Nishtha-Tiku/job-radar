import datetime as dt
import json
import unittest
from pathlib import Path

from jobradar.match import choose, dedupe, filter_and_score, is_india, min_years, rank, relevant
from jobradar.models import Job

CFG = {"max_days_old": 7, "max_min_years": 3, "min_score": 20, "target_count": 50,
       "max_per_company": 1, "max_per_company_fallback": 3}
TODAY = dt.date(2026, 9, 19)
SAMPLE = [Job(**j) for j in json.loads((Path(__file__).parent / "sample_jobs.json").read_text())]


def by_company(jobs):
    return {j.company for j in jobs}


class MatchTests(unittest.TestCase):
    def test_min_years(self):
        self.assertEqual(min_years("Need 1-3 years of experience"), 1)
        self.assertEqual(min_years("5+ years experience in Java"), 5)
        self.assertEqual(min_years("Experience of 2 to 4 years required"), 2)
        self.assertIsNone(min_years("We have been in business for 20 years"))

    def test_location(self):
        self.assertTrue(is_india(Job("t", "c", "Gurugram", "u", "Lever")))
        self.assertFalse(is_india(Job("t", "c", "San Francisco, CA", "u", "Greenhouse")))
        self.assertTrue(is_india(Job("t", "c", "Remote (Worldwide)", "u", "Remotive")))
        self.assertFalse(is_india(Job("t", "c", "Remote", "u", "Greenhouse")))

    def test_relevance(self):
        self.assertFalse(relevant(Job("Senior Java Developer", "c", "x", "u", "s", description="Java")))
        self.assertFalse(relevant(Job("Java Intern", "c", "x", "u", "s", description="Java")))
        self.assertFalse(relevant(Job(".NET Developer", "c", "x", "u", "s", description="c# java")))
        self.assertFalse(relevant(Job("Backend Engineer", "c", "x", "u", "s", description="Python and Go")))
        self.assertTrue(relevant(Job("Backend Engineer", "c", "x", "u", "s", description="Java and Spring Boot")))
        self.assertTrue(relevant(Job("Member of Technical Staff", "c", "x", "u", "s", description="Java, Kafka")))
        self.assertFalse(relevant(Job("Staff Software Engineer", "c", "x", "u", "s", description="Java")))

    def test_pipeline_on_sample(self):
        out = filter_and_score([Job(**j.__dict__) for j in SAMPLE], CFG, TODAY)
        companies = by_company(out)
        self.assertIn("Sample Corp A", companies)   # Java/Spring/Kafka, 1-3 yrs
        self.assertIn("Sample Corp B", companies)   # Camel integration
        self.assertIn("Sample Corp H", companies)   # Java backend on Lever, India
        self.assertIn("Sample Corp J", companies)   # remote worldwide
        self.assertIn("Sample Corp L", companies)   # MTS with Java
        for bad in ("C", "D", "E", "F", "G", "I", "K"):
            self.assertNotIn(f"Sample Corp {bad}", companies, bad)

    def test_dedupe_prefers_company_board_and_one_per_company(self):
        out = filter_and_score([Job(**j.__dict__) for j in SAMPLE], CFG, TODAY)
        out = dedupe(out)
        a_jobs = [j for j in out if j.company == "Sample Corp A" and j.title == "Java Backend Developer"]
        self.assertEqual(len(a_jobs), 1)
        picked = choose(rank(out), CFG)
        per = {}
        for j in picked:
            per[j.company] = per.get(j.company, 0) + 1
        self.assertTrue(all(v <= 3 for v in per.values()))
        self.assertEqual(per["Sample Corp A"], 2)   # fallback pass allows a second listing
        first_pass = choose(rank(out), {**CFG, "target_count": 3})
        self.assertEqual(len({j.company for j in first_pass}), len(first_pass))

    def test_dead_links_are_excluded(self):
        out = dedupe(filter_and_score([Job(**j.__dict__) for j in SAMPLE], CFG, TODAY))
        out[0].link_status = "dead"
        dead_company = out[0].company
        picked = choose(rank(out), {**CFG, "max_per_company_fallback": 1})
        self.assertNotIn(out[0], picked)
        self.assertTrue(dead_company not in by_company(picked) or len([j for j in out if j.company == dead_company]) > 1)


if __name__ == "__main__":
    unittest.main()

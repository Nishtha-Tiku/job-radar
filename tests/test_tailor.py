import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from jobradar import resume_pdf, tailor
from jobradar.models import Job

MASTER = tailor.load_master()
JOB = Job(title="Java Backend Developer", company="Zephyr Payments Pvt Ltd", location="Noida", url="u", source="Adzuna",
          description="Java, Spring Boot, Kafka, Redis, microservices, REST APIs, PostgreSQL. Zephyr Payments builds UPI products. "
                      "2 years experience. Nice to have: AWS, Docker.")


def good_output():
    return {
        "match_score": 78,
        "missing_keywords": ["AWS", "UPI", "Payments domain", "Spring Cloud", "Terraform"],
        "red_flags": ["a", "b", "c"],
        "summary": "Java backend developer with 3 years of experience building secure Spring Boot microservices and Kafka event-driven integrations.",
        "skills": {"Core": ["spring boot", "Apache Kafka", "Redis", "Not A Real Skill"], "Databases": ["PostgreSQL", "SQL"],
                   "DevOps": ["Docker", "Kubernetes"], "Testing & Security": ["JUnit", "OAuth2"]},
        "experience": [
            {"source_ids": ["e1"], "text": "Cut manual ERP data entry by 60% by architecting a bidirectional sync Spring Boot microservice across enterprise ERPs."},
            {"source_ids": ["e2"], "text": "Accelerated releases by about 40% by automating 20+ REST APIs and Kafka workflows across 4 ERP platforms."},
            {"source_ids": ["e6"], "text": "Improved integration sync throughput by implementing Redis caching for frequently accessed data."},
            {"source_ids": ["e4"], "text": "Mitigated OWASP Top 10 risks by implementing OAuth2 JWT authentication \u2014 a custom Camel interceptor."},
            {"source_ids": ["e5"], "text": "Cut connector effort by 90% by following TDD with JUnit and Mockito."},          # invented number
            {"source_ids": ["e7"], "text": "Cut repeat production issues by 30-40% by reviewing 150+ pull requests for Zephyr Payments."},  # company
            {"source_ids": ["e3"], "text": "Integrated NetSuite, Dynamics 365 and SAP on AWS to eliminate manual workflows."},  # unlisted tech
        ],
        "projects": [{"project_id": "rag", "bullets": [{"source_ids": ["p1"], "text": "Achieved 85% answer relevance on a 50-question evaluation set with hybrid BM25 and vector search."}]},
                     {"project_id": "llm", "bullets": [{"source_ids": ["p3"], "text": "Achieved 92% field-level extraction accuracy on a 30-document evaluation set."}]}],
    }


def pdf_text(pdf: bytes) -> str:
    if not shutil.which("pdftotext"):
        return ""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "r.pdf"
        p.write_bytes(pdf)
        return subprocess.run(["pdftotext", str(p), "-"], capture_output=True, text=True).stdout


def page_count(pdf: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page[^s]", pdf))


class TailorTests(unittest.TestCase):
    def test_clean_removes_dashes(self):
        self.assertNotIn("\u2014", tailor.clean("a \u2014 b"))
        self.assertEqual(tailor.clean("35\u201345%"), "35-45%")

    def test_bad_bullets_revert_to_master(self):
        t = tailor.validate(good_output(), MASTER, JOB)
        text = " ".join(t.content["experience"])
        self.assertNotIn("90%", text)
        self.assertNotIn("Zephyr", text)
        self.assertNotIn("AWS", text)
        self.assertNotIn("\u2014", text)
        self.assertIn("Cut manual ERP data entry by 60%", text)
        self.assertGreaterEqual(len(t.notes), 3)

    def test_skills_only_from_master(self):
        t = tailor.validate(good_output(), MASTER, JOB)
        allowed = {i for v in MASTER["skills"].values() for i in v}
        for items in t.content["skills"].values():
            for it in items:
                self.assertIn(it, allowed)
        self.assertNotIn("Not A Real Skill", sum(t.content["skills"].values(), []))
        self.assertEqual(t.content["skills"]["Core"][0], "Spring Boot")

    def test_summary_with_new_number_reverts(self):
        out = good_output()
        out["summary"] = "Java developer with 7 years of experience."
        self.assertEqual(tailor.validate(out, MASTER, JOB).content["summary"], MASTER["summary_base"])

    def test_meta(self):
        t = tailor.validate(good_output(), MASTER, JOB)
        self.assertEqual(t.fit, 78)
        self.assertIn("AWS", t.gaps)

    def test_company_tokens_ignore_common_words(self):
        self.assertEqual(tailor.company_tokens("Zephyr Payments Pvt Ltd", tailor.master_text(MASTER)), ["zephyr", "payments"])

    def test_pdf_is_one_page_and_clean(self):
        for content in (tailor.validate(good_output(), MASTER, JOB).content, tailor.fallback_content(MASTER, JOB)):
            pdf = resume_pdf.render_one_page(content, MASTER)
            self.assertEqual(page_count(pdf), 1)
            text = pdf_text(pdf)
            if text:
                self.assertNotIn("\u2014", text)
                self.assertNotIn("\u2013", text)
                self.assertNotIn("zephyr", text.lower())

    def test_parse_json_handles_fences(self):
        self.assertEqual(tailor.parse_json('```json\n{"a": 1}\n```'), {"a": 1})

    def test_file_name_has_no_company(self):
        job = Job("Zephyr Java Developer", "Zephyr Payments", "x", "u", "s")
        self.assertNotIn("Zephyr", tailor.file_name(job, 1, MASTER))


class ProviderTests(unittest.TestCase):
    def test_gemini_reply_is_parsed(self):
        from unittest import mock
        fake = mock.Mock(status_code=200)
        fake.json.return_value = {"candidates": [{"content": {"parts": [{"text": '{"match_score": 70}'}]}}]}
        with mock.patch("jobradar.tailor.requests.post", return_value=fake) as post:
            text = tailor.call_gemini("sys", "user", "some-model", "KEY", rpm=0)
        self.assertEqual(tailor.parse_json(text), {"match_score": 70})
        self.assertIn("some-model:generateContent", post.call_args[0][0])
        self.assertEqual(post.call_args[1]["headers"]["x-goog-api-key"], "KEY")

    def test_api_key_follows_provider(self):
        env = {"GEMINI_API_KEY": "g", "ANTHROPIC_API_KEY": "a"}
        self.assertEqual(tailor.api_key({"provider": "gemini"}, env), "g")
        self.assertEqual(tailor.api_key({"provider": "anthropic"}, env), "a")

    def test_bad_model_reply_falls_back(self):
        from unittest import mock
        with mock.patch("jobradar.tailor.call_model", return_value="sorry, no json"):
            t = tailor.tailor_one(JOB, MASTER, {"provider": "gemini"}, "KEY")
        self.assertEqual(t.mode, "fallback")


if __name__ == "__main__":
    unittest.main()

import re
from typing import Optional

from tracker.models import MatchResult, RawJob, StructuredResume

# Common tech terms to extract from job descriptions
TECH_TERMS = {
    "python", "java", "javascript", "typescript", "go", "golang", "rust",
    "c++", "c#", "csharp", "ruby", "scala", "kotlin", "swift",
    "php", "perl", "lua", "matlab", "julia", "dart",
    "react", "angular", "vue", "svelte", "nextjs", "nuxt",
    "node", "nodejs", "deno", "express", "django", "flask", "fastapi",
    "spring", "springboot", "rails", "asp.net",
    "sql", "mysql", "postgresql", "postgres", "mongodb", "redis",
    "cassandra", "dynamodb", "elasticsearch", "bigquery", "snowflake",
    "aws", "gcp", "azure", "docker", "kubernetes", "k8s", "terraform",
    "git", "github", "gitlab", "ci/cd", "jenkins",
    "tensorflow", "pytorch", "keras", "scikit-learn", "sklearn",
    "numpy", "pandas", "matplotlib", "seaborn",
    "machine learning", "deep learning", "nlp", "llm", "ai",
    "data science", "data analysis", "statistics", "probability",
    "causal inference", "monte carlo", "time series",
    "spark", "hadoop", "kafka", "airflow", "beam",
    "tableau", "power bi", "looker",
    "excel", "vba", "sas", "spss",
    "html", "css", "sass", "tailwind", "bootstrap",
    "graphql", "rest", "grpc", "api",
    "linux", "unix", "bash", "shell", "powershell",
    "agile", "scrum", "jira", "confluence",
    "algorithms", "data structures", "dsa",
    "linear algebra", "calculus", "discrete mathematics",
    "quantitative", "quant", "trading", "risk", "finance",
    "options", "derivatives", "backtesting", "var",
    "geospatial", "gis", "real-time",
}


def extract_keywords(text: str | None) -> set[str]:
    if not text:
        return set()
    text_lower = text.lower()
    found: set[str] = set()

    for term in TECH_TERMS:
        if len(term) <= 2:
            pattern = re.compile(r"\b" + re.escape(term) + r"\b")
            if pattern.search(text_lower):
                found.add(term)
        else:
            if term in text_lower:
                found.add(term)

    year_pattern = re.compile(r"\b(20\d{2})\b")
    for match in year_pattern.finditer(text_lower):
        found.add(match.group(1))

    return found


def extract_required_skills(job: RawJob) -> set[str]:
    combined = job.title
    if job.description:
        combined += " " + job.description
    return extract_keywords(combined)


class JobMatcher:
    def score(self, job: RawJob, resume: StructuredResume) -> MatchResult:
        required = extract_required_skills(job)
        if not required:
            return MatchResult(score=0, reasons=["No technical keywords found in job posting"])

        resume_skills_lower = {s.lower() for s in resume.skills}
        projects_text = " ".join(resume.projects).lower()

        matched: list[str] = []
        for skill in sorted(required):
            if skill.lower() in resume_skills_lower or skill.lower() in projects_text:
                matched.append(skill)

        if matched:
            score = int(round(len(matched) / len(required) * 100))
        else:
            score = 0

        if score > 100:
            score = 100

        return MatchResult(
            score=score,
            reasons=matched if matched else ["No skills matched"],
        )

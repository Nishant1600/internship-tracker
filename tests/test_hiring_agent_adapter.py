import json
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from tracker.config import HiringAgentConfig
from tracker.matching.hiring_agent import HiringAgentAdapter, _hash_pdf, _parse_cache_json
from tracker.matching.resume_fallback import HEMANG_RESUME_FALLBACK


def make_sample_cache() -> dict:
    return {
        "basics": {"name": "Hemang Varshney"},
        "skills": [
            {"name": "Python", "keywords": ["NumPy", "Pandas"]},
            {"name": "C++", "keywords": None},
        ],
        "work": [
            {"name": "Zetheta Algorithms", "position": "Quantitative Risk Analyst Intern", "summary": ""}
        ],
        "education": [
            {"institution": "University of Delhi", "area": "Computer Science Engineering", "studyType": "BTech"}
        ],
        "projects": [
            {"name": "Kelly Betting", "description": "Monte Carlo simulation", "technologies": ["Python", "NumPy"]}
        ],
        "certificates": [
            {"name": "Akuna Options 101", "issuer": "Akuna Capital"}
        ],
    }


class TestParseCacheJson:
    def test_parses_full_resume(self):
        data = make_sample_cache()
        result = _parse_cache_json(data)
        assert result.name == "Hemang Varshney"
        assert "Python" in result.skills
        assert "NumPy" in result.skills
        assert len(result.work) == 1
        assert len(result.education) == 1
        assert len(result.projects) == 1
        assert len(result.certifications) == 1

    def test_handles_empty_data(self):
        result = _parse_cache_json({})
        assert result.name == "Unknown"
        assert result.skills == []


class TestHashPdf:
    def test_hash_is_consistent(self, tmp_path):
        pdf = tmp_path / "resume.pdf"
        pdf.write_bytes(b"test pdf content")
        h1 = _hash_pdf(pdf)
        h2 = _hash_pdf(pdf)
        assert h1 == h2

    def test_hash_changes_on_content(self, tmp_path):
        pdf1 = tmp_path / "resume1.pdf"
        pdf2 = tmp_path / "resume2.pdf"
        pdf1.write_bytes(b"content a")
        pdf2.write_bytes(b"content b")
        assert _hash_pdf(pdf1) != _hash_pdf(pdf2)


class TestHiringAgentAdapter:
    def test_falls_back_when_disabled(self):
        config = HiringAgentConfig(enabled=False)
        adapter = HiringAgentAdapter(config)
        result = adapter.get_structured_resume()
        assert result == HEMANG_RESUME_FALLBACK

    def test_falls_back_when_no_pdf(self, tmp_path):
        config = HiringAgentConfig(
            enabled=True,
            resume_path=str(tmp_path / "nonexistent.pdf"),
        )
        adapter = HiringAgentAdapter(config)
        result = adapter.get_structured_resume()
        assert result == HEMANG_RESUME_FALLBACK

    @patch("tracker.matching.hiring_agent.subprocess.run")
    def test_returns_fallback_on_subprocess_failure(self, mock_run, tmp_path):
        pdf = tmp_path / "resume.pdf"
        pdf.write_text("test")
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        config = HiringAgentConfig(
            enabled=True,
            resume_path=str(pdf),
            python_path="/usr/bin/python3",
            repo_path=str(tmp_path),
            cache_dir=str(cache_dir),
            rerun_on_resume_change=True,
        )

        mock_run.side_effect = subprocess.CalledProcessError(1, "score.py")

        adapter = HiringAgentAdapter(config)
        result = adapter.get_structured_resume()
        assert result == HEMANG_RESUME_FALLBACK

    @patch("tracker.matching.hiring_agent.subprocess.run")
    def test_parses_successful_agent_output(self, mock_run, tmp_path):
        pdf = tmp_path / "resume.pdf"
        pdf.write_text("test")

        repo_cache = tmp_path / "cache"
        repo_cache.mkdir()
        cache_file = repo_cache / "resumecache_resume.json"
        with open(cache_file, "w") as f:
            json.dump(make_sample_cache(), f)

        our_cache = tmp_path / "our_cache"
        our_cache.mkdir()

        config = HiringAgentConfig(
            enabled=True,
            resume_path=str(pdf),
            python_path="/usr/bin/python3",
            repo_path=str(tmp_path),
            cache_dir=str(our_cache),
            rerun_on_resume_change=True,
        )

        mock_run.return_value = subprocess.CompletedProcess(
            args=["score.py", str(pdf)],
            returncode=0,
            stdout="",
            stderr="",
        )

        adapter = HiringAgentAdapter(config)
        result = adapter.get_structured_resume()
        assert result is not None
        assert result.name == "Hemang Varshney"
        assert "Python" in result.skills

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Optional

from tracker.config import HiringAgentConfig
from tracker.logger import get_logger
from tracker.matching.resume_fallback import HEMANG_RESUME_FALLBACK
from tracker.models import StructuredResume

logger = get_logger()


def _hash_pdf(pdf_path: Path) -> str:
    h = hashlib.sha256()
    with open(pdf_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _parse_cache_json(data: dict) -> StructuredResume:
    basics = data.get("basics") or {}
    raw_skills = data.get("skills") or []
    raw_work = data.get("work") or []
    raw_education = data.get("education") or []
    raw_projects = data.get("projects") or []
    raw_certificates = data.get("certificates") or []

    skills = []
    for s in raw_skills:
        if isinstance(s, dict):
            name = s.get("name")
            if name:
                skills.append(name)
            keywords = s.get("keywords")
            if isinstance(keywords, list):
                skills.extend(k for k in keywords if isinstance(k, str))

    work = []
    for w in raw_work:
        if isinstance(w, dict):
            name = w.get("name") or ""
            position = w.get("position") or ""
            summary = w.get("summary") or ""
            parts = [p for p in (name, position, summary) if p]
            if parts:
                work.append(" — ".join(parts))

    education = []
    for e in raw_education:
        if isinstance(e, dict):
            institution = e.get("institution") or ""
            area = e.get("area") or ""
            study_type = e.get("studyType") or ""
            parts = [p for p in (study_type, area, institution) if p]
            if parts:
                education.append(", ".join(parts))

    projects = []
    for p in raw_projects:
        if isinstance(p, dict):
            name = p.get("name") or ""
            desc = p.get("description") or ""
            techs = p.get("technologies") or []
            if isinstance(techs, list):
                tech_str = ", ".join(str(t) for t in techs if t)
            else:
                tech_str = ""
            parts = [p for p in (name, desc, tech_str) if p]
            if parts:
                projects.append(" — ".join(parts))

    certificates = []
    for c in raw_certificates:
            if isinstance(c, dict):
                name = c.get("name") or ""
                issuer = c.get("issuer") or ""
                parts = [p for p in (name, issuer) if p]
                if parts:
                    certificates.append(" — ".join(parts))

    return StructuredResume(
        name=basics.get("name") or "Unknown",
        skills=list(set(skills)),
        education=education,
        work=work,
        projects=projects,
        certifications=certificates,
    )


def _find_cache_file(cache_dir: Path, pdf_hash: str) -> Optional[Path]:
    if not cache_dir.exists():
        return None
    for f in cache_dir.iterdir():
        if f.is_file() and f.name.startswith(f"resumecache_{pdf_hash}"):
            return f
    return None


class HiringAgentAdapter:
    def __init__(self, config: HiringAgentConfig) -> None:
        self._config = config
        self._cached_resume: Optional[StructuredResume] = None
        self._last_pdf_hash: Optional[str] = None

    def get_structured_resume(self) -> Optional[StructuredResume]:
        if not self._config.enabled:
            logger.info("Hiring agent disabled; using fallback resume")
            return HEMANG_RESUME_FALLBACK

        resume_path = Path(self._config.resume_path).resolve()
        if not resume_path.exists():
            logger.warning(
                "Resume PDF not found at %s; using fallback resume",
                resume_path,
            )
            return HEMANG_RESUME_FALLBACK

        pdf_hash = _hash_pdf(resume_path)
        repo_path = Path(self._config.repo_path).resolve()
        agent_cache_dir = repo_path / "cache"
        our_cache_dir = Path(self._config.cache_dir).resolve()
        our_cache_dir.mkdir(parents=True, exist_ok=True)

        if pdf_hash == self._last_pdf_hash and self._cached_resume:
            return self._cached_resume

        cache_file = _find_cache_file(our_cache_dir, pdf_hash)
        if cache_file and not self._config.rerun_on_resume_change:
            try:
                with open(cache_file, "r") as f:
                    parsed = _parse_cache_json(json.load(f))
                self._cached_resume = parsed
                self._last_pdf_hash = pdf_hash
                logger.info("Loaded cached resume from %s", cache_file)
                return parsed
            except Exception as e:
                logger.warning("Failed to read cached resume: %s", e)

        try:
            python_path = Path(self._config.python_path).absolute()
            if not python_path.exists():
                logger.warning(
                    "Python path %s not found; using fallback resume",
                    python_path,
                )
                return HEMANG_RESUME_FALLBACK

            model_map = {
                "gemini": "gemini-2.0-flash",
                "ollama": "gemma3:4b",
            }
            llm_model = model_map.get(self._config.llm_backend, "gemini-2.0-flash")
            logger.info("Running hiring-agent score.py on %s (model=%s)", resume_path, llm_model)
            result = subprocess.run(
                [str(python_path), "score.py", str(resume_path)],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                timeout=120,
                env={
                    **os.environ,
                    "DEVELOPMENT_MODE": "True",
                    "DEFAULT_MODEL": llm_model,
                },
            )

            if result.returncode != 0:
                logger.warning(
                    "Hiring agent exited with code %d: %s",
                    result.returncode,
                    result.stderr[:500],
                )
                return HEMANG_RESUME_FALLBACK

            cache_hit = _find_cache_file(agent_cache_dir, pdf_hash)
            if cache_hit is None:
                files_before = set(agent_cache_dir.iterdir()) if agent_cache_dir.exists() else set()
                files_after = set(agent_cache_dir.iterdir()) if agent_cache_dir.exists() else set()
                new_files = files_after - files_before
                if new_files:
                    cache_hit = max(new_files, key=lambda f: f.stat().st_mtime)

            if cache_hit is None:
                logger.warning(
                    "Hiring agent did not produce cache file; using fallback resume"
                )
                return HEMANG_RESUME_FALLBACK

            try:
                with open(cache_hit, "r") as f:
                    parsed = _parse_cache_json(json.load(f))
            except Exception as e:
                logger.warning("Failed to parse agent cache: %s", e)
                return HEMANG_RESUME_FALLBACK

            dest = our_cache_dir / f"resumecache_{pdf_hash}.json"
            try:
                import shutil
                shutil.copy2(cache_hit, dest)
            except Exception:
                pass

            self._cached_resume = parsed
            self._last_pdf_hash = pdf_hash
            logger.info(
                "Successfully parsed resume for %s (%d skills)",
                parsed.name,
                len(parsed.skills),
            )
            return parsed

        except subprocess.TimeoutExpired:
            logger.warning("Hiring agent timed out after 120s; using fallback resume")
            return HEMANG_RESUME_FALLBACK
        except FileNotFoundError as e:
            logger.warning("Hiring agent binary not found: %s; using fallback resume", e)
            return HEMANG_RESUME_FALLBACK
        except Exception as e:
            logger.warning(
                "Hiring agent adapter failed: %s; using fallback resume",
                e,
                exc_info=True,
            )
            return HEMANG_RESUME_FALLBACK

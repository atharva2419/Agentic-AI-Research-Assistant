"""Write a session to disk: data/sessions/<id>.json (full state) and data/reports/<id>.md.

Used by the CLI at the end of a run and by the web server whenever a session finishes, so
reports survive a server restart. (Phase 7 adds a database; these files stay as readable exports.)
"""

from pathlib import Path

from app.models import ResearchSession
from app.report_render import report_to_markdown


def export_session(session: ResearchSession, data_dir: Path) -> tuple[Path, Path]:
    sessions_dir = data_dir / "sessions"
    reports_dir = data_dir / "reports"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    session_path = sessions_dir / f"{session.id}.json"
    report_path = reports_dir / f"{session.id}.md"
    session_path.write_text(session.model_dump_json(indent=2), encoding="utf-8")
    report_path.write_text(report_to_markdown(session), encoding="utf-8")
    return session_path, report_path

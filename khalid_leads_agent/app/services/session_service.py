"""Working session of the owner – resumable after the agent is closed."""
from __future__ import annotations

from app.db import Database
from app.models import LeadSession
from app.repositories.lead_repo import SessionRepository
from app.services.settings_service import SettingsService
from app.utils.timeutils import fmt_local, utcnow


class SessionService:
    def __init__(self, db: Database, settings: SettingsService) -> None:
        self.db = db
        self.settings = settings
        self.resume_decided = False  # per process: ask "resume?" once after start

    @property
    def owner(self) -> str:
        return self.settings.get().agent_owner

    def active(self) -> LeadSession | None:
        with self.db.session() as s:
            return SessionRepository(s).active(self.owner)

    def ensure(self) -> LeadSession:
        with self.db.session() as s:
            repo = SessionRepository(s)
            return repo.active(self.owner) or repo.create(self.owner)

    def status(self) -> dict:
        sess = self.active()
        has_progress = bool(sess and (sess.completed_fingerprints or sess.skipped_fingerprints or sess.current_fingerprint))
        return {
            "needs_prompt": bool(has_progress and not self.resume_decided),
            "session": self.to_dict(sess) if sess else None,
        }

    def start(self, resume: bool) -> LeadSession:
        self.resume_decided = True
        with self.db.session() as s:
            repo = SessionRepository(s)
            if resume:
                sess = repo.active(self.owner)
                if sess:
                    return sess
            repo.close_all(self.owner)
            return repo.create(self.owner)

    def _mutate(self, fn) -> LeadSession:
        with self.db.session() as s:
            repo = SessionRepository(s)
            sess = repo.active(self.owner) or repo.create(self.owner)
            fn(sess)
            sess.updated_at = utcnow()
            return sess

    def set_current(self, fingerprint: str | None, sheet_row: int | None) -> LeadSession:
        def fn(sess: LeadSession) -> None:
            sess.current_fingerprint, sess.current_sheet_row = fingerprint, sheet_row
        return self._mutate(fn)

    def mark_completed(self, fingerprint: str) -> LeadSession:
        def fn(sess: LeadSession) -> None:
            if fingerprint not in sess.completed_fingerprints:
                sess.completed_fingerprints = [*sess.completed_fingerprints, fingerprint]
            if sess.current_fingerprint == fingerprint:
                sess.current_fingerprint, sess.current_sheet_row = None, None
        return self._mutate(fn)

    def mark_skipped(self, fingerprint: str) -> LeadSession:
        def fn(sess: LeadSession) -> None:
            if fingerprint not in sess.skipped_fingerprints:
                sess.skipped_fingerprints = [*sess.skipped_fingerprints, fingerprint]
            if sess.current_fingerprint == fingerprint:
                sess.current_fingerprint, sess.current_sheet_row = None, None
        return self._mutate(fn)

    def unskip(self, fingerprint: str) -> LeadSession:
        def fn(sess: LeadSession) -> None:
            sess.skipped_fingerprints = [f for f in sess.skipped_fingerprints if f != fingerprint]
        return self._mutate(fn)

    def add_error(self, fingerprint: str | None, message: str) -> None:
        def fn(sess: LeadSession) -> None:
            sess.errors = [*sess.errors[-49:], {"fingerprint": fingerprint, "message": message,
                                                "at": utcnow().isoformat()}]
        self._mutate(fn)

    @staticmethod
    def to_dict(sess: LeadSession) -> dict:
        return {
            "id": sess.id, "owner": sess.owner, "status": sess.status,
            "started_at": fmt_local(sess.created_at), "updated_at": fmt_local(sess.updated_at),
            "current_fingerprint": sess.current_fingerprint, "current_sheet_row": sess.current_sheet_row,
            "completed_count": len(sess.completed_fingerprints or []),
            "skipped_count": len(sess.skipped_fingerprints or []),
            "errors_count": len(sess.errors or []),
            "completed": list(sess.completed_fingerprints or []),
            "skipped": list(sess.skipped_fingerprints or []),
        }

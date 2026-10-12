"""Files (an image or a PDF) attached to WhatsApp templates.

A ``wa.me`` link can only carry text, so the file is sent this way: when WhatsApp opens, the agent puts
the file on the Windows clipboard (like «Copy» in File Explorer) and the user presses Ctrl+V inside the
chat, then Send. From the phone (remote access) there is no shared clipboard: the page offers the file
to download/share instead.

Files live in ``data/attachments/<random>.<ext>``; only these names are ever served or copied.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

from app.errors import AgentError

log = logging.getLogger(__name__)

MAX_BYTES = 16 * 1024 * 1024  # WhatsApp's limit for photos
KINDS = {".jpg": "image", ".jpeg": "image", ".png": "image", ".webp": "image", ".pdf": "pdf"}
MEDIA_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
               ".pdf": "application/pdf"}
_ID = re.compile(r"^[0-9a-f]{32}\.(jpg|jpeg|png|webp|pdf)$")

# The path comes in through an environment variable, never inside the command text.
# A picture goes on the clipboard as an image (WhatsApp pastes it like a screenshot); a PDF as a file
# (like «Copy» in File Explorer).
_CLIP_PS = (
    "Add-Type -AssemblyName System.Windows.Forms, System.Drawing;"
    "if ($env:KLA_CLIP_KIND -eq 'image') {"
    " $img = [System.Drawing.Image]::FromFile($env:KLA_CLIP_FILE);"
    " [System.Windows.Forms.Clipboard]::SetImage($img); $img.Dispose()"
    "} else {"
    " $f = New-Object System.Collections.Specialized.StringCollection;"
    " [void]$f.Add($env:KLA_CLIP_FILE);"
    " [System.Windows.Forms.Clipboard]::SetFileDropList($f)"
    "}"
)


def _sniff(content: bytes) -> str | None:
    """The real type from the first bytes (the extension alone is not trusted)."""
    if content.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return ".webp"
    if content.startswith(b"%PDF-"):
        return ".pdf"
    return None


def safe_name(name: str, ext: str) -> str:
    base = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", Path(name or "").stem).strip()[:80] or "مرفق"
    return base + (".jpg" if ext == ".jpeg" else ext)


class AttachmentService:
    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def save(self, filename: str, content: bytes) -> dict:
        if not content:
            raise AgentError("FILE_EMPTY", "الملف فارغ.")
        if len(content) > MAX_BYTES:
            raise AgentError("FILE_TOO_LARGE", "الملف أكبر من 16 ميجابايت (حد واتساب للصور). صغّر حجمه وحاول مرة أخرى.")
        ext = _sniff(content)
        if ext is None:
            raise AgentError("FILE_TYPE", "نوع الملف غير مدعوم. المسموح: صورة (JPG أو PNG أو WEBP) أو ملف PDF.")
        self.folder.mkdir(parents=True, exist_ok=True)
        file_id = f"{uuid.uuid4().hex}{ext}"
        (self.folder / file_id).write_bytes(content)
        return self.describe(file_id, safe_name(filename, ext))

    def path(self, file_id: str) -> Path | None:
        if not _ID.match(file_id or ""):
            return None
        p = self.folder / file_id
        return p if p.is_file() else None

    def describe(self, file_id: str, name: str = "") -> dict | None:
        p = self.path(file_id)
        if p is None:
            return None
        ext = p.suffix.lower()
        return {"id": file_id, "name": name or safe_name("", ext), "kind": KINDS[ext], "size": p.stat().st_size,
                "url": f"/api/attachments/{file_id}"}

    def copy_to_clipboard(self, file_id: str) -> bool:
        """Put the file on the Windows clipboard so Ctrl+V in WhatsApp attaches it. False when not possible."""
        p = self.path(file_id)
        if p is None or sys.platform != "win32":
            return False
        try:
            subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-STA", "-ExecutionPolicy", "Bypass", "-Command", _CLIP_PS],
                env={**os.environ, "KLA_CLIP_FILE": str(p.resolve()), "KLA_CLIP_KIND": KINDS[p.suffix.lower()]},
                check=True, timeout=15,
                capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return True
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("Could not copy %s to the clipboard: %s", p.name, exc)
            return False

    def cleanup(self, keep: set[str], min_age_seconds: int = 86400) -> int:
        """Delete files no template uses any more (only older ones: a fresh upload may not be saved yet)."""
        if not self.folder.is_dir():
            return 0
        removed = 0
        now = time.time()
        for p in self.folder.iterdir():
            if _ID.match(p.name) and p.name not in keep and now - p.stat().st_mtime >= min_age_seconds:
                try:
                    p.unlink()
                    removed += 1
                except OSError:
                    pass
        return removed

from datetime import datetime, timezone
from pathlib import Path
from .daum_post import extract_article_payload
from ..models import AcquisitionResult

class SnapshotDaumPostAcquirer:
    def __init__(self, root: Path, mapping: dict):
        self.root = Path(root)
        self.mapping = mapping

    def acquire(self, *, post_id: int, source_id: str, url: str):
        now = datetime.now(timezone.utc).isoformat()
        rel = self.mapping.get(url)
        if rel is None:
            return AcquisitionResult(source_id,post_id,url,"FAILED",None,url,
                error_code="SNAPSHOT_NOT_FOUND",error="No acquisition snapshot mapping",acquired_at=now)
        html = (self.root/rel).read_text(encoding="utf-8")
        text, images, posters = extract_article_payload(html, url)
        if len(text) < 40:
            return AcquisitionResult(source_id,post_id,url,"PARTIAL",200,url,body_text=text,body_chars=len(text),
                images=images,poster_candidates=posters,content_type="text/html",
                error_code="BODY_UNAVAILABLE",error="Snapshot contains no meaningful article body",acquired_at=now)
        status = "FULL" if images else "BODY_ONLY"
        return AcquisitionResult(source_id,post_id,url,status,200,url,body_text=text,body_chars=len(text),
            images=images,poster_candidates=posters,content_type="text/html",acquired_at=now)

from datetime import datetime, timezone
from pathlib import Path
from .generic import extract_html
from ..models import AcquisitionResult

class SnapshotGenericPostAcquirer:
    def __init__(self, root: Path, mapping: dict):
        self.root=Path(root); self.mapping=mapping
    def acquire(self, *, post_id, source_id, url):
        now=datetime.now(timezone.utc).isoformat()
        rel=self.mapping.get(url)
        if not rel:
            return AcquisitionResult(source_id,post_id,url,"FAILED",None,url,error_code="SNAPSHOT_NOT_FOUND",error="No mapping",acquired_at=now)
        h=(self.root/rel).read_text(encoding="utf-8")
        text,imgs,posters=extract_html(h,url)
        if len(text)<40:
            return AcquisitionResult(source_id,post_id,url,"PARTIAL",200,url,body_text=text,body_chars=len(text),
                images=imgs,poster_candidates=posters,content_type="text/html",error_code="BODY_UNAVAILABLE",
                error="Snapshot contains no meaningful body",acquired_at=now)
        st="FULL" if imgs else "BODY_ONLY"
        return AcquisitionResult(source_id,post_id,url,st,200,url,body_text=text,body_chars=len(text),
            images=imgs,poster_candidates=posters,content_type="text/html",acquired_at=now)

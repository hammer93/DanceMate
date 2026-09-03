import json
from pathlib import Path
from ..collectors.base import RawPostRecord

class SnapshotCrossSourceProvider:
    name="SNAPSHOT"
    def __init__(self, path: Path):
        self.data=json.loads(Path(path).read_text(encoding="utf-8"))
    def search(self, query: str):
        rows=[]
        q=(query or "").lower()
        for item in self.data["documents"]:
            hay=" ".join([item.get("title",""),item.get("contents",""),item.get("cafename",""),item.get("blogname","")]).lower()
            tokens=[t for t in q.replace("@"," ").split() if len(t)>=2]
            if not tokens or any(t in hay for t in tokens):
                rows.append(RawPostRecord(
                    source_id=item["source_id"],
                    platform=item["platform"],
                    source_url=item["url"],
                    title=item["title"],
                    body=item.get("contents",""),
                    published_at=item.get("datetime"),
                    cafe_name=item.get("cafename") or item.get("blogname"),
                    discovery_query=query,
                    acquisition_quality=item.get("acquisition_quality","METADATA_ONLY"),
                    raw_json=json.dumps(item,ensure_ascii=False)
                ))
        return rows

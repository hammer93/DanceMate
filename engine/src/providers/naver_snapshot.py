from pathlib import Path
from ..collectors.naver import load_naver_snapshot

class NaverApiSnapshotProvider:
    name="NAVER_API_SNAPSHOT"
    def __init__(self, root: Path):
        self.root=Path(root)
    def search(self, query: str):
        rows=[]
        rows += load_naver_snapshot(self.root/"naver-blog-sample.json",kind="blog",source_id="SRC-N-001",query=query)
        rows += load_naver_snapshot(self.root/"naver-cafe-sample.json",kind="cafe",source_id="SRC-N-002",query=query)
        # Keep snapshot deterministic but still approximate query relevance.
        qtokens=[t.lower() for t in query.replace("@"," ").split() if len(t)>=2]
        out=[]
        for r in rows:
            hay=(r.title+" "+r.body).lower()
            if not qtokens or any(t in hay for t in qtokens):
                out.append(r)
        return out

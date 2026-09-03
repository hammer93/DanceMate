from ..collectors.naver import NaverSearchCollector

class NaverCrossSourceProvider:
    name="NAVER_SEARCH"

    def __init__(self, collector=None, *, kinds=("blog","cafe"), display=100, sort="date"):
        self.collector=collector or NaverSearchCollector()
        self.kinds=tuple(kinds)
        self.display=display
        self.sort=sort

    def search(self, query: str):
        rows=[]
        for kind in self.kinds:
            source_id="SRC-N-001" if kind=="blog" else "SRC-N-002"
            rows.extend(self.collector.search(
                query,kind=kind,display=self.display,start=1,sort=self.sort,source_id=source_id
            ))
        return rows

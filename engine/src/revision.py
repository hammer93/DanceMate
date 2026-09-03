import re
from dataclasses import dataclass

CANCEL_PATTERNS=[
    re.compile(r"(취소|휴무|쉽니다|운영\s*중단|행사\s*없(?:음|습니다)|cancel(?:led|ed)?)",re.I),
]
UPDATE_PATTERNS=[
    re.compile(r"(시간\s*변경|시작\s*시간\s*변경|장소\s*변경|변경\s*공지|오늘만)",re.I),
]

@dataclass
class RevisionDecision:
    role:str
    reasons:list

def classify_revision(text):
    t=text or ""
    if any(p.search(t) for p in CANCEL_PATTERNS):
        return RevisionDecision("CANCELLATION",["CANCELLATION_KEYWORD"])
    if any(p.search(t) for p in UPDATE_PATTERNS):
        return RevisionDecision("UPDATE",["UPDATE_KEYWORD"])
    return RevisionDecision("ORIGINAL",["NO_REVISION_KEYWORD"])

def extract_change_hints(text):
    t=text or ""
    out={}
    m=re.search(r"(?:시작\s*시간\s*변경|시간\s*변경|오늘만).*?(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*시?",t,re.S)
    if m:
        h=int(m.group("h")); mi=int(m.group("m") or 0)
        if 0<=h<=23 and 0<=mi<=59:
            out["start_time"]=f"{h:02d}:{mi:02d}"
    m=re.search(r"(?:장소\s*변경|변경\s*장소)\s*[:：-]?\s*([^\n,]{2,40})",t)
    if m:
        out["venue"]=m.group(1).strip()
    return out

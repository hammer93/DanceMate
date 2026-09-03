import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

STOP_WORDS = {"밀롱가","milonga","tango","탱고","the","at","@"}

def _clean(s):
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"[^\w가-힣]+"," ",s)
    return " ".join(s.split())

def normalize_event_name(name):
    s=_clean(name)

    # Event titles frequently include the occurrence date. It must not become
    # part of EventSeries/EventInstance identity because equivalent sources
    # may express the same date as "8/22", "8월 22일", or omit it entirely.
    s=re.sub(r"\b20\d{2}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일\b"," ",s)
    s=re.sub(r"\b\d{2}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일\b"," ",s)
    s=re.sub(r"\b\d{1,2}\s*월\s*\d{1,2}\s*일\b"," ",s)
    s=re.sub(r"\b\d{1,2}\s*[./-]\s*\d{1,2}\b"," ",s)
    # _clean() turns "8/22" into "8 22", so remove that normalized form too.
    s=re.sub(r"^\s*\d{1,2}\s+\d{1,2}\s+"," ",s)
    s=" ".join(s.split())

    phrase_aliases={
        "더 피스타 밀롱가":"pista",
        "더 피스타":"pista",
        "the pista milonga":"pista",
        "pista milonga":"pista",
    }
    if s in phrase_aliases:
        return phrase_aliases[s]
    toks=[t for t in s.split() if t not in STOP_WORDS]
    out=" ".join(toks)
    token_aliases={"피스타":"pista"}
    return " ".join(token_aliases.get(t,t) for t in out.split())

def normalize_venue(venue):
    s=_clean(venue)
    aliases={
        "라 벤따나":"la ventana",
        "라벤따나":"la ventana",
        "라 벤타나":"la ventana",
        "라벤타나":"la ventana",
        "더 피스타":"pista",
        "the pista":"pista",
        "피스타":"pista",
        "pista":"pista",
    }
    return aliases.get(s,s)

def similarity(a,b):
    a=normalize_event_name(a); b=normalize_event_name(b)
    if not a or not b: return 0.0
    return SequenceMatcher(None,a,b).ratio()

def build_identity_key(name, event_date, venue):
    nn=normalize_event_name(name)
    nv=normalize_venue(venue)
    return f"{event_date or 'UNKNOWN'}|{nv or 'UNKNOWN'}|{nn or 'UNKNOWN'}"

@dataclass
class MatchDecision:
    match: bool
    review_required: bool
    score: float
    reasons: list

def same_event_instance(a, b):
    reasons=[]
    if a.get("event_date") and b.get("event_date"):
        if a["event_date"] != b["event_date"]:
            return MatchDecision(False,False,0.0,["DATE_MISMATCH"])
        reasons.append("DATE_MATCH")
    else:
        return MatchDecision(False,True,0.2,["DATE_MISSING"])

    av=normalize_venue(a.get("venue"))
    bv=normalize_venue(b.get("venue"))
    if av and bv:
        if av != bv:
            return MatchDecision(False,False,0.0,["VENUE_MISMATCH"])
        reasons.append("VENUE_MATCH")
    else:
        reasons.append("VENUE_MISSING")

    s=similarity(a.get("name",""),b.get("name",""))
    if s >= 0.72:
        reasons.append("NAME_SIMILAR")
        return MatchDecision(True,False,0.9,reasons)
    if av and bv and s >= 0.45:
        reasons.append("NAME_WEAK_BUT_VENUE_DATE_STRONG")
        return MatchDecision(True,False,0.8,reasons)
    return MatchDecision(False,True,0.5,reasons+["NAME_AMBIGUOUS"])

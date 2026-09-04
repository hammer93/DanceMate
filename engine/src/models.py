from dataclasses import dataclass, field, asdict
from typing import List, Optional, Any

@dataclass
class Evidence:
    field: str
    value: Any
    raw_text: str
    evidence_type: str = "TEXT"
    source_role: str = "SECONDARY"
    inference: Optional[str] = None
    # Which text segment this came from, when extract_single() split the post
    # into more than one (a multi-program post) - None for a single segment,
    # meaning "the whole post", exactly as every Evidence behaved before
    # v0.81.2. See extractor.py's _context_segments().
    context_id: Optional[str] = None

@dataclass
class EventCandidate:
    name: str
    event_type: str
    date: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    end_day_offset: int = 0
    fee: Optional[int] = None
    venue: Optional[str] = None
    dj: Optional[str] = None
    evidences: List[Evidence] = field(default_factory=list)
    status: str = "POSSIBLE"
    core_complete: bool = False

    def to_dict(self):
        return asdict(self)

@dataclass
class AcquisitionResult:
    source_id: str
    post_id: int
    source_url: str
    status: str
    http_status: Optional[int] = None
    final_url: Optional[str] = None
    body_text: Optional[str] = None
    body_chars: int = 0
    images: List[str] = field(default_factory=list)
    poster_candidates: List[str] = field(default_factory=list)
    content_type: Optional[str] = None
    error_code: Optional[str] = None
    error: Optional[str] = None
    acquired_at: Optional[str] = None

    def to_dict(self):
        return asdict(self)

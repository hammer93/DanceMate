from dataclasses import dataclass, asdict
from typing import Optional

@dataclass
class RawPostRecord:
    source_id: str
    platform: str
    source_url: str
    title: str
    body: str
    published_at: Optional[str] = None
    cafe_name: Optional[str] = None
    thumbnail_url: Optional[str] = None
    discovery_query: Optional[str] = None
    acquisition_quality: str = "METADATA_ONLY"
    raw_json: Optional[str] = None
    # v0.80: admissible when the collector's own page/section structure
    # already guarantees the event type (e.g. a site's dedicated milonga
    # listing page never carries a class-only or performance-only post) -
    # see classifier.classify()'s own known_event_type parameter. None
    # (the default) leaves classification exactly as it was for every
    # existing caller.
    known_event_type: Optional[str] = None

    def to_dict(self):
        return asdict(self)

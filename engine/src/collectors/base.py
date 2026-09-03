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

    def to_dict(self):
        return asdict(self)

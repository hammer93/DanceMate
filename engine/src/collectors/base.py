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
    # Only a Source explicitly configured as a dated class board opts into
    # class-instance Event creation. Ordinary lesson adverts stay non-events.
    class_event_opt_in: bool = False
    # v0.86.9: extra normalized words the tango-social detection should
    # recognise, handed in by the runtime from its Settings terminology.
    # None (the default) leaves classification exactly as it was.
    event_terms: Optional[tuple] = None
    # v0.96.10: what the SOURCE itself files this post as, when the source
    # keeps a category of its own per item and the runtime can read it -
    # "EVENT" (a night: a party, a 출빠 listing, a 정모) or "CLASS" (a
    # course). Not known_event_type: that answers *which kind of night*,
    # this answers *whether the source calls it a night at all*, and only
    # a source that labels each post itself may set it. None (the default)
    # leaves classification exactly as it was for every other collector.
    source_category: Optional[str] = None
    # v0.96.35: the weak counterpart to known_event_type above. That one
    # answers "which kind of night is this", and outranks every keyword
    # reading. This one answers only "is there a night here at all", for a
    # source that publishes a dated, clocked occurrence carrying no event
    # type of any kind to read (TangoNOW's share pages state `@type: Event`
    # and no category, no genre). classify() therefore asks it last, after
    # every refusal and after the post's own words have found nothing, so it
    # can promote an unreadable brand name to a night but can never weaken
    # or overrule a classification. None (the default) leaves classification
    # exactly as it was for every existing collector.
    source_night_fallback: Optional[str] = None
    # v0.96.41: a structured tango calendar's own judgement that this record is
    # a festival - a dated record with no clock of its own whose name announces
    # a festival, marathon or tango week (runtime/festival_evidence.py). Only
    # "FESTIVAL" is read. ``event_period`` is the record's own structured
    # {"start": ISO date, "end": ISO date (only when the record states it)}.
    # None (the default) leaves classification exactly as it was.
    source_event_format: Optional[str] = None
    event_period: Optional[dict] = None

    def to_dict(self):
        return asdict(self)

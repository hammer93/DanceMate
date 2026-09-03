import re
from dataclasses import dataclass

MEDIA_CLASSES={"EVENT_POSTER","VENUE_IMAGE","LOGO","UNKNOWN"}

EVENT_HINTS=re.compile(r"(poster|milonga|event|schedule|flyer|2026|8[_-]?27|thu|thursday)",re.I)
LOGO_HINTS=re.compile(r"(logo|mark|symbol|ocho|onada|andante)",re.I)
VENUE_HINTS=re.compile(r"(venue|interior|room|space|hall)",re.I)

@dataclass
class MediaDecision:
    media_class:str
    reason:str
    score:float

def classify_media(*, url:str, surrounding_text:str="", image_width=None, image_height=None):
    u=(url or "").lower()
    t=(surrounding_text or "").lower()

    if "logo" in u or re.search(r"\blogo\b",t):
        return MediaDecision("LOGO","explicit_logo_hint",0.98)

    if EVENT_HINTS.search(u) or EVENT_HINTS.search(t):
        # If it is a tiny square icon despite event words, stay conservative.
        if image_width and image_height and image_width<=256 and image_height<=256 and abs(image_width-image_height)<=32:
            return MediaDecision("UNKNOWN","small_square_asset",0.45)
        return MediaDecision("EVENT_POSTER","event_or_schedule_hint",0.85)

    if VENUE_HINTS.search(u) or VENUE_HINTS.search(t):
        return MediaDecision("VENUE_IMAGE","venue_hint",0.75)

    if LOGO_HINTS.search(u) and image_width and image_height and image_width<=512 and image_height<=512:
        return MediaDecision("LOGO","brand_name_small_asset",0.70)

    return MediaDecision("UNKNOWN","insufficient_evidence",0.20)

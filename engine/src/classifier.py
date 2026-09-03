def classify(title: str, body: str, known_event_type=None) -> str:
    if known_event_type:
        # Source Registry / known series context is admissible evidence for type classification.
        return known_event_type
    text = f"{title} {body}".lower()
    class_words = ["lesson", "강습", "개강", "모집", "안무반", "공연반", "초중급", "전문가반"]
    milonga_words = ["milonga", "밀롱가", "쁘롱", "쁘락"]
    if any(w in text for w in class_words):
        if "open class" in text and any(w in text for w in milonga_words):
            return "MILONGA_WITH_CLASS"
        return "CLASS"
    if any(w in text for w in milonga_words):
        return "MILONGA"
    return "OTHER"

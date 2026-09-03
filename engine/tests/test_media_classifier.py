from src.media_classifier import classify_media

def test_event_poster():
    r=classify_media(url="https://x/sueno_schedule_2026-08-27.jpg",surrounding_text="Thursday 20:00~24:00 Milonga")
    assert r.media_class=="EVENT_POSTER"

def test_logo():
    assert classify_media(url="https://x/ocho_logo.png").media_class=="LOGO"

def test_venue_image():
    assert classify_media(url="https://x/andante_space.jpg",surrounding_text="venue interior").media_class=="VENUE_IMAGE"

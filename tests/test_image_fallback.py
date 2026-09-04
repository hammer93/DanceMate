"""Image OCR orchestration and cache (v0.81.3).

Runs against the real staging PostgreSQL (the `pg` fixture rolls back), with
`image_fetch.fetch_image` and `ocr.run_ocr` monkeypatched so these tests
exercise the caching/recording logic itself, not a real network fetch or a
real tesseract run.
"""

from __future__ import annotations

import pytest

from runtime import image_fallback, image_fetch, ocr


def _source_item(pg, unique, suffix="1"):
    from runtime import sources

    source = sources.create_source(
        pg, source_key=f"SRC-IMG-{unique}-{suffix}", name=f"image probe {unique}",
        platform="WEB", source_role="COMMUNITY",
        url=f"https://example.invalid/{unique}/{suffix}", enabled=False)
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO source_items (source_id, external_id, url, title, content_hash) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING source_item_id",
            (source["source_id"], f"ext-{unique}-{suffix}",
             f"https://example.invalid/{unique}/{suffix}/post", "image probe",
             f"hash-{unique}-{suffix}"))
        return cur.fetchone()[0]


def _ok_fetch(data=b"\xff\xd8\xff fake jpeg bytes"):
    return image_fetch.ImageFetchResult(url="x", status="FETCHED",
                                        content_type="image/jpeg", data=data)


def _ok_ocr(text="THE PISTA MILONGA 9월 5일 19:30", confidence=88.0):
    return ocr.OcrResult(status=ocr.STATUS_SUCCESS, text=text, confidence=confidence,
                         width=800, height=600)


def test_a_successful_fetch_and_ocr_yields_usable_text(pg, unique, monkeypatch):
    from runtime.config import load_settings

    item_id = _source_item(pg, unique)
    monkeypatch.setattr(image_fetch, "fetch_image", lambda url, **kw: _ok_fetch())
    monkeypatch.setattr(ocr, "run_ocr", lambda data, **kw: _ok_ocr())

    result = image_fallback.gather_image_texts(
        pg, load_settings(), source_item_id=item_id,
        candidate_urls=["https://cdn.example.test/poster.jpg"],
    )
    assert result == [("https://cdn.example.test/poster.jpg",
                        "THE PISTA MILONGA 9월 5일 19:30")]


def test_a_fetch_failure_yields_no_text_but_is_recorded(pg, unique, monkeypatch):
    from runtime.config import load_settings

    item_id = _source_item(pg, unique)
    monkeypatch.setattr(image_fetch, "fetch_image",
                        lambda url, **kw: image_fetch.ImageFetchResult(
                            url=url, status="FETCH_FAILED", error="timed out"))

    result = image_fallback.gather_image_texts(
        pg, load_settings(), source_item_id=item_id,
        candidate_urls=["https://cdn.example.test/poster.jpg"],
    )
    assert result == []
    rows = image_fallback.images_for_review(pg, item_id)
    assert rows[0]["fetch_status"] == "FETCH_FAILED"


def test_low_confidence_ocr_yields_no_text_but_is_recorded(pg, unique, monkeypatch):
    from runtime.config import load_settings

    item_id = _source_item(pg, unique)
    monkeypatch.setattr(image_fetch, "fetch_image", lambda url, **kw: _ok_fetch())
    monkeypatch.setattr(ocr, "run_ocr", lambda data, **kw: ocr.OcrResult(
        status=ocr.STATUS_LOW_CONFIDENCE, text="garbled", confidence=5.0))

    result = image_fallback.gather_image_texts(
        pg, load_settings(), source_item_id=item_id,
        candidate_urls=["https://cdn.example.test/poster.jpg"],
    )
    assert result == []
    rows = image_fallback.images_for_review(pg, item_id)
    assert rows[0]["ocr_status"] == ocr.STATUS_LOW_CONFIDENCE


def test_one_failing_image_does_not_stop_the_others(pg, unique, monkeypatch):
    from runtime.config import load_settings

    item_id = _source_item(pg, unique)
    calls = {"n": 0}

    def flaky_fetch(url, **kw):
        calls["n"] += 1
        if "bad" in url:
            return image_fetch.ImageFetchResult(url=url, status="FETCH_FAILED")
        return _ok_fetch()

    monkeypatch.setattr(image_fetch, "fetch_image", flaky_fetch)
    monkeypatch.setattr(ocr, "run_ocr", lambda data, **kw: _ok_ocr())

    result = image_fallback.gather_image_texts(
        pg, load_settings(), source_item_id=item_id,
        candidate_urls=["https://cdn.example.test/bad.jpg",
                        "https://cdn.example.test/good.jpg"],
    )
    assert len(result) == 1
    assert result[0][0] == "https://cdn.example.test/good.jpg"


def test_a_second_call_for_the_same_url_does_not_refetch(pg, unique, monkeypatch):
    from runtime.config import load_settings

    item_id = _source_item(pg, unique)
    calls = {"fetch": 0, "ocr": 0}
    monkeypatch.setattr(image_fetch, "fetch_image",
                        lambda url, **kw: calls.__setitem__("fetch", calls["fetch"] + 1) or _ok_fetch())
    monkeypatch.setattr(ocr, "run_ocr",
                        lambda data, **kw: calls.__setitem__("ocr", calls["ocr"] + 1) or _ok_ocr())

    settings = load_settings()
    urls = ["https://cdn.example.test/poster.jpg"]
    first = image_fallback.gather_image_texts(pg, settings, source_item_id=item_id, candidate_urls=urls)
    second = image_fallback.gather_image_texts(pg, settings, source_item_id=item_id, candidate_urls=urls)

    assert first == second
    assert calls["fetch"] == 1
    assert calls["ocr"] == 1


def test_the_same_image_bytes_reused_across_items_are_ocrd_once(pg, unique, monkeypatch):
    """The same poster, reposted to a second source item, is recognised by
    content hash and its OCR text is reused - not re-run through tesseract."""
    from runtime.config import load_settings

    item_a = _source_item(pg, unique, "a")
    item_b = _source_item(pg, unique, "b")
    calls = {"ocr": 0}
    monkeypatch.setattr(image_fetch, "fetch_image", lambda url, **kw: _ok_fetch(data=b"\xff\xd8\xff same bytes"))
    monkeypatch.setattr(ocr, "run_ocr",
                        lambda data, **kw: calls.__setitem__("ocr", calls["ocr"] + 1) or _ok_ocr())

    settings = load_settings()
    a = image_fallback.gather_image_texts(pg, settings, source_item_id=item_a,
                                          candidate_urls=["https://cdn.example.test/a.jpg"])
    b = image_fallback.gather_image_texts(pg, settings, source_item_id=item_b,
                                          candidate_urls=["https://cdn.example.test/b.jpg"])

    assert a and b
    assert a[0][1] == b[0][1]  # same OCR text
    assert calls["ocr"] == 1  # tesseract ran only once


def test_mark_used_as_fallback_updates_only_the_named_urls(pg, unique, monkeypatch):
    from runtime.config import load_settings

    item_id = _source_item(pg, unique)
    monkeypatch.setattr(image_fetch, "fetch_image", lambda url, **kw: _ok_fetch())
    monkeypatch.setattr(ocr, "run_ocr", lambda data, **kw: _ok_ocr())

    image_fallback.gather_image_texts(
        pg, load_settings(), source_item_id=item_id,
        candidate_urls=["https://cdn.example.test/used.jpg",
                        "https://cdn.example.test/unused.jpg"],
    )
    image_fallback.mark_used_as_fallback(pg, item_id, {"https://cdn.example.test/used.jpg"})

    rows = {r["image_url"]: r for r in image_fallback.images_for_review(pg, item_id)}
    assert rows["https://cdn.example.test/used.jpg"]["used_as_fallback"] is True
    assert rows["https://cdn.example.test/unused.jpg"]["used_as_fallback"] is False


def test_pii_in_ocr_text_is_redacted_before_storage(pg, unique, monkeypatch):
    from runtime.config import load_settings

    item_id = _source_item(pg, unique)
    monkeypatch.setattr(image_fetch, "fetch_image", lambda url, **kw: _ok_fetch())
    monkeypatch.setattr(ocr, "run_ocr", lambda data, **kw: ocr.OcrResult(
        status=ocr.STATUS_SUCCESS, text="문의 010-1234-5678", confidence=90.0))

    result = image_fallback.gather_image_texts(
        pg, load_settings(), source_item_id=item_id,
        candidate_urls=["https://cdn.example.test/poster.jpg"],
    )
    assert "010-1234-5678" not in result[0][1]
    assert "[전화번호]" in result[0][1]


def test_no_candidate_urls_returns_empty_without_touching_the_network(pg, unique, monkeypatch):
    from runtime.config import load_settings

    item_id = _source_item(pg, unique)
    monkeypatch.setattr(image_fetch, "fetch_image",
                        lambda url, **kw: (_ for _ in ()).throw(AssertionError("must not fetch")))
    result = image_fallback.gather_image_texts(
        pg, load_settings(), source_item_id=item_id, candidate_urls=[],
    )
    assert result == []

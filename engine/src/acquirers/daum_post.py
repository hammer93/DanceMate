import html
import re
import urllib.request
import urllib.error
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin
from ..models import AcquisitionResult

SPACE_RE = re.compile(r"\s+")
LIKELY_ASSET_RE = re.compile(r"\.(?:jpe?g|png|webp|gif)(?:$|[?#])", re.I)
POSTER_HINT_RE = re.compile(r"(poster|attach|cafeattach|image|img|photo)", re.I)

class AcquisitionError(RuntimeError):
    pass

class _ArticleHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text_parts = []
        self.images = []
        self._skip_depth = 0
        self._skip_tags = {"script","style","noscript","svg"}
    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in self._skip_tags:
            self._skip_depth += 1
        if tag == "img":
            ad = dict(attrs)
            for key in ("data-original-src","data-src","src"):
                u = ad.get(key)
                if u:
                    self.images.append(u)
                    break
        if tag in {"br","p","div","li","tr","h1","h2","h3","article","section"} and self._skip_depth == 0:
            self.text_parts.append("\n")
    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self._skip_tags and self._skip_depth:
            self._skip_depth -= 1
        if tag in {"p","div","li","tr","article","section"} and self._skip_depth == 0:
            self.text_parts.append("\n")
    def handle_data(self, data):
        if self._skip_depth == 0 and data.strip():
            self.text_parts.append(data)

def _normalize_text(parts):
    text = "".join(parts)
    lines = []
    for line in text.splitlines():
        clean = SPACE_RE.sub(" ", html.unescape(line)).strip()
        if clean:
            lines.append(clean)
    return "\n".join(lines)

def extract_article_payload(raw_html: str, base_url: str):
    parser = _ArticleHTMLParser()
    parser.feed(raw_html)
    text = _normalize_text(parser.text_parts)
    images = []
    seen = set()
    for u in parser.images:
        absu = urljoin(base_url, html.unescape(u))
        if absu in seen:
            continue
        seen.add(absu)
        images.append(absu)
    poster_candidates = [u for u in images if LIKELY_ASSET_RE.search(u) or POSTER_HINT_RE.search(u)]
    return text, images, poster_candidates

class DaumPostAcquirer:
    def __init__(self, timeout_seconds=15, user_agent=None):
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent or "Mozilla/5.0 (compatible; DanceMate-InformationEngine-PoC/0.3; +local-validation)"

    def acquire(self, *, post_id: int, source_id: str, url: str) -> AcquisitionResult:
        now = datetime.now(timezone.utc).isoformat()
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.5",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                status = getattr(resp, "status", 200)
                ctype = resp.headers.get("Content-Type","")
                body = resp.read()
                charset = resp.headers.get_content_charset() or "utf-8"
                try:
                    text_html = body.decode(charset, errors="replace")
                except LookupError:
                    text_html = body.decode("utf-8", errors="replace")
                final_url = resp.geturl()
                if "html" not in ctype.lower() and "<html" not in text_html[:500].lower():
                    return AcquisitionResult(source_id,post_id,url,"FAILED",status,final_url,
                        content_type=ctype,error_code="UNSUPPORTED_CONTENT_TYPE",
                        error=f"Unsupported Content-Type: {ctype}",acquired_at=now)
                text, images, posters = extract_article_payload(text_html, final_url)
                # A page shell/login wall with almost no text is not FULL acquisition.
                if len(text) < 40:
                    return AcquisitionResult(source_id,post_id,url,"PARTIAL",status,final_url,
                        body_text=text,body_chars=len(text),images=images,poster_candidates=posters,
                        content_type=ctype,error_code="BODY_UNAVAILABLE",
                        error="HTML fetched but meaningful article body was not found",acquired_at=now)
                quality = "FULL" if images else "BODY_ONLY"
                return AcquisitionResult(source_id,post_id,url,quality,status,final_url,
                    body_text=text,body_chars=len(text),images=images,poster_candidates=posters,
                    content_type=ctype,acquired_at=now)
        except urllib.error.HTTPError as e:
            code = "ACCESS_DENIED" if e.code in (401,403) else "HTTP_ERROR"
            return AcquisitionResult(source_id,post_id,url,"FAILED",e.code,url,error_code=code,error=str(e),acquired_at=now)
        except urllib.error.URLError as e:
            return AcquisitionResult(source_id,post_id,url,"FAILED",None,url,error_code="NETWORK_ERROR",error=str(e.reason),acquired_at=now)
        except Exception as e:
            return AcquisitionResult(source_id,post_id,url,"FAILED",None,url,error_code="ACQUISITION_ERROR",error=str(e),acquired_at=now)

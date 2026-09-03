import html
import re
import urllib.request
import urllib.error
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin
from ..models import AcquisitionResult

SPACE_RE = re.compile(r"\s+")
ASSET_RE = re.compile(r"\.(?:jpe?g|png|webp|gif)(?:$|[?#])", re.I)
POSTER_HINT_RE = re.compile(r"(poster|attach|image|img|photo|cafeattach|postfiles|blogfiles)", re.I)

class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text=[]
        self.images=[]
        self._skip=0
        self._skip_tags={"script","style","noscript","svg"}
    def handle_starttag(self,tag,attrs):
        tag=tag.lower()
        if tag in self._skip_tags:
            self._skip+=1
        ad=dict(attrs)
        if tag=="img":
            for k in ("data-lazy-src","data-original-src","data-src","src"):
                if ad.get(k):
                    self.images.append(ad[k]); break
        if self._skip==0 and tag in {"br","p","div","li","article","section","h1","h2","h3"}:
            self.text.append("\n")
    def handle_endtag(self,tag):
        if tag.lower() in self._skip_tags and self._skip:
            self._skip-=1
        if self._skip==0 and tag.lower() in {"p","div","li","article","section"}:
            self.text.append("\n")
    def handle_data(self,data):
        if self._skip==0 and data.strip():
            self.text.append(data)

def extract_html(raw_html, base_url):
    p=_Parser(); p.feed(raw_html)
    lines=[]
    for line in "".join(p.text).splitlines():
        c=SPACE_RE.sub(" ",html.unescape(line)).strip()
        if c: lines.append(c)
    text="\n".join(lines)
    images=[]; seen=set()
    for u in p.images:
        u=urljoin(base_url,html.unescape(u))
        if u not in seen:
            seen.add(u); images.append(u)
    posters=[u for u in images if ASSET_RE.search(u) or POSTER_HINT_RE.search(u)]
    return text,images,posters

class GenericPostAcquirer:
    def __init__(self, timeout_seconds=15, user_agent=None):
        self.timeout_seconds=timeout_seconds
        self.user_agent=user_agent or "Mozilla/5.0 (compatible; DanceMate-InformationEngine-PoC/0.6)"

    def acquire(self, *, post_id, source_id, url):
        now=datetime.now(timezone.utc).isoformat()
        req=urllib.request.Request(url,headers={
            "User-Agent":self.user_agent,
            "Accept":"text/html,application/xhtml+xml",
            "Accept-Language":"ko-KR,ko;q=0.9,en;q=0.5",
        },method="GET")
        try:
            with urllib.request.urlopen(req,timeout=self.timeout_seconds) as resp:
                status=getattr(resp,"status",200)
                ctype=resp.headers.get("Content-Type","")
                raw=resp.read()
                enc=resp.headers.get_content_charset() or "utf-8"
                try: h=raw.decode(enc,errors="replace")
                except LookupError: h=raw.decode("utf-8",errors="replace")
                final=resp.geturl()
                text,imgs,posters=extract_html(h,final)
                if len(text)<40:
                    return AcquisitionResult(source_id,post_id,url,"PARTIAL",status,final,body_text=text,body_chars=len(text),
                        images=imgs,poster_candidates=posters,content_type=ctype,error_code="BODY_UNAVAILABLE",
                        error="HTML fetched but meaningful article body was not found",acquired_at=now)
                st="FULL" if imgs else "BODY_ONLY"
                return AcquisitionResult(source_id,post_id,url,st,status,final,body_text=text,body_chars=len(text),
                    images=imgs,poster_candidates=posters,content_type=ctype,acquired_at=now)
        except urllib.error.HTTPError as e:
            code="ACCESS_DENIED" if e.code in (401,403) else "HTTP_ERROR"
            return AcquisitionResult(source_id,post_id,url,"FAILED",e.code,url,error_code=code,error=str(e),acquired_at=now)
        except urllib.error.URLError as e:
            return AcquisitionResult(source_id,post_id,url,"FAILED",None,url,error_code="NETWORK_ERROR",error=str(e.reason),acquired_at=now)
        except Exception as e:
            return AcquisitionResult(source_id,post_id,url,"FAILED",None,url,error_code="ACQUISITION_ERROR",error=str(e),acquired_at=now)

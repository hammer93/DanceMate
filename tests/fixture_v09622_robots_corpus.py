"""Real robots.txt files from the hosts DanceMate actually fetches.

Captured 2026-09-28 with this project's own `acquisition.USER_AGENT`, from the
board. Verbatim apart from trimming trailing blank lines; these are public
files. Each one is here because it exercises a different part of RFC 9309, and
because a regression in how it reads would change what this project may fetch.
"""

# cafe.daum.net - the shape this release exists for, met in production.
# Four specific `Allow:` rules above one broad `Disallow:`. DanceMate's Daum
# board collector walks `/_c21_/bbs_list?grpid=...`, which the longest match
# allows; anything else under `/_c21_/` is disallowed. The current parser
# happens to agree here only because the Allow lines are written first.
CAFE_DAUM = """\
User-agent: *
Allow: /_c21_/home
Allow: /_c21_/bbs_search_read
Allow: /_c21_/bbs_list
Allow: /_c21_/bbs_read

Disallow: /_c21_/
"""

# cafe.naver.com - genuinely closed to everyone. 401 stored items sit behind
# this, and they must stay blocked.
CAFE_NAVER = """\
# BOT ACCESS FOR THE PURPOSES OF AI TRAINING AND RETRIEVAL-AUGMENTED GENERATION (RAG) IS STRICTLY PROHIBITED.
User-agent: *
Disallow: /

User-agent: Googlebot
Disallow: /

User-agent: GPTBot
Disallow: /
"""

# danceinfo.net - `Allow: /` first, then a Sitemap, then two Disallow rules.
# The release's original hypothesis said the Sitemap line would swallow them.
DANCEINFO = """\
User-agent: *
Allow: /

# 관리자 페이지/기능 제외
Disallow: /admin_w/

# 관리자 API 제외
Disallow: /api/

# 사이트맵 위치 (운영 도메인에 맞게 필요 시 수정)
Sitemap: https://danceinfo.net/sitemap.xml
"""

# seoullindyfest.com - two Sitemap lines BEFORE the only group, a WordPress
# default. v0.96.21's source lives here and must keep working.
SEOUL_LINDYFEST = """\
# If you are regularly crawling WordPress.com sites, please use our firehose to receive real-time push updates instead.
# Please see https://developer.wordpress.com/docs/firehose/ for more details.

Sitemap: https://seoullindyfest.com/sitemap.xml
Sitemap: https://seoullindyfest.com/news-sitemap.xml

User-agent: *
Disallow: /wp-admin/
Allow: /wp-admin/admin-ajax.php
Disallow: /wp-login.php
Disallow: /activate/
Disallow: /cgi-bin/
Disallow: /next/
Disallow: /public.api/
"""

# tangocalendar.kr - open, with a Sitemap.
TANGOCALENDAR = """\
User-agent: *
Allow: /

Sitemap: https://tangocalendar.kr/sitemap.xml
"""

# socialdancelive.com - the one source whose decision this release changes.
# Two named bots share one group; the `*` group is `Allow: /` followed by
# nineteen Disallow rules, six of them using `*` inside the pattern.
SOCIALDANCELIVE = """\
User-Agent: GPTBot
User-Agent: Amazonbot
Disallow: /

User-Agent: *
Allow: /
Disallow: /home-public-cache
Disallow: /admin
Disallow: /auth
Disallow: /create
Disallow: /my
Disallow: /?location=
Disallow: /?*&location=
Disallow: /?genre=
Disallow: /?*&genre=
Disallow: /?category=
Disallow: /?*&category=
Disallow: /?date=
Disallow: /?*&date=
Disallow: /?sort=
Disallow: /?*&sort=
Disallow: /?type=
Disallow: /?*&type=

Sitemap: https://www.socialdancelive.com/sitemap.xml
Sitemap: https://www.socialdancelive.com/rss.xml
"""

# latindancekorea.com - not a registered source, and the site this release was
# sent to investigate. Its Disallow rules sit after a Sitemap line, which is
# what made the Sitemap hypothesis look plausible. They are hidden by the
# `Allow: /` above them instead.
LATINDANCEKOREA = """\
# https://www.robotstxt.org/robotstxt.html
User-agent: *
Allow: /

# Sitemap
Sitemap: https://latindancekorea.com/sitemap.xml

# Disallow admin and API routes from indexing
Disallow: /admin/
Disallow: /api/
Disallow: /organizer/
"""

# miltang.com - a group whose rules are followed by a long comment block, and
# which deliberately leaves its query parameters unblocked.
MILTANG = """\
User-agent: *

# 관리자
Disallow: /admin
Disallow: /admin/

# 로그인이 필요한 화면
Disallow: /more
Disallow: /requests
Disallow: /nickname
Disallow: /auth/
"""

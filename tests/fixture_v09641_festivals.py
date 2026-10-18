"""v0.96.41 fixtures: the live festival records, as captured 2026-10-19.

Captured read-only from the two public structured calendars through the
collectors' own fetchers (robots.txt and Crawl-delay honoured):

* ``TANGONOW_DATE_ONLY`` - every share page in https://ktnow.kr/sitemap-events.xml
  whose JSON-LD ``startDate`` carries no clock: 12 of the 40 pages listed. The
  JSON-LD is kept exactly as served (no page states an ``endDate``).
* ``MILTANG_NOTICES`` - ten of Miltang's 16 ``/notices`` detail pages: the
  JSON-LD, and the DATE / TIME / PLACE / ORG rows and the description the
  detail template renders, which is what ``parse_detail()`` reads.

Phone numbers are replaced by ``[전화번호]``. Nothing here is an invented
answer: the expectations the tests assert are what each page itself states.
"""

TANGONOW_DATE_ONLY = {'https://ktnow.kr/e/0SB1vX8MbJ7I6l1dePUx': {'@context': 'https://schema.org',
                                             '@type': 'Event',
                                             'name': 'BUSAN TANGO FESTIVAL',
                                             'url': 'https://ktnow.kr/e/0SB1vX8MbJ7I6l1dePUx',
                                             'description': '2026-10-21(wed) · 데땅고',
                                             'startDate': '2026-10-21',
                                             'eventStatus': 'https://schema.org/EventScheduled',
                                             'eventAttendanceMode': 'https://schema.org/OfflineEventAttendanceMode',
                                             'inLanguage': 'ko-KR',
                                             'image': ['https://ktnow.kr/og-image-v2.png'],
                                             'location': {'@type': 'Place', 'name': '데땅고'},
                                             'organizer': {'@type': 'Organization',
                                                           'name': 'Lucas Carrizo, Maria Paula '
                                                                   'Tejeda'}},
 'https://ktnow.kr/e/t4yTitjlTQ6G8ZcDHJz1': {'@context': 'https://schema.org',
                                             '@type': 'Event',
                                             'name': '제1회 마산 가고파 국화 탱고 마라톤',
                                             'url': 'https://ktnow.kr/e/t4yTitjlTQ6G8ZcDHJz1',
                                             'description': '2026-10-31(토) · Tango club Mi Noche',
                                             'startDate': '2026-10-31',
                                             'eventStatus': 'https://schema.org/EventScheduled',
                                             'eventAttendanceMode': 'https://schema.org/OfflineEventAttendanceMode',
                                             'inLanguage': 'ko-KR',
                                             'image': ['https://ktnow.kr/og-image-v2.png'],
                                             'location': {'@type': 'Place',
                                                          'name': 'Tango club Mi Noche'},
                                             'organizer': {'@type': 'Organization',
                                                           'name': 'ISABELLE & SENS'}},
 'https://ktnow.kr/e/occ_56870bca896e75165664bb6cb3638a678fd9fcec270c82439bdd24f1dac26238': {'@context': 'https://schema.org',
                                                                                             '@type': 'Event',
                                                                                             'name': 'The '
                                                                                                     'Best '
                                                                                                     'Tangueros '
                                                                                                     'Seoul',
                                                                                             'url': 'https://ktnow.kr/e/occ_56870bca896e75165664bb6cb3638a678fd9fcec270c82439bdd24f1dac26238',
                                                                                             'description': '2026-11-08(일) '
                                                                                                            '· '
                                                                                                            '13:00 '
                                                                                                            '· '
                                                                                                            '프리스타일 '
                                                                                                            '(합정동 '
                                                                                                            '386-37 '
                                                                                                            'B1 '
                                                                                                            '지하철 '
                                                                                                            '2, '
                                                                                                            '6호선 '
                                                                                                            '합정역) '
                                                                                                            '· '
                                                                                                            'DJ '
                                                                                                            '헨리',
                                                                                             'startDate': '2026-11-08',
                                                                                             'eventStatus': 'https://schema.org/EventScheduled',
                                                                                             'eventAttendanceMode': 'https://schema.org/OfflineEventAttendanceMode',
                                                                                             'inLanguage': 'ko-KR',
                                                                                             'image': ['https://firebasestorage.googleapis.com/v0/b/ktangoguide.firebasestorage.app/o/inbox%2Fsharecard_event_occ_56870bca896e75165664bb6cb3638a678fd9fc_card_659c3a79096b480a.jpg?alt=media&token=6c509547-4cbb-4792-bb63-e380b1882f5b'],
                                                                                             'location': {'@type': 'Place',
                                                                                                          'name': '프리스타일 '
                                                                                                                  '(합정동 '
                                                                                                                  '386-37 '
                                                                                                                  'B1 '
                                                                                                                  '지하철 '
                                                                                                                  '2, '
                                                                                                                  '6호선 '
                                                                                                                  '합정역)'},
                                                                                             'organizer': {'@type': 'Organization',
                                                                                                           'name': '빅토르 '
                                                                                                                   '(Victor '
                                                                                                                   'Won)'}},
 'https://ktnow.kr/e/occ_37117f467f3fcb37cc803917b6755fc7327b29c4630d91deb64ef18d08b75d8a': {'@context': 'https://schema.org',
                                                                                             '@type': 'Event',
                                                                                             'name': 'SEOUL '
                                                                                                     'TANGO '
                                                                                                     'WEEK '
                                                                                                     '2026',
                                                                                             'url': 'https://ktnow.kr/e/occ_37117f467f3fcb37cc803917b6755fc7327b29c4630d91deb64ef18d08b75d8a',
                                                                                             'description': '2026-11-12(목) '
                                                                                                            '· '
                                                                                                            'ELTANGO '
                                                                                                            '· '
                                                                                                            'Seoul '
                                                                                                            'Tango '
                                                                                                            'Academy',
                                                                                             'startDate': '2026-11-12',
                                                                                             'eventStatus': 'https://schema.org/EventScheduled',
                                                                                             'eventAttendanceMode': 'https://schema.org/OfflineEventAttendanceMode',
                                                                                             'inLanguage': 'ko-KR',
                                                                                             'image': ['https://firebasestorage.googleapis.com/v0/b/ktangoguide.firebasestorage.app/o/inbox%2Fsharecard_event_occ_37117f467f3fcb37cc803917b6755fc7327b29_card_6367f6e23dd54356.jpg?alt=media&token=fd8cff99-bd46-46dc-907f-4bf079d91d2a'],
                                                                                             'location': {'@type': 'Place',
                                                                                                          'name': 'ELTANGO '
                                                                                                                  '· '
                                                                                                                  'Seoul '
                                                                                                                  'Tango '
                                                                                                                  'Academy'},
                                                                                             'organizer': {'@type': 'Organization',
                                                                                                           'name': 'ELTANGO '
                                                                                                                   '· '
                                                                                                                   'Seoul '
                                                                                                                   'Tango '
                                                                                                                   'Academy'}},
 'https://ktnow.kr/e/97mawjl8UM2nXG2U3jFt': {'@context': 'https://schema.org',
                                             '@type': 'Event',
                                             'name': 'KOREA SPECIAL TANGO WEEK 2026',
                                             'url': 'https://ktnow.kr/e/97mawjl8UM2nXG2U3jFt',
                                             'description': '2026-11-18(wed) · 포항 posTango · 서울 '
                                                            'OCHO',
                                             'startDate': '2026-11-18',
                                             'eventStatus': 'https://schema.org/EventScheduled',
                                             'eventAttendanceMode': 'https://schema.org/OfflineEventAttendanceMode',
                                             'inLanguage': 'ko-KR',
                                             'image': ['https://ktnow.kr/og-image-v2.png'],
                                             'location': {'@type': 'Place',
                                                          'name': '포항 posTango · 서울 OCHO'},
                                             'organizer': {'@type': 'Organization',
                                                           'name': '부산탱고협동조합'}},
 'https://ktnow.kr/e/aSkYZREohvQi2RKzEXEA': {'@context': 'https://schema.org',
                                             '@type': 'Event',
                                             'name': 'RoyBeDDong in BUSAN',
                                             'url': 'https://ktnow.kr/e/aSkYZREohvQi2RKzEXEA',
                                             'description': '2026-12-18(fri)',
                                             'startDate': '2026-12-18',
                                             'eventStatus': 'https://schema.org/EventScheduled',
                                             'eventAttendanceMode': 'https://schema.org/OfflineEventAttendanceMode',
                                             'inLanguage': 'ko-KR',
                                             'image': ['https://ktnow.kr/og-image-v2.png']},
 'https://ktnow.kr/e/occ_396245c9ece9c1016279ec094a479c03427879fe470271acc83c3772ee2d9708': {'@context': 'https://schema.org',
                                                                                             '@type': 'Event',
                                                                                             'name': 'posTango '
                                                                                                     '| '
                                                                                                     'CRAB '
                                                                                                     'MILONGA '
                                                                                                     '- '
                                                                                                     'POSTANGO '
                                                                                                     '22nd '
                                                                                                     'ANNIVERSARY',
                                                                                             'url': 'https://ktnow.kr/e/occ_396245c9ece9c1016279ec094a479c03427879fe470271acc83c3772ee2d9708',
                                                                                             'description': '2027-02-26(금) '
                                                                                                            '· '
                                                                                                            'posTango',
                                                                                             'startDate': '2027-02-26',
                                                                                             'eventStatus': 'https://schema.org/EventScheduled',
                                                                                             'eventAttendanceMode': 'https://schema.org/OfflineEventAttendanceMode',
                                                                                             'inLanguage': 'ko-KR',
                                                                                             'image': ['https://firebasestorage.googleapis.com/v0/b/ktangoguide.firebasestorage.app/o/inbox%2Fsharecard_brand_1769585914005_brand-v3-1pepn69.jpg?alt=media&token=725dcab8-d62f-4bb6-9665-f8eb8a88e600'],
                                                                                             'location': {'@type': 'Place',
                                                                                                          'name': 'posTango'}},
 'https://ktnow.kr/e/occ_a60eb994195011aa917a9d0f9e1af84f3c04a79b712c7af99299d0729def5963': {'@context': 'https://schema.org',
                                                                                             '@type': 'Event',
                                                                                             'name': '서라벌 '
                                                                                                     '밀롱게로스',
                                                                                             'url': 'https://ktnow.kr/e/occ_a60eb994195011aa917a9d0f9e1af84f3c04a79b712c7af99299d0729def5963',
                                                                                             'description': '2027-04-09(금) '
                                                                                                            '· '
                                                                                                            'GYEONGJU '
                                                                                                            'KOREA',
                                                                                             'startDate': '2027-04-09',
                                                                                             'eventStatus': 'https://schema.org/EventScheduled',
                                                                                             'eventAttendanceMode': 'https://schema.org/OfflineEventAttendanceMode',
                                                                                             'inLanguage': 'ko-KR',
                                                                                             'image': ['https://firebasestorage.googleapis.com/v0/b/ktangoguide.firebasestorage.app/o/inbox%2Fsharecard_event_occ_a60eb994195011aa917a9d0f9e1af84f3c04a7_card_c135890f3d7f462c.jpg?alt=media&token=e9e9c7bd-4fdc-4837-971c-3a4725eddfe5'],
                                                                                             'location': {'@type': 'Place',
                                                                                                          'name': 'GYEONGJU '
                                                                                                                  'KOREA'},
                                                                                             'organizer': {'@type': 'Organization',
                                                                                                           'name': 'Encuentro '
                                                                                                                   'de '
                                                                                                                   'Tango'}},
 'https://ktnow.kr/e/f1PaEgVCTKCGEEY54cXE': {'@context': 'https://schema.org',
                                             '@type': 'Event',
                                             'name': '엘 불린 땅고 | 2027 서울 땅고 페스티발',
                                             'url': 'https://ktnow.kr/e/f1PaEgVCTKCGEEY54cXE',
                                             'description': '2027-04-29(목)',
                                             'startDate': '2027-04-29',
                                             'eventStatus': 'https://schema.org/EventScheduled',
                                             'eventAttendanceMode': 'https://schema.org/OfflineEventAttendanceMode',
                                             'inLanguage': 'ko-KR',
                                             'image': ['https://firebasestorage.googleapis.com/v0/b/ktangoguide.firebasestorage.app/o/inbox%2Fsharecard_brand_1771[전화번호]_brand-v3-1t0mqus.jpg?alt=media&token=d9df7aad-b021-4adb-bbd4-85d01ee3d08c'],
                                             'organizer': {'@type': 'Organization',
                                                           'name': '헝얏 & 화이'}},
 'https://ktnow.kr/e/occ_70e6278173ac2da96b0b76c23342d7747b2093af498b23c6594bedd8b6b81523': {'@context': 'https://schema.org',
                                                                                             '@type': 'Event',
                                                                                             'name': '2027 '
                                                                                                     'GUNSAN '
                                                                                                     'SUNSET '
                                                                                                     'TANGO '
                                                                                                     'MARATHON',
                                                                                             'url': 'https://ktnow.kr/e/occ_70e6278173ac2da96b0b76c23342d7747b2093af498b23c6594bedd8b6b81523',
                                                                                             'description': '2027-05-21(금) '
                                                                                                            '· '
                                                                                                            '군산',
                                                                                             'startDate': '2027-05-21',
                                                                                             'eventStatus': 'https://schema.org/EventScheduled',
                                                                                             'eventAttendanceMode': 'https://schema.org/OfflineEventAttendanceMode',
                                                                                             'inLanguage': 'ko-KR',
                                                                                             'image': ['https://firebasestorage.googleapis.com/v0/b/ktangoguide.firebasestorage.app/o/inbox%2Fsharecard_event_occ_70e6278173ac2da96b0b76c23342d7747b2093_card_efa74078e4824a73.jpg?alt=media&token=a7b9c459-575c-4d40-8af3-fa185b53e000'],
                                                                                             'location': {'@type': 'Place',
                                                                                                          'name': '군산'}},
 'https://ktnow.kr/e/occ_beb54ee75c4cf3fbe9c7ae3189d91fa73d95219bf2764c6d6d6d5198c3591625': {'@context': 'https://schema.org',
                                                                                             '@type': 'Event',
                                                                                             'name': 'Jeju '
                                                                                                     'Summ '
                                                                                                     'Milonga',
                                                                                             'url': 'https://ktnow.kr/e/occ_beb54ee75c4cf3fbe9c7ae3189d91fa73d95219bf2764c6d6d6d5198c3591625',
                                                                                             'description': '2027-08-27(금) '
                                                                                                            '· '
                                                                                                            'Jeju',
                                                                                             'startDate': '2027-08-27',
                                                                                             'eventStatus': 'https://schema.org/EventScheduled',
                                                                                             'eventAttendanceMode': 'https://schema.org/OfflineEventAttendanceMode',
                                                                                             'inLanguage': 'ko-KR',
                                                                                             'image': ['https://firebasestorage.googleapis.com/v0/b/ktangoguide.firebasestorage.app/o/inbox%2Fsharecard_event_occ_beb54ee75c4cf3fbe9c7ae3189d91fa73d9521_card_4ab6cc652d444226.jpg?alt=media&token=5ab0da75-f9d8-44c7-bf85-d34f8d93b1f4'],
                                                                                             'location': {'@type': 'Place',
                                                                                                          'name': 'Jeju'},
                                                                                             'organizer': {'@type': 'Organization',
                                                                                                           'name': 'Tango '
                                                                                                                   'O '
                                                                                                                   'Nada'}},
 'https://ktnow.kr/e/occ_059519e91def6d8b71d9321ef0dc1111085cb2792302488a74e9d996b9a81a04': {'@context': 'https://schema.org',
                                                                                             '@type': 'Event',
                                                                                             'name': 'Busan '
                                                                                                     'Tango '
                                                                                                     'Weekend '
                                                                                                     'El '
                                                                                                     'Mar',
                                                                                             'url': 'https://ktnow.kr/e/occ_059519e91def6d8b71d9321ef0dc1111085cb2792302488a74e9d996b9a81a04',
                                                                                             'description': '2027-09-02(목) '
                                                                                                            '· '
                                                                                                            'Busan',
                                                                                             'startDate': '2027-09-02',
                                                                                             'eventStatus': 'https://schema.org/EventScheduled',
                                                                                             'eventAttendanceMode': 'https://schema.org/OfflineEventAttendanceMode',
                                                                                             'inLanguage': 'ko-KR',
                                                                                             'image': ['https://firebasestorage.googleapis.com/v0/b/ktangoguide.firebasestorage.app/o/inbox%2Fsharecard_event_occ_059519e91def6d8b71d9321ef0dc1111085cb2_card_34b9a07c2b36495a.jpg?alt=media&token=96a5e773-9a20-477e-9978-286569a1625a'],
                                                                                             'location': {'@type': 'Place',
                                                                                                          'name': 'Busan'}}}

MILTANG_NOTICES = {'https://miltang.com/notices/12': {'ld': {'@context': 'https://schema.org',
                                           '@type': 'Event',
                                           'name': 'BUSAN TANGO FESTIVAL',
                                           'url': 'https://miltang.com/notices/12',
                                           'startDate': '2026-10-21',
                                           'endDate': '2026-10-29',
                                           'eventStatus': 'https://schema.org/EventScheduled',
                                           'eventAttendanceMode': 'https://schema.org/OfflineEventAttendanceMode',
                                           'description': 'DE TANGO 17th Anniversary',
                                           'image': ['https://miltang.com/storage/imports/ktnow_6a7731e893d5e6.71182084_cec21368299519ae.jpg'],
                                           'location': {'@type': 'Place',
                                                        'name': 'Detango 데땅고',
                                                        'address': {'@type': 'PostalAddress',
                                                                    'streetAddress': '부산광역시 부산진구 '
                                                                                     '서면로68번길 41',
                                                                    'addressCountry': 'KR'}}},
                                    'date_row': '2026. 10. 21(수) ~ 2026. 10. 29(목)',
                                    'time_row': None,
                                    'place_row': '<p class="font-bold">Detango 데땅고</p> <p '
                                                 'class="text-fg3 text-xs mt-0.5">부산광역시 부산진구 '
                                                 '서면로68번길 41</p> <button type="button" '
                                                 '@click="copy(\'addr\', \'부산광역시 부산진구 서면로68번길 '
                                                 '41\')" class="btn-pill btn-pill--secondary '
                                                 'text-[11px] px-3 py-1 mt-2 inline-flex '
                                                 'items-center gap-1"> <span class="ms-icon '
                                                 'text-[12px]">content_copy</span> <span '
                                                 'x-text="copied.addr ? \'복사됨\' : '
                                                 '\'주소복사\'"></span> </button>',
                                    'org_row': None,
                                    'description': 'DE TANGO 17th Anniversary'},
 'https://miltang.com/notices/14': {'ld': {'@context': 'https://schema.org',
                                           '@type': 'Event',
                                           'name': '제1회 마산 가고파 국화 탱고 마라톤',
                                           'url': 'https://miltang.com/notices/14',
                                           'startDate': '2026-10-31',
                                           'endDate': '2026-11-01',
                                           'eventStatus': 'https://schema.org/EventScheduled',
                                           'eventAttendanceMode': 'https://schema.org/OfflineEventAttendanceMode',
                                           'image': ['https://miltang.com/storage/imports/ktnow_6a7732f157c0a2.33314921_1ff6b7d26ebf651d.jpg'],
                                           'location': {'@type': 'Place',
                                                        'name': 'Tango club Mi Noche',
                                                        'address': {'@type': 'PostalAddress',
                                                                    'streetAddress': '경남 창원시 마산합포구 '
                                                                                     '가포로25 지하1층',
                                                                    'addressCountry': 'KR'}},
                                           'organizer': {'@type': 'Organization',
                                                         'name': 'ISABELLE & SENS'}},
                                    'date_row': '2026. 10. 31(토) ~ 2026. 11. 1(일)',
                                    'time_row': None,
                                    'place_row': '<p class="font-bold">Tango club Mi Noche</p> <p '
                                                 'class="text-fg3 text-xs mt-0.5">경남 창원시 마산합포구 '
                                                 '가포로25 지하1층</p> <button type="button" '
                                                 '@click="copy(\'addr\', \'경남 창원시 마산합포구 가포로25 '
                                                 '지하1층\')" class="btn-pill btn-pill--secondary '
                                                 'text-[11px] px-3 py-1 mt-2 inline-flex '
                                                 'items-center gap-1"> <span class="ms-icon '
                                                 'text-[12px]">content_copy</span> <span '
                                                 'x-text="copied.addr ? \'복사됨\' : '
                                                 '\'주소복사\'"></span> </button>',
                                    'org_row': 'ISABELLE &amp; SENS',
                                    'description': None},
 'https://miltang.com/notices/15': {'ld': {'@context': 'https://schema.org',
                                           '@type': 'Event',
                                           'name': '2026 Seoul Tango Week',
                                           'url': 'https://miltang.com/notices/15',
                                           'startDate': '2026-11-11',
                                           'endDate': '2026-11-16',
                                           'eventStatus': 'https://schema.org/EventScheduled',
                                           'eventAttendanceMode': 'https://schema.org/OfflineEventAttendanceMode',
                                           'description': '신청링크:https://docs.google.com/forms/d/e/1FAIpQLScDs8IBfU75Wg4nl7MvxyjL3HJ-mxQya25uWkiTNK7y1-',
                                           'image': ['https://miltang.com/storage/notices/hMGgOgeaeXrrukBKpX41OFnibCmzIH1kFqWrMx7C.jpg',
                                                     'https://miltang.com/storage/notices/wCe3F4VY1pgtHMICCBsnc75KuOWGqiUWzEjTWWq2.jpg'],
                                           'location': {'@type': 'Place',
                                                        'name': 'El Tango 엘땅고',
                                                        'address': {'@type': 'PostalAddress',
                                                                    'streetAddress': '서울 서초구 주흥길 '
                                                                                     '12 환희빌딩 2층',
                                                                    'addressCountry': 'KR'}}},
                                    'date_row': '2026. 11. 11(수) ~ 2026. 11. 16(월)',
                                    'time_row': '상세 정보 참고',
                                    'place_row': '<p class="font-bold">El Tango 엘땅고</p> <p '
                                                 'class="text-fg3 text-xs mt-0.5">서울 서초구 주흥길 12 '
                                                 '환희빌딩 2층</p> <button type="button" '
                                                 '@click="copy(\'addr\', \'서울 서초구 주흥길 12 환희빌딩 '
                                                 '2층\')" class="btn-pill btn-pill--secondary '
                                                 'text-[11px] px-3 py-1 mt-2 inline-flex '
                                                 'items-center gap-1"> <span class="ms-icon '
                                                 'text-[12px]">content_copy</span> <span '
                                                 'x-text="copied.addr ? \'복사됨\' : '
                                                 '\'주소복사\'"></span> </button>',
                                    'org_row': None,
                                    'description': '<p>신청링크:</p><p><br></p><p>https://docs.google.com/forms/d/e/1FAIpQLScDs8IBfU75Wg4nl7MvxyjL3HJ-mxQya25uWkiTNK7y1-</p>'},
 'https://miltang.com/notices/16': {'ld': {'@context': 'https://schema.org',
                                           '@type': 'Event',
                                           'name': 'Chicho Frumboli & Juana Sepulveda  Tango '
                                                   'Seminar & Show',
                                           'url': 'https://miltang.com/notices/16',
                                           'startDate': '2026-10-22',
                                           'endDate': '2026-10-25',
                                           'eventStatus': 'https://schema.org/EventScheduled',
                                           'eventAttendanceMode': 'https://schema.org/OfflineEventAttendanceMode',
                                           'description': '이시대의 진정한 탱고 아티스트, 우리의 위대한 탱고의 스승 Chicho '
                                                          'Frumboli & Juana Sepulveda 를 초청합니다. 역대급 '
                                                          '최고의 개런티, 컨택조차 쉽지않아서 그동안 초청…',
                                           'image': ['https://miltang.com/storage/notices/S18r9GRRw1iV3zxp4gk6pFJi7aR3I2PfbSscOWYK.webp'],
                                           'location': {'@type': 'Place',
                                                        'name': 'PISTA 피스타',
                                                        'address': {'@type': 'PostalAddress',
                                                                    'streetAddress': '서울 월드컵북로6길 '
                                                                                     '49 지하1층',
                                                                    'addressCountry': 'KR'}}},
                                    'date_row': '2026. 10. 22(목) ~ 2026. 10. 25(일)',
                                    'time_row': '상세 링크 참고',
                                    'place_row': '<p class="font-bold">PISTA 피스타</p> <p '
                                                 'class="text-fg3 text-xs mt-0.5">서울 월드컵북로6길 49 '
                                                 '지하1층</p> <button type="button" '
                                                 '@click="copy(\'addr\', \'서울 월드컵북로6길 49 지하1층\')" '
                                                 'class="btn-pill btn-pill--secondary text-[11px] '
                                                 'px-3 py-1 mt-2 inline-flex items-center gap-1"> '
                                                 '<span class="ms-icon '
                                                 'text-[12px]">content_copy</span> <span '
                                                 'x-text="copied.addr ? \'복사됨\' : '
                                                 '\'주소복사\'"></span> </button>',
                                    'org_row': None,
                                    'description': '<p><span style="background-color: rgb(255, '
                                                   '255, 255); color: rgb(31, 31, 31);">이시대의 진정한 '
                                                   '탱고 아티스트,&nbsp;우리의 위대한 탱고의 스승&nbsp;Chicho '
                                                   'Frumboli &amp; Juana Sepulveda 를 '
                                                   '초청합니다.&nbsp;역대급 최고의 개런티,&nbsp;컨택조차 '
                                                   '쉽지않아서&nbsp;그동안 초청이 어려웠으나, 드디어 2007년 초청에 이어 '
                                                   '20년만에 다시 한국으로의 초청이 '
                                                   '성사되었습니다.&nbsp;&nbsp;</span></p><p><br></p><p><br></p><p><span '
                                                   'style="background-color: rgb(255, 255, 255); '
                                                   'color: rgb(31, 31, 31);">&nbsp;&nbsp;마스터 '
                                                   '스스로&nbsp;"주제가 없는" 클래스에 대해 본인들이 설명을 다음과 같이 '
                                                   '합니다.&nbsp;"우리&nbsp;세미나 수업은 제목이 따로 없습니다. 참가자들이 '
                                                   '12시간의 수업에 모두 참여하는 것을 목표로 하며, 탱고와 관련된 다양한 주제를 '
                                                   '다룹니다".</span></p><p><br></p><p><br></p><p><span '
                                                   'style="background-color: rgb(255, 255, 255); '
                                                   'color: rgb(31, 31, 31);">&nbsp;&nbsp;이러한 "언타이틀 '
                                                   '클래스"에 대한 설명의 의미는,&nbsp;1~2개의 수업을 들어서 단편적으로 간만 '
                                                   '보는 것이 아니라, 12시간 짜리 세미나 전체를 통해,&nbsp;개념이 유기적으로 '
                                                   '연결되고 점진적으로 발전되는 형식으로 진행되기 때문에,&nbsp;12시간짜리 탱고 '
                                                   '세미나 전체를 수강함으로써, 이 시대의 위대한 탱고 아티스트들의 에센스를 제대로 '
                                                   '익히고,&nbsp;세미나 전체를 꿰뚫고 있는, 일관성있게 전달하고자 하는 마스터들의 '
                                                   '탱고 철학을 제대로 경험할 수 있다는 '
                                                   '의미입니다.&nbsp;</span></p><p><br></p><p><br></p><p><span '
                                                   'style="background-color: rgb(255, 255, 255); '
                                                   'color: rgb(31, 31, 31);">&nbsp;&nbsp;이 번 탱고 '
                                                   '세미나는 마스터입장에서 원할한 수업진행과 학생입장에서 제대로된 수업 이해를 위해 '
                                                   '풀팩키지 신청만 가능합니다.&nbsp;&nbsp;신청은 선착순으로&nbsp;20커플 '
                                                   '이하만 받습니다.&nbsp;조기 마감될 것이 예상되니 서둘러 '
                                                   '신청바랍니다.&nbsp;가능한 개인지도 기회도 한정되어 있으며, 단체 수업 전후에 '
                                                   '가능하며, 사전 신청 받습니다.&nbsp;하단에 개인지도 '
                                                   '항목에&nbsp;체크하시고, 별도로 개별 연락주시기 '
                                                   '바랍니다.&nbsp;&nbsp;</span></p><p><br></p><p><br></p><p><span '
                                                   'style="background-color: rgb(255, 255, 255); '
                                                   'color: rgb(31, 31, 31);">&nbsp;&nbsp;국내 신청자는 '
                                                   '입금 마감일 자정전에&nbsp;입금완료 해야하고,&nbsp;국외신청자는 현장 '
                                                   '납부이지만 10월 15일까지 신청시 이용한 이메일주소를 이용하여 참가 확인 이메일을 '
                                                   '보내야만 합니다. 만약 이 기한을 지키지 않은 신청자는 자동적으로 신청 취소처리되고 '
                                                   '웨이팅리스트에 있는 다음 순번 후보자에게 신청권한이 '
                                                   '넘어갑니다.</span></p><p><br></p><p><br></p><p><span '
                                                   'style="background-color: rgb(255, 255, 255); '
                                                   'color: rgb(31, 31, 31);">Chicho Frumboli &amp; '
                                                   'Juana Sepulveda will be invited to Korea, true '
                                                   'tango artists of our time and our great tango '
                                                   'masters. With an all-time high guarantee, it '
                                                   'was difficult to even make contact, and making '
                                                   'an invitation has been more challenging until '
                                                   'now. However, following their invitation in '
                                                   '2007, their return to Korea has finally been '
                                                   'realized after 20 '
                                                   'years.</span></p><p><br></p><p><span '
                                                   'style="background-color: rgb(255, 255, 255); '
                                                   'color: rgb(31, 31, 31);">The Masters '
                                                   'themselves explain their "untitled" seminars '
                                                   'as follows: "The classes in our seminars are '
                                                   'untitled; the idea is for people to '
                                                   'participate in all 12 hours of classes, and we '
                                                   'cover different topics within '
                                                   'tango."</span></p><p><br></p><p><span '
                                                   'style="background-color: rgb(255, 255, 255); '
                                                   'color: rgb(31, 31, 31);">The significance of '
                                                   'this description of the "Untitled Class" lies '
                                                   'in the fact that, rather than merely getting a '
                                                   'superficial taste of the subject through one '
                                                   'or two lessons, the course proceeds as an '
                                                   'entire 12-hour seminar where concepts are '
                                                   'organically connected and progressively '
                                                   'developed. By taking the full 12-hour tango '
                                                   'seminar, you can properly grasp the essence of '
                                                   'the great tango artists of our time and fully '
                                                   'experience the consistent tango philosophy of '
                                                   'the masters that permeates the entire '
                                                   'seminar.</span></p><p><br></p><p><span '
                                                   'style="background-color: rgb(255, 255, 255); '
                                                   'color: rgb(31, 31, 31);">To ensure smooth '
                                                   'class progression for the masters and a proper '
                                                   'understanding for the students, this tango '
                                                   'seminar is only available through full package '
                                                   'applications. Registration is limited to 20 '
                                                   'couples on a first-come, first-served basis. '
                                                   'As early closure is expected, please apply '
                                                   'promptly. The number of available private '
                                                   'lessons is also limited; they are available '
                                                   'before or after the group class and require '
                                                   'advance registration. Please check the '
                                                   '"Private Lesson" option at the bottom and '
                                                   'contact us '
                                                   'individually.</span></p><p><br></p><p><span '
                                                   'style="background-color: rgb(255, 255, 255); '
                                                   'color: rgb(31, 31, 31);">Domestic applicants '
                                                   'must deposit the full application fee before '
                                                   'midnight on October 15, while international '
                                                   'applicants must pay on-site but send a '
                                                   'confirmation email until October 15 using the '
                                                   'email address used during application. If an '
                                                   'applicant fails to meet this deadline, their '
                                                   'application will be automatically cancelled, '
                                                   'and the right to apply will be passed to the '
                                                   'next candidate on the waiting '
                                                   'list.</span></p><p><br></p>'},
 'https://miltang.com/notices/19': {'ld': {'@context': 'https://schema.org',
                                           '@type': 'Event',
                                           'name': 'KOREA SPECIAL TANGO WEEK 2026 (홍대)',
                                           'url': 'https://miltang.com/notices/19',
                                           'startDate': '2026-11-21',
                                           'endDate': '2026-11-24',
                                           'eventStatus': 'https://schema.org/EventScheduled',
                                           'eventAttendanceMode': 'https://schema.org/OfflineEventAttendanceMode',
                                           'description': '협찬 | 부산 탱고 마라톤[포항] 11/18~11/20 워크숍 & '
                                                          '이벤트POHANG WELCOME MILONGA — 11/20(금) '
                                                          '20:00~01:00[서울] 11/21~11/24 워크숍 & '
                                                          '이벤트SEOUL GRAND MILONGA @Oc…',
                                           'image': ['https://miltang.com/storage/notices/eWbjxaDG9cjq5Ya4GceENVRz6Ba34BXLoxwLA4z9.webp'],
                                           'location': {'@type': 'Place',
                                                        'name': 'Ocho 오초',
                                                        'address': {'@type': 'PostalAddress',
                                                                    'streetAddress': '서울 마포구 '
                                                                                     '월드컵북로2길 57 '
                                                                                     '지하1층',
                                                                    'addressCountry': 'KR'}},
                                           'organizer': {'@type': 'Organization',
                                                         'name': '부산탱고협동조합'}},
                                    'date_row': '2026. 11. 21(토) ~ 2026. 11. 24(화)',
                                    'time_row': '상세 정보 링크 참고',
                                    'place_row': '<p class="font-bold">Ocho 오초</p> <p '
                                                 'class="text-fg3 text-xs mt-0.5">서울 마포구 월드컵북로2길 '
                                                 '57 지하1층</p> <button type="button" '
                                                 '@click="copy(\'addr\', \'서울 마포구 월드컵북로2길 57 '
                                                 '지하1층\')" class="btn-pill btn-pill--secondary '
                                                 'text-[11px] px-3 py-1 mt-2 inline-flex '
                                                 'items-center gap-1"> <span class="ms-icon '
                                                 'text-[12px]">content_copy</span> <span '
                                                 'x-text="copied.addr ? \'복사됨\' : '
                                                 '\'주소복사\'"></span> </button>',
                                    'org_row': '부산탱고협동조합',
                                    'description': '<p>협찬 | 부산 탱고 마라톤</p><p><br></p><p>[포항] '
                                                   '11/18~11/20 워크숍 &amp; 이벤트</p><p>POHANG WELCOME '
                                                   'MILONGA — 11/20(금) '
                                                   '20:00~01:00</p><p><br></p><p>[서울] 11/21~11/24 '
                                                   '워크숍 &amp; 이벤트</p><p>SEOUL GRAND MILONGA @Ocho '
                                                   '— 11/21(토) 21:00~02:00</p>'},
 'https://miltang.com/notices/20': {'ld': {'@context': 'https://schema.org',
                                           '@type': 'Event',
                                           'name': 'KOREA SPECIAL TANGO WEEK 2026 (포항)',
                                           'url': 'https://miltang.com/notices/20',
                                           'startDate': '2026-11-18',
                                           'endDate': '2026-11-21',
                                           'eventStatus': 'https://schema.org/EventScheduled',
                                           'eventAttendanceMode': 'https://schema.org/OfflineEventAttendanceMode',
                                           'description': '협찬 | 부산 탱고 마라톤[포항] 11/18~11/20 워크숍 & '
                                                          '이벤트POHANG WELCOME MILONGA — 11/20(금) '
                                                          '20:00~01:00[서울] 11/21~11/24 워크숍 & '
                                                          '이벤트SEOUL GRAND MILONGA @Oc…',
                                           'image': ['https://miltang.com/storage/notices/LppI5xK6ZcrQBwIshvz8n1FRWXLSTLKAtiF8U514.webp'],
                                           'location': {'@type': 'Place',
                                                        'name': 'PosTango 포스탱고',
                                                        'address': {'@type': 'PostalAddress',
                                                                    'streetAddress': '포항시 남구 중앙로 '
                                                                                     '83, 3층 프스탱고',
                                                                    'addressCountry': 'KR'}},
                                           'organizer': {'@type': 'Organization',
                                                         'name': '부산탱고협동조합'}},
                                    'date_row': '2026. 11. 18(수) ~ 2026. 11. 21(토)',
                                    'time_row': '세부 링크 정보 참고',
                                    'place_row': '<p class="font-bold">PosTango 포스탱고</p> <p '
                                                 'class="text-fg3 text-xs mt-0.5">포항시 남구 중앙로 83, '
                                                 '3층 프스탱고</p> <button type="button" '
                                                 '@click="copy(\'addr\', \'포항시 남구 중앙로 83, 3층 '
                                                 '프스탱고\')" class="btn-pill btn-pill--secondary '
                                                 'text-[11px] px-3 py-1 mt-2 inline-flex '
                                                 'items-center gap-1"> <span class="ms-icon '
                                                 'text-[12px]">content_copy</span> <span '
                                                 'x-text="copied.addr ? \'복사됨\' : '
                                                 '\'주소복사\'"></span> </button>',
                                    'org_row': '부산탱고협동조합',
                                    'description': '<p>협찬 | 부산 탱고 마라톤</p><p><br></p><p>[포항] '
                                                   '11/18~11/20 워크숍 &amp; 이벤트</p><p>POHANG WELCOME '
                                                   'MILONGA — 11/20(금) '
                                                   '20:00~01:00</p><p><br></p><p>[서울] 11/21~11/24 '
                                                   '워크숍 &amp; 이벤트</p><p>SEOUL GRAND MILONGA @Ocho '
                                                   '— 11/21(토) 21:00~02:00</p>'},
 'https://miltang.com/notices/4': {'ld': {'@context': 'https://schema.org',
                                          '@type': 'Event',
                                          'name': 'JEJU Summ Milonga',
                                          'url': 'https://miltang.com/notices/4',
                                          'startDate': '2026-08-21',
                                          'endDate': '2026-08-23',
                                          'eventStatus': 'https://schema.org/EventScheduled',
                                          'eventAttendanceMode': 'https://schema.org/OfflineEventAttendanceMode',
                                          'image': ['https://miltang.com/storage/notices/5TjsxEd9hwE3NvKCsWeK4gej62JF2TcO7Z7rLahR.webp'],
                                          'location': {'@type': 'Place',
                                                       'name': '씨오르리조트',
                                                       'address': {'@type': 'PostalAddress',
                                                                   'streetAddress': '제주특별자치도 서귀포시 '
                                                                                    '이어도로 989',
                                                                   'addressCountry': 'KR'}},
                                          'organizer': {'@type': 'Organization',
                                                        'name': 'Augusto Kim'}},
                                   'date_row': '2026. 8. 21(금) ~ 2026. 8. 23(일)',
                                   'time_row': '8월 21일 오후 4시 ~ 8월 23일 오후 6시',
                                   'place_row': '<p class="font-bold">씨오르리조트</p> <p '
                                                'class="text-fg3 text-xs mt-0.5">제주특별자치도 서귀포시 이어도로 '
                                                '989</p> <button type="button" '
                                                '@click="copy(\'addr\', \'제주특별자치도 서귀포시 이어도로 '
                                                '989\')" class="btn-pill btn-pill--secondary '
                                                'text-[11px] px-3 py-1 mt-2 inline-flex '
                                                'items-center gap-1"> <span class="ms-icon '
                                                'text-[12px]">content_copy</span> <span '
                                                'x-text="copied.addr ? \'복사됨\' : \'주소복사\'"></span> '
                                                '</button>',
                                   'org_row': 'Augusto Kim',
                                   'description': None},
 'https://miltang.com/notices/11': {'ld': {'@context': 'https://schema.org',
                                           '@type': 'Event',
                                           'name': 'Estrellas',
                                           'url': 'https://miltang.com/notices/11',
                                           'startDate': '2026-10-17',
                                           'endDate': '2026-10-18',
                                           'eventStatus': 'https://schema.org/EventScheduled',
                                           'eventAttendanceMode': 'https://schema.org/OfflineEventAttendanceMode',
                                           'image': ['https://miltang.com/storage/imports/ktnow_6a7731a24c0fb8.74068191_87183ba5b451ea68.jpg'],
                                           'location': {'@type': 'Place',
                                                        'name': '순천시 서면 청소년 수련원',
                                                        'address': {'@type': 'PostalAddress',
                                                                    'streetAddress': '전남광주통합특별시 '
                                                                                     '순천시 서면 '
                                                                                     '청소년수련원길 167',
                                                                    'addressCountry': 'KR'}}},
                                    'date_row': '2026. 10. 17(토) ~ 2026. 10. 18(일)',
                                    'time_row': None,
                                    'place_row': '<p class="font-bold">순천시 서면 청소년 수련원</p> <p '
                                                 'class="text-fg3 text-xs mt-0.5">전남광주통합특별시 순천시 서면 '
                                                 '청소년수련원길 167</p> <button type="button" '
                                                 '@click="copy(\'addr\', \'전남광주통합특별시 순천시 서면 '
                                                 '청소년수련원길 167\')" class="btn-pill '
                                                 'btn-pill--secondary text-[11px] px-3 py-1 mt-2 '
                                                 'inline-flex items-center gap-1"> <span '
                                                 'class="ms-icon text-[12px]">content_copy</span> '
                                                 '<span x-text="copied.addr ? \'복사됨\' : '
                                                 '\'주소복사\'"></span> </button>',
                                    'org_row': None,
                                    'description': None},
 'https://miltang.com/notices/13': {'ld': {'@context': 'https://schema.org',
                                           '@type': 'Event',
                                           'name': 'RoyBeDDong in BUSAN',
                                           'url': 'https://miltang.com/notices/13',
                                           'startDate': '2026-12-18',
                                           'endDate': '2026-12-20',
                                           'eventStatus': 'https://schema.org/EventScheduled',
                                           'eventAttendanceMode': 'https://schema.org/OfflineEventAttendanceMode',
                                           'image': ['https://miltang.com/storage/imports/ktnow_6a77326540dfc8.99413980_12c3629ec5d6c8d7.jpg',
                                                     'https://miltang.com/storage/imports/ktnow_6a7732654213d8.49516354_4b90b455f307d3e1.jpg'],
                                           'location': {'@type': 'Place', 'name': '상세 공지 참고'}},
                                    'date_row': '2026. 12. 18(금) ~ 2026. 12. 20(일)',
                                    'time_row': None,
                                    'place_row': '<p class="font-bold">상세 공지 참고</p>',
                                    'org_row': None,
                                    'description': None},
 'https://miltang.com/notices/10': {'ld': {'@context': 'https://schema.org',
                                           '@type': 'Event',
                                           'name': 'Juan Malizia & Manuela Rossi in Seoul',
                                           'url': 'https://miltang.com/notices/10',
                                           'startDate': '2026-10-07',
                                           'endDate': '2026-10-20',
                                           'eventStatus': 'https://schema.org/EventScheduled',
                                           'eventAttendanceMode': 'https://schema.org/OfflineEventAttendanceMode',
                                           'image': ['https://miltang.com/storage/imports/ktnow_6a773117ed0264.96879670_7bb577cab646df7a.jpg'],
                                           'location': {'@type': 'Place',
                                                        'name': 'Otra Tango Club 오뜨라 탱고 클럽',
                                                        'address': {'@type': 'PostalAddress',
                                                                    'streetAddress': '마포구 홍익로5안길 '
                                                                                     '20 재강빌딩 지하 '
                                                                                     '1층',
                                                                    'addressCountry': 'KR'}}},
                                    'date_row': '2026. 10. 7(수) ~ 2026. 10. 20(화)',
                                    'time_row': None,
                                    'place_row': '<p class="font-bold">Otra Tango Club 오뜨라 탱고 '
                                                 '클럽</p> <p class="text-fg3 text-xs mt-0.5">마포구 '
                                                 '홍익로5안길 20 재강빌딩 지하 1층</p> <button type="button" '
                                                 '@click="copy(\'addr\', \'마포구 홍익로5안길 20 재강빌딩 지하 '
                                                 '1층\')" class="btn-pill btn-pill--secondary '
                                                 'text-[11px] px-3 py-1 mt-2 inline-flex '
                                                 'items-center gap-1"> <span class="ms-icon '
                                                 'text-[12px]">content_copy</span> <span '
                                                 'x-text="copied.addr ? \'복사됨\' : '
                                                 '\'주소복사\'"></span> </button>',
                                    'org_row': None,
                                    'description': None}}

from src.database import init_db,create_preventive_quarantine
from src.source_reliability import evaluate_verification_policy
from src.source_independence_graph import register_relationship,evaluate_pair
from src.automated_origin_inference import infer_cross_post_cluster,review_cluster,clusters
R='VERIFIED_EVENT_EXISTENCE'; Q='Q48'

def src(con,s,p):
 con.execute("INSERT OR REPLACE INTO sources(source_id,platform,source_role,name,status,authority_level,access_state) VALUES(?,?,?,?,?,?,?)",(s,p,'SECONDARY',s,'ACTIVE','SECONDARY','OPEN')); con.commit()
def post(con,event,sid,title,body,pub,url):
 cur=con.execute("INSERT INTO raw_posts(fixture_key,source_id,source_url,external_key,published_at,title,body,collected_at) VALUES(?,?,?,?,?,?,?,datetime('now'))",(sid,sid,url,f'{event}-{sid}',pub,title,body)); pid=cur.lastrowid
 c=con.execute("INSERT INTO event_candidates(post_id,name,status,core_complete) VALUES(?,?,?,?)",(pid,title,'POSSIBLE',1)).lastrowid
 con.execute("INSERT INTO event_instance_candidates(event_instance_id,candidate_id,source_id,linked_at) VALUES(?,?,?,datetime('now'))",(event,c,sid)); con.commit()
def setup(con,event=1):
 src(con,Q,'FACEBOOK'); src(con,'A','NAVER_BLOG'); src(con,'B','DAUM_CAFE')
 con.execute("INSERT INTO event_instances(event_instance_id,identity_key,status,created_at,updated_at) VALUES(?,?,?,datetime('now'),datetime('now'))",(event,f'e{event}','POSSIBLE')); con.commit()

def test_near_duplicate_cluster_and_likely_earliest_origin(tmp_path):
 con=init_db(tmp_path/'a.db'); setup(con,1)
 post(con,1,'A','밀롱가 오초','8월 31일 일요일 오후 8시 입장료 13000원 DJ Kim','2026-08-30T10:00:00','https://a/x')
 post(con,1,'B','밀롱가 오초','8월 31일 일요일 오후 8시 입장료 13000원 DJ Kim 입니다','2026-08-30T11:00:00','https://b/y')
 r=infer_cross_post_cluster(con,1,.75); assert len(r['clusters'])==1
 c=r['clusters'][0]; assert c['status']=='AUTO_SUSPECTED_SYNDICATION'; assert c['likely_origin_source_id']=='A'; assert c['member_count']==2
 con.close()

def test_auto_suspected_cluster_blocks_fake_independence_shadow_safely(tmp_path):
 con=init_db(tmp_path/'b.db'); setup(con,2)
 register_relationship(con,source_id_a='A',source_id_b='B',relationship_type='INDEPENDENT',reviewed_by='r')
 post(con,2,'A','Dance Night','same event notice price 13000 time 20 00 music tango','2026-08-30T10:00:00','https://a/x')
 post(con,2,'B','Dance Night','same event notice price 13000 time 20 00 music tango tonight','2026-08-30T10:05:00','https://b/y')
 infer_cross_post_cluster(con,2,.70)
 r=evaluate_pair(con,event_instance_id=2,source_id_a='A',source_id_b='B'); assert r['relationship_type']=='RELATED'; assert r['independence_status']=='NOT_INDEPENDENT'; assert 'AUTO_SUSPECTED_CROSS_POST' in r['syndication_signals']
 con.close()

def test_human_confirm_syndication_upgrades_cluster_state(tmp_path):
 con=init_db(tmp_path/'c.db'); setup(con,3)
 post(con,3,'A','x','very similar event announcement alpha beta gamma delta','2026-08-30T10:00:00','https://a/x'); post(con,3,'B','x','very similar event announcement alpha beta gamma delta today','2026-08-30T11:00:00','https://b/y')
 c=infer_cross_post_cluster(con,3,.70)['clusters'][0]; review_cluster(con,c['cluster_id'],'CONFIRM_SYNDICATION','op','confirmed repost')
 r=evaluate_pair(con,event_instance_id=3,source_id_a='A',source_id_b='B'); assert r['relationship_type']=='SYNDICATED'; assert 'HUMAN_CONFIRMED_CROSS_POST_CLUSTER' in r['syndication_signals']
 con.close()

def test_human_confirm_independent_can_clear_false_positive(tmp_path):
 con=init_db(tmp_path/'d.db'); setup(con,4)
 post(con,4,'A','x','same schedule wording common template tango event tonight','2026-08-30T10:00:00','https://a/x'); post(con,4,'B','x','same schedule wording common template tango event tonight now','2026-08-30T11:00:00','https://b/y')
 c=infer_cross_post_cluster(con,4,.70)['clusters'][0]; review_cluster(con,c['cluster_id'],'CONFIRM_INDEPENDENT','op','separate original organizer confirmations')
 r=evaluate_pair(con,event_instance_id=4,source_id_a='A',source_id_b='B'); assert r['independence_status']=='INDEPENDENT'
 con.close()

def test_no_near_duplicate_creates_no_cluster(tmp_path):
 con=init_db(tmp_path/'e.db'); setup(con,5)
 post(con,5,'A','alpha','completely different first announcement','2026-08-30T10:00:00','https://a/x'); post(con,5,'B','beta','unrelated second text about another detail','2026-08-30T11:00:00','https://b/y')
 assert infer_cross_post_cluster(con,5,.90)['clusters']==[]; con.close()

def test_cross_post_route_stays_possible_until_human_clears(tmp_path):
 con=init_db(tmp_path/'f.db'); setup(con,6); create_preventive_quarantine(con,source_id=Q,rule_key=R,trigger_recovery_case_id=1,trigger_reason='q',metadata={})
 register_relationship(con,source_id_a='A',source_id_b='B',relationship_type='INDEPENDENT',reviewed_by='r')
 post(con,6,'A','x','milonga same notice sunday 8pm fee 13000 organizer abc','2026-08-30T10:00:00','https://a/x'); post(con,6,'B','x','milonga same notice sunday 8pm fee 13000 organizer abc now','2026-08-30T10:10:00','https://b/y')
 infer_cross_post_cluster(con,6,.70)
 for s in ('A','B'): evaluate_verification_policy(con,decision_key=s,event_instance_id=6,source_id=s,rule_key=R,base_eligible=True)
 q=evaluate_verification_policy(con,decision_key='q',event_instance_id=6,source_id=Q,rule_key=R,base_eligible=True); assert q['alternative_route']['route_status']=='ROUTED_POSSIBLE'
 c=clusters(con,6)[0]; review_cluster(con,c['cluster_id'],'CONFIRM_INDEPENDENT','op','independent originals verified')
 q2=evaluate_verification_policy(con,decision_key='q2',event_instance_id=6,source_id=Q,rule_key=R,base_eligible=True); assert q2['alternative_route']['route_status']=='ROUTED_VERIFIED'; con.close()

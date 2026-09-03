from datetime import datetime, timezone
from .database import (
    init_db,create_lineage,start_observation,finish_observation,
    link_observation_post,link_observation_event,close_lineage,lineage_trace,
    persist_raw_post,upsert_event_instance
)
from .collectors.base import RawPostRecord

def run_snapshot(con):
    lineage_id=create_lineage(con,root_run_type="DISCOVERY",root_source_id="SRC-D-001",
                              root_query="8/27 더 피스타 밀롱가")

    # Discovery
    d=start_observation(con,run_type="DISCOVERY",source_id="SRC-D-001",
                        query_text="8/27 더 피스타 밀롱가",lineage_id=lineage_id,stage="DISCOVERY")
    p=RawPostRecord("SRC-D-001","DAUM_CAFE","https://snapshot.local/lineage/pista",
                    "8/27 더 피스타 밀롱가","8/27 PISTA 입장료 13000",acquisition_quality="METADATA_ONLY")
    post_id,_=persist_raw_post(con,p)
    link_observation_post(con,lineage_id=lineage_id,observation_id=d,post_id=post_id,
                          source_id="SRC-D-001",role="DISCOVERED")
    finish_observation(con,d,result_status="PASS",discovered_count=1,rawpost_new_count=1)

    # Acquisition child
    a=start_observation(con,run_type="ACQUISITION",source_id="SRC-D-001",
                        target_url=p.source_url,lineage_id=lineage_id,parent_observation_id=d,stage="ACQUISITION")
    finish_observation(con,a,result_status="PARTIAL",acquisition_attempt_count=1,
                       acquisition_success_count=0,acquisition_failure_count=1,
                       error_code="BODY_UNAVAILABLE")

    # Recovery child
    r=start_observation(con,run_type="RECOVERY",source_id="SRC-N-001",
                        query_text="PISTA 2026-08-27",lineage_id=lineage_id,
                        parent_observation_id=a,stage="RECOVERY")
    finish_observation(con,r,result_status="PASS",recovery_attempt_count=1,recovery_success_count=1)

    # Event instance result
    eid=upsert_event_instance(con,"2026-08-27|pista|pista","pista","2026-08-27","pista","VERIFIED")
    link_observation_event(con,lineage_id=lineage_id,observation_id=r,event_instance_id=eid,role="RESOLVED_EVENT")
    close_lineage(con,lineage_id,"COMPLETE")
    return lineage_trace(con,lineage_id)

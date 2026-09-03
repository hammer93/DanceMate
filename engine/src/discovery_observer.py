from .database import start_observation,finish_observation,record_observation_rawpost,link_observation_post
def run_discovery_with_lineage(con, *, source_id, query, collector_callable):
    obs_id=start_observation(con,run_type="DISCOVERY",source_id=source_id,query_text=query,stage="DISCOVERY")
    lineage_id=con.execute("SELECT lineage_id FROM observation_runs WHERE observation_id=?",(obs_id,)).fetchone()["lineage_id"]
    rows=collector_callable()
    finish_observation(con,obs_id,result_status="PASS",discovered_count=len(rows),metadata={"query":query})
    return {"lineage_id":lineage_id,"observation_id":obs_id,"rows":rows}
def record_discovery_persist_result(con, *, lineage_id, observation_id, post_id, source_id, source_url, is_new):
    record_observation_rawpost(con,observation_id,post_id=post_id,source_id=source_id,source_url=source_url,
                               event_kind="NEW" if is_new else "DUPLICATE")
    link_observation_post(con,lineage_id=lineage_id,observation_id=observation_id,post_id=post_id,
                          source_id=source_id,role="DISCOVERED" if is_new else "DUPLICATE")
    row=con.execute("SELECT rawpost_new_count,rawpost_duplicate_count FROM observation_runs WHERE observation_id=?",(observation_id,)).fetchone()
    con.execute("UPDATE observation_runs SET rawpost_new_count=?,rawpost_duplicate_count=? WHERE observation_id=?",
                ((row["rawpost_new_count"] or 0)+(1 if is_new else 0),
                 (row["rawpost_duplicate_count"] or 0)+(0 if is_new else 1),observation_id))
    con.commit()

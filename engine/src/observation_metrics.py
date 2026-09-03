def _ratio(n,d):
    return round(n/d,4) if d else None

def calculate_observation_metrics(con):
    totals=con.execute("""SELECT
        COUNT(*) runs,
        COALESCE(SUM(discovered_count),0) discovered,
        COALESCE(SUM(rawpost_new_count),0) raw_new,
        COALESCE(SUM(rawpost_duplicate_count),0) raw_dup,
        COALESCE(SUM(acquisition_attempt_count),0) acq_attempts,
        COALESCE(SUM(acquisition_success_count),0) acq_success,
        COALESCE(SUM(acquisition_failure_count),0) acq_fail,
        COALESCE(SUM(recovery_attempt_count),0) rec_attempts,
        COALESCE(SUM(recovery_success_count),0) rec_success
        FROM observation_runs
        WHERE result_status<>'RUNNING'""").fetchone()

    source_rows=con.execute("""SELECT source_id,
        COALESCE(SUM(discovered_count),0) discovered,
        COALESCE(SUM(rawpost_new_count),0) raw_new,
        COALESCE(SUM(acquisition_attempt_count),0) acq_attempts,
        COALESCE(SUM(acquisition_failure_count),0) acq_fail,
        COALESCE(SUM(recovery_attempt_count),0) rec_attempts,
        COALESCE(SUM(recovery_success_count),0) rec_success
        FROM observation_runs
        WHERE result_status<>'RUNNING'
        GROUP BY source_id
        ORDER BY source_id""").fetchall()

    overall={
      "run_count":totals["runs"],
      "discovered_count":totals["discovered"],
      "rawpost_new_count":totals["raw_new"],
      "rawpost_duplicate_count":totals["raw_dup"],
      "acquisition_attempt_count":totals["acq_attempts"],
      "acquisition_success_count":totals["acq_success"],
      "acquisition_failure_count":totals["acq_fail"],
      "recovery_attempt_count":totals["rec_attempts"],
      "recovery_success_count":totals["rec_success"],
      "source_yield_rate":_ratio(totals["raw_new"],totals["discovered"]),
      "access_failure_rate":_ratio(totals["acq_fail"],totals["acq_attempts"]),
      "recovery_success_rate":_ratio(totals["rec_success"],totals["rec_attempts"]),
    }

    sources=[]
    for r in source_rows:
        sources.append({
          "source_id":r["source_id"],
          "discovered_count":r["discovered"],
          "rawpost_new_count":r["raw_new"],
          "acquisition_attempt_count":r["acq_attempts"],
          "acquisition_failure_count":r["acq_fail"],
          "recovery_attempt_count":r["rec_attempts"],
          "recovery_success_count":r["rec_success"],
          "source_yield_rate":_ratio(r["raw_new"],r["discovered"]),
          "access_failure_rate":_ratio(r["acq_fail"],r["acq_attempts"]),
          "recovery_success_rate":_ratio(r["rec_success"],r["rec_attempts"]),
        })
    return {"overall":overall,"sources":sources}

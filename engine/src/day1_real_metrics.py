def r(n,d): return round(n/d,4) if d else None
def calculate(x):
    es=x["events"]; total=len(es)*4
    verified=sum(3+(1 if e.get("fee_verified") is not None else 0) for e in es)
    expected=sum(1 for e in es if e.get("fee_verified") is None and e.get("fee_expected") is not None)
    unknown=total-verified-expected
    hc=sum(1 for e in es if e["confidence"]=="HIGH_CONFIDENCE")
    limited=sum(1 for s in x["primary_sources"] if s["access"]!="OPEN")
    return {"event_count":len(es),"high_confidence":hc,"possible":len(es)-hc,
      "core_field_total":total,"verified_fields":verified,"expected_fields":expected,"unknown_fields":unknown,
      "field_coverage_rate":r(verified,total),"known_field_rate":r(verified+expected,total),
      "fee_verified_rate":r(sum(e.get("fee_verified") is not None for e in es),len(es)),
      "fee_expected_rate":r(expected,len(es)),
      "observed_primary_access_problem_rate":r(limited,len(x["primary_sources"])),
      "source_yield_rate":None,"access_failure_rate":None,"primary_recovery_success_rate":None,
      "measurement_gaps":["raw post denominator not retained","complete acquisition-attempt denominator not retained","recovery denominator not retained"]}

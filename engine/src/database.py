import hashlib
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS sources(
 source_id TEXT PRIMARY KEY,
 platform TEXT,
 source_role TEXT,
 name TEXT,
 status TEXT,
 authority_level TEXT DEFAULT 'UNKNOWN',
 access_state TEXT DEFAULT 'UNKNOWN'
);
CREATE TABLE IF NOT EXISTS raw_posts(
 post_id INTEGER PRIMARY KEY AUTOINCREMENT,
 fixture_key TEXT,
 source_id TEXT,
 source_url TEXT,
 external_key TEXT UNIQUE,
 published_at TEXT,
 title TEXT NOT NULL,
 body TEXT,
 cafe_name TEXT,
 thumbnail_url TEXT,
 discovery_query TEXT,
 acquisition_quality TEXT,
 raw_json TEXT,
 raw_hash TEXT,
 collected_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS event_candidates(
 candidate_id INTEGER PRIMARY KEY AUTOINCREMENT, post_id INTEGER NOT NULL, name TEXT,
 event_type TEXT, event_date TEXT, start_time TEXT, end_time TEXT, end_day_offset INTEGER,
 fee INTEGER, venue TEXT, dj TEXT, status TEXT, core_complete INTEGER,
 FOREIGN KEY(post_id) REFERENCES raw_posts(post_id)
);
CREATE TABLE IF NOT EXISTS evidences(
 evidence_id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_id INTEGER NOT NULL,
 field TEXT, value TEXT, raw_text TEXT, evidence_type TEXT, source_role TEXT, inference TEXT,
 -- Which text segment this value came from, when the post had more than one
 -- (a multi-program post) - NULL for a single-segment post, unchanged from
 -- before v0.81.2. See extractor.py's context segmentation.
 context_id TEXT,
 FOREIGN KEY(candidate_id) REFERENCES event_candidates(candidate_id)
);
-- v0.81.2: runtime/candidates.py's review queue now filters and sorts
-- event_candidates/raw_posts/evidences directly in SQL instead of reading up
-- to 300 rows and cutting them in Python - these are the indexes that query
-- needs to not just move the cost from Python to an unindexed full scan.
CREATE INDEX IF NOT EXISTS idx_event_candidates_post ON event_candidates(post_id);
CREATE INDEX IF NOT EXISTS idx_event_candidates_status_date
    ON event_candidates(status, event_date);
CREATE INDEX IF NOT EXISTS idx_event_candidates_date ON event_candidates(event_date);
CREATE INDEX IF NOT EXISTS idx_raw_posts_collected ON raw_posts(collected_at);
CREATE INDEX IF NOT EXISTS idx_evidences_candidate_field ON evidences(candidate_id, field);
CREATE TABLE IF NOT EXISTS collector_runs(
 run_id INTEGER PRIMARY KEY AUTOINCREMENT,
 collector TEXT NOT NULL,
 source_id TEXT,
 mode TEXT NOT NULL,
 query_count INTEGER DEFAULT 0,
 discovered_count INTEGER DEFAULT 0,
 new_count INTEGER DEFAULT 0,
 duplicate_count INTEGER DEFAULT 0,
 started_at TEXT NOT NULL,
 finished_at TEXT,
 status TEXT NOT NULL,
 error TEXT
);
CREATE TABLE IF NOT EXISTS acquisition_runs(
 acquisition_id INTEGER PRIMARY KEY AUTOINCREMENT,
 post_id INTEGER NOT NULL,
 source_id TEXT NOT NULL,
 source_url TEXT NOT NULL,
 mode TEXT NOT NULL,
 status TEXT NOT NULL,
 http_status INTEGER,
 final_url TEXT,
 content_type TEXT,
 body_chars INTEGER DEFAULT 0,
 image_count INTEGER DEFAULT 0,
 poster_candidate_count INTEGER DEFAULT 0,
 started_at TEXT NOT NULL,
 finished_at TEXT,
 error_code TEXT,
 error TEXT,
 FOREIGN KEY(post_id) REFERENCES raw_posts(post_id)
);
CREATE TABLE IF NOT EXISTS acquired_media(
 media_id INTEGER PRIMARY KEY AUTOINCREMENT,
 acquisition_id INTEGER NOT NULL,
 post_id INTEGER NOT NULL,
 media_url TEXT NOT NULL,
 media_type TEXT NOT NULL,
 poster_candidate INTEGER DEFAULT 0,
 media_class TEXT DEFAULT 'UNKNOWN',
 media_class_reason TEXT,
 FOREIGN KEY(acquisition_id) REFERENCES acquisition_runs(acquisition_id),
 FOREIGN KEY(post_id) REFERENCES raw_posts(post_id)
);
CREATE TABLE IF NOT EXISTS event_instances(
 event_instance_id INTEGER PRIMARY KEY AUTOINCREMENT,
 identity_key TEXT UNIQUE,
 normalized_name TEXT,
 event_date TEXT,
 normalized_venue TEXT,
 status TEXT NOT NULL DEFAULT 'POSSIBLE',
 source_count INTEGER DEFAULT 0,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS event_instance_candidates(
 link_id INTEGER PRIMARY KEY AUTOINCREMENT,
 event_instance_id INTEGER NOT NULL,
 candidate_id INTEGER NOT NULL UNIQUE,
 source_id TEXT NOT NULL,
 linked_at TEXT NOT NULL,
 FOREIGN KEY(event_instance_id) REFERENCES event_instances(event_instance_id),
 FOREIGN KEY(candidate_id) REFERENCES event_candidates(candidate_id)
);
CREATE TABLE IF NOT EXISTS event_field_states(
 field_state_id INTEGER PRIMARY KEY AUTOINCREMENT,
 event_instance_id INTEGER NOT NULL,
 field_name TEXT NOT NULL,
 value TEXT,
 confidence TEXT NOT NULL,
 evidence_ids_json TEXT,
 expected_value TEXT,
 verified_value TEXT,
 source_scope TEXT,
 updated_at TEXT NOT NULL,
 UNIQUE(event_instance_id,field_name),
 FOREIGN KEY(event_instance_id) REFERENCES event_instances(event_instance_id)
);
CREATE TABLE IF NOT EXISTS event_revisions(
 revision_id INTEGER PRIMARY KEY AUTOINCREMENT,
 event_instance_id INTEGER NOT NULL,
 candidate_id INTEGER,
 source_id TEXT NOT NULL,
 revision_role TEXT NOT NULL,
 effective_at TEXT,
 observed_at TEXT NOT NULL,
 field_changes_json TEXT,
 raw_summary TEXT,
 is_current INTEGER DEFAULT 1,
 FOREIGN KEY(event_instance_id) REFERENCES event_instances(event_instance_id),
 FOREIGN KEY(candidate_id) REFERENCES event_candidates(candidate_id)
);
CREATE TABLE IF NOT EXISTS event_refresh_checks(
 check_id INTEGER PRIMARY KEY AUTOINCREMENT,
 event_instance_id INTEGER NOT NULL,
 checked_at TEXT NOT NULL,
 scheduled_event_date TEXT,
 hours_before_start REAL,
 status_before TEXT,
 status_after TEXT,
 change_detected INTEGER DEFAULT 0,
 cancellation_detected INTEGER DEFAULT 0,
 critical_miss INTEGER DEFAULT 0,
 source_id TEXT,
 notes TEXT,
 FOREIGN KEY(event_instance_id) REFERENCES event_instances(event_instance_id)
);
CREATE TABLE IF NOT EXISTS change_effect_verdicts(
 verdict_id INTEGER PRIMARY KEY AUTOINCREMENT,
 change_id INTEGER NOT NULL,
 baseline_daily_run_id TEXT,
 post_daily_run_id TEXT,
 verdict TEXT NOT NULL,
 comparable_metric_count INTEGER DEFAULT 0,
 improved_metric_count INTEGER DEFAULT 0,
 regressed_metric_count INTEGER DEFAULT 0,
 unchanged_metric_count INTEGER DEFAULT 0,
 score REAL,
 weighted_score REAL,
 goal_profile TEXT,
 metric_weights_json TEXT,
 improved_metrics_json TEXT,
 regressed_metrics_json TEXT,
 unchanged_metrics_json TEXT,
 reasons_json TEXT,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS canary_outcome_evaluations(
 outcome_id INTEGER PRIMARY KEY AUTOINCREMENT,
 lease_id INTEGER NOT NULL,
 policy_version TEXT NOT NULL,
 status TEXT NOT NULL,
 completed_changes INTEGER NOT NULL,
 safe_changes INTEGER NOT NULL,
 divergent_changes INTEGER NOT NULL,
 divergence_rate REAL,
 false_optimism_count INTEGER NOT NULL DEFAULT 0,
 base_improved_count INTEGER NOT NULL DEFAULT 0,
 canary_improved_count INTEGER NOT NULL DEFAULT 0,
 criteria_json TEXT NOT NULL,
 reasons_json TEXT NOT NULL,
 evaluated_at TEXT NOT NULL,
 FOREIGN KEY(lease_id) REFERENCES adaptive_promotion_leases(lease_id)
);
CREATE TABLE IF NOT EXISTS adaptive_final_promotion_reviews(
 final_review_id INTEGER PRIMARY KEY AUTOINCREMENT,
 lease_id INTEGER NOT NULL,
 candidate_id INTEGER NOT NULL,
 goal_profile TEXT NOT NULL,
 decision TEXT NOT NULL,
 reviewer TEXT NOT NULL,
 reason TEXT,
 outcome_id INTEGER,
 reviewed_at TEXT NOT NULL,
 metadata_json TEXT NOT NULL,
 FOREIGN KEY(lease_id) REFERENCES adaptive_promotion_leases(lease_id)
);
CREATE TABLE IF NOT EXISTS source_reliability_observations(
 reliability_observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
 observation_key TEXT NOT NULL UNIQUE,
 source_id TEXT NOT NULL,
 rule_key TEXT NOT NULL,
 outcome TEXT NOT NULL,
 severity TEXT NOT NULL,
 weight REAL NOT NULL,
 cluster_id INTEGER,
 attribution_id INTEGER,
 evidence_id INTEGER,
 rationale_json TEXT NOT NULL,
 observed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_reliability_profiles(
 profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
 source_id TEXT NOT NULL,
 rule_key TEXT NOT NULL,
 score REAL NOT NULL,
 band TEXT NOT NULL,
 critical_failure_count INTEGER NOT NULL DEFAULT 0,
 success_count INTEGER NOT NULL DEFAULT 0,
 observation_count INTEGER NOT NULL DEFAULT 0,
 consecutive_success_count INTEGER NOT NULL DEFAULT 0,
 last_critical_at TEXT,
 last_success_at TEXT,
 reasons_json TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 UNIQUE(source_id,rule_key)
);
CREATE TABLE IF NOT EXISTS preventive_verification_decisions(
 decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
 decision_key TEXT NOT NULL UNIQUE,
 event_instance_id INTEGER,
 source_id TEXT NOT NULL,
 rule_key TEXT NOT NULL,
 base_eligible INTEGER NOT NULL,
 independent_source_count INTEGER NOT NULL,
 human_confirmed INTEGER NOT NULL,
 existing_verified INTEGER NOT NULL DEFAULT 0,
 reliability_score REAL NOT NULL,
 reliability_band TEXT NOT NULL,
 shadow_action TEXT NOT NULL,
 production_action TEXT NOT NULL,
 production_mode TEXT NOT NULL,
 canary_id INTEGER,
 reasons_json TEXT NOT NULL,
 evaluated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS preventive_policy_canaries(
 canary_id INTEGER PRIMARY KEY AUTOINCREMENT,
 source_id TEXT NOT NULL,
 rule_key TEXT NOT NULL,
 status TEXT NOT NULL,
 max_decisions INTEGER NOT NULL,
 used_decisions INTEGER NOT NULL DEFAULT 0,
 approved_by TEXT NOT NULL,
 approved_at TEXT NOT NULL,
 ended_at TEXT,
 rollback_reason TEXT,
 metadata_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_relationships(
 relationship_id INTEGER PRIMARY KEY AUTOINCREMENT,
 source_id_a TEXT NOT NULL,
 source_id_b TEXT NOT NULL,
 relationship_type TEXT NOT NULL,
 confidence TEXT NOT NULL,
 provenance TEXT NOT NULL,
 reviewed_by TEXT,
 reason TEXT,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 UNIQUE(source_id_a,source_id_b)
);
CREATE TABLE IF NOT EXISTS evidence_origin_fingerprints(
 fingerprint_id INTEGER PRIMARY KEY AUTOINCREMENT,
 event_instance_id INTEGER NOT NULL,
 source_id TEXT NOT NULL,
 content_hash TEXT,
 poster_hash TEXT,
 canonical_url TEXT,
 origin_source_id TEXT,
 fingerprint_method TEXT NOT NULL,
 observed_at TEXT NOT NULL,
 UNIQUE(event_instance_id,source_id)
);
CREATE TABLE IF NOT EXISTS source_independence_evaluations(
 independence_evaluation_id INTEGER PRIMARY KEY AUTOINCREMENT,
 event_instance_id INTEGER NOT NULL,
 source_id_a TEXT NOT NULL,
 source_id_b TEXT NOT NULL,
 relationship_type TEXT NOT NULL,
 independence_status TEXT NOT NULL,
 relationship_evidence_json TEXT NOT NULL,
 syndication_signals_json TEXT NOT NULL,
 reasons_json TEXT NOT NULL,
 evaluated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cross_post_clusters(
 cluster_id INTEGER PRIMARY KEY AUTOINCREMENT,
 event_instance_id INTEGER NOT NULL,
 cluster_key TEXT NOT NULL,
 status TEXT NOT NULL,
 likely_origin_source_id TEXT,
 confidence TEXT NOT NULL,
 member_count INTEGER NOT NULL,
 reasons_json TEXT NOT NULL,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 UNIQUE(event_instance_id,cluster_key)
);
CREATE TABLE IF NOT EXISTS cross_post_cluster_members(
 member_id INTEGER PRIMARY KEY AUTOINCREMENT,
 cluster_id INTEGER NOT NULL,
 source_id TEXT NOT NULL,
 published_at TEXT,
 text_similarity REAL,
 same_poster INTEGER NOT NULL DEFAULT 0,
 same_link_origin INTEGER NOT NULL DEFAULT 0,
 origin_score REAL NOT NULL DEFAULT 0,
 signals_json TEXT NOT NULL,
 UNIQUE(cluster_id,source_id)
);
CREATE TABLE IF NOT EXISTS origin_inference_reviews(
 review_id INTEGER PRIMARY KEY AUTOINCREMENT,
 cluster_id INTEGER NOT NULL,
 decision TEXT NOT NULL,
 reviewer TEXT NOT NULL,
 reason TEXT NOT NULL,
 reviewed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_inference_calibrations(
 calibration_id INTEGER PRIMARY KEY AUTOINCREMENT,
 policy_version TEXT NOT NULL,
 reviewed_cluster_count INTEGER NOT NULL,
 confirmed_syndication_count INTEGER NOT NULL,
 confirmed_independent_count INTEGER NOT NULL,
 hold_count INTEGER NOT NULL,
 precision REAL,
 false_positive_rate REAL,
 baseline_text_threshold REAL NOT NULL,
 shadow_recommended_text_threshold REAL NOT NULL,
 threshold_delta REAL NOT NULL,
 recommendation_status TEXT NOT NULL,
 reasons_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_review_priorities(
 priority_id INTEGER PRIMARY KEY AUTOINCREMENT,
 cluster_id INTEGER NOT NULL,
 status TEXT NOT NULL,
 priority_score REAL NOT NULL,
 priority_band TEXT NOT NULL,
 event_status TEXT,
 member_count INTEGER NOT NULL,
 max_text_similarity REAL NOT NULL,
 same_poster_count INTEGER NOT NULL,
 same_link_origin_count INTEGER NOT NULL,
 route_impact_count INTEGER NOT NULL,
 likely_origin_source_id TEXT,
 reasons_json TEXT NOT NULL,
 calculated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_calibration_events(
 calibration_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
 calibration_id INTEGER NOT NULL,
 event_type TEXT NOT NULL,
 actor TEXT NOT NULL,
 detail_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_candidates(
 candidate_id INTEGER PRIMARY KEY AUTOINCREMENT,
 calibration_id INTEGER NOT NULL,
 baseline_threshold REAL NOT NULL,
 candidate_threshold REAL NOT NULL,
 direction TEXT NOT NULL,
 status TEXT NOT NULL,
 shadow_gate_status TEXT NOT NULL,
 decisive_review_count INTEGER NOT NULL,
 base_precision REAL,
 candidate_precision REAL,
 base_false_positive_rate REAL,
 candidate_false_positive_rate REAL,
 base_missed_syndication_count INTEGER NOT NULL,
 candidate_missed_syndication_count INTEGER NOT NULL,
 critical_missed_syndication_count INTEGER NOT NULL,
 reasons_json TEXT NOT NULL,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_reviews(
 threshold_review_id INTEGER PRIMARY KEY AUTOINCREMENT,
 candidate_id INTEGER NOT NULL,
 decision TEXT NOT NULL,
 reviewer TEXT NOT NULL,
 reason TEXT NOT NULL,
 reviewed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_canaries(
 canary_id INTEGER PRIMARY KEY AUTOINCREMENT,
 candidate_id INTEGER NOT NULL,
 status TEXT NOT NULL,
 max_assignments INTEGER NOT NULL,
 assigned_count INTEGER NOT NULL DEFAULT 0,
 confirmed_syndication_count INTEGER NOT NULL DEFAULT 0,
 confirmed_independent_count INTEGER NOT NULL DEFAULT 0,
 hold_count INTEGER NOT NULL DEFAULT 0,
 missed_syndication_count INTEGER NOT NULL DEFAULT 0,
 critical_missed_syndication_count INTEGER NOT NULL DEFAULT 0,
 rollback_reason TEXT,
 approved_by TEXT NOT NULL,
 started_at TEXT NOT NULL,
 completed_at TEXT,
 rolled_back_at TEXT
);
CREATE TABLE IF NOT EXISTS origin_threshold_canary_assignments(
 assignment_id INTEGER PRIMARY KEY AUTOINCREMENT,
 canary_id INTEGER NOT NULL,
 event_instance_id INTEGER NOT NULL,
 baseline_threshold REAL NOT NULL,
 candidate_threshold REAL NOT NULL,
 assigned_at TEXT NOT NULL,
 outcome TEXT,
 outcome_cluster_id INTEGER,
 outcome_at TEXT,
 UNIQUE(canary_id,event_instance_id)
);
CREATE TABLE IF NOT EXISTS origin_threshold_promotions(
 promotion_id INTEGER PRIMARY KEY AUTOINCREMENT,
 candidate_id INTEGER NOT NULL,
 canary_id INTEGER,
 status TEXT NOT NULL,
 production_threshold REAL NOT NULL,
 approved_by TEXT NOT NULL,
 reason TEXT NOT NULL,
 promoted_at TEXT NOT NULL,
 rolled_back_at TEXT,
 rollback_reason TEXT
);
CREATE TABLE IF NOT EXISTS origin_threshold_events(
 threshold_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
 candidate_id INTEGER,
 canary_id INTEGER,
 promotion_id INTEGER,
 event_type TEXT NOT NULL,
 actor TEXT NOT NULL,
 detail_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_runtime_observations(
 runtime_observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
 promotion_id INTEGER NOT NULL,
 event_instance_id INTEGER NOT NULL,
 cluster_id INTEGER,
 human_outcome TEXT NOT NULL,
 max_text_similarity REAL NOT NULL,
 event_status TEXT,
 critical INTEGER NOT NULL DEFAULT 0,
 base_threshold REAL NOT NULL,
 promoted_threshold REAL NOT NULL,
 base_predicted_syndication INTEGER NOT NULL,
 promoted_predicted_syndication INTEGER NOT NULL,
 base_correct INTEGER NOT NULL,
 promoted_correct INTEGER NOT NULL,
 counterfactual_class TEXT NOT NULL,
 observed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_runtime_evaluations(
 runtime_evaluation_id INTEGER PRIMARY KEY AUTOINCREMENT,
 promotion_id INTEGER NOT NULL,
 window_size INTEGER NOT NULL,
 observed_count INTEGER NOT NULL,
 promoted_true_positive INTEGER NOT NULL,
 promoted_false_positive INTEGER NOT NULL,
 promoted_missed_syndication INTEGER NOT NULL,
 promoted_true_negative INTEGER NOT NULL,
 promoted_precision REAL,
 promoted_false_positive_rate REAL,
 promoted_miss_rate REAL,
 base_false_positive_count INTEGER NOT NULL,
 base_missed_syndication_count INTEGER NOT NULL,
 promotion_regression_count INTEGER NOT NULL,
 promotion_improvement_count INTEGER NOT NULL,
 critical_regression_count INTEGER NOT NULL,
 status TEXT NOT NULL,
 reasons_json TEXT NOT NULL,
 evaluated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_recovery_cases(
 recovery_case_id INTEGER PRIMARY KEY AUTOINCREMENT,
 promotion_id INTEGER NOT NULL UNIQUE,
 candidate_id INTEGER NOT NULL,
 failed_threshold REAL NOT NULL,
 fallback_threshold REAL NOT NULL,
 status TEXT NOT NULL,
 rollback_reason TEXT NOT NULL,
 required_shadow_outcomes INTEGER NOT NULL,
 safe_shadow_outcome_count INTEGER NOT NULL DEFAULT 0,
 opened_at TEXT NOT NULL,
 ready_at TEXT,
 requalified_by TEXT,
 requalified_at TEXT,
 requalification_reason TEXT
);
CREATE TABLE IF NOT EXISTS origin_threshold_recovery_outcomes(
 recovery_outcome_id INTEGER PRIMARY KEY AUTOINCREMENT,
 recovery_case_id INTEGER NOT NULL,
 event_instance_id INTEGER NOT NULL,
 outcome TEXT NOT NULL,
 safe INTEGER NOT NULL,
 notes TEXT,
 observed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_runtime_events(
 runtime_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
 promotion_id INTEGER,
 recovery_case_id INTEGER,
 event_type TEXT NOT NULL,
 actor TEXT NOT NULL,
 detail_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_root_causes(
 root_cause_id INTEGER PRIMARY KEY AUTOINCREMENT,
 recovery_case_id INTEGER NOT NULL,
 promotion_id INTEGER NOT NULL,
 failure_class TEXT NOT NULL,
 root_cause_type TEXT NOT NULL,
 risk_band TEXT NOT NULL,
 dominant_source_id TEXT,
 dominant_platform TEXT,
 source_concentration REAL,
 boundary_distance REAL,
 repeated_root_cause_count INTEGER NOT NULL,
 evidence_json TEXT NOT NULL,
 reasons_json TEXT NOT NULL,
 attributed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_remediations(
 remediation_id INTEGER PRIMARY KEY AUTOINCREMENT,
 recovery_case_id INTEGER NOT NULL,
 root_cause_id INTEGER NOT NULL,
 remediation_type TEXT NOT NULL,
 remediation_ref TEXT,
 notes TEXT NOT NULL,
 submitted_by TEXT NOT NULL,
 submitted_at TEXT NOT NULL,
 status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_adaptive_requirements(
 requirement_id INTEGER PRIMARY KEY AUTOINCREMENT,
 recovery_case_id INTEGER NOT NULL,
 root_cause_id INTEGER NOT NULL,
 risk_band TEXT NOT NULL,
 required_safe_shadow_outcomes INTEGER NOT NULL,
 required_distinct_sources INTEGER NOT NULL,
 required_distinct_platforms INTEGER NOT NULL,
 require_remediation INTEGER NOT NULL,
 require_human_root_cause_review INTEGER NOT NULL,
 recurrence_penalty INTEGER NOT NULL,
 reasons_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_root_cause_reviews(
 root_cause_review_id INTEGER PRIMARY KEY AUTOINCREMENT,
 root_cause_id INTEGER NOT NULL,
 decision TEXT NOT NULL,
 reviewer TEXT NOT NULL,
 reason TEXT NOT NULL,
 reviewed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_recurrence_profiles(
 recurrence_profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
 signature TEXT NOT NULL UNIQUE,
 root_cause_type TEXT NOT NULL,
 dominant_source_id TEXT,
 dominant_platform TEXT,
 recurrence_count INTEGER NOT NULL,
 post_requalification_recurrence_count INTEGER NOT NULL,
 failed_effective_remediation_count INTEGER NOT NULL,
 risk_band TEXT NOT NULL,
 long_term_restricted INTEGER NOT NULL DEFAULT 0,
 reasons_json TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_recurrence_events(
 recurrence_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
 recurrence_profile_id INTEGER NOT NULL,
 recovery_case_id INTEGER NOT NULL,
 root_cause_id INTEGER NOT NULL,
 event_type TEXT NOT NULL,
 previous_recovery_case_id INTEGER,
 previous_remediation_id INTEGER,
 detail_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_remediation_effectiveness(
 effectiveness_id INTEGER PRIMARY KEY AUTOINCREMENT,
 remediation_id INTEGER NOT NULL,
 recovery_case_id INTEGER NOT NULL,
 root_cause_type TEXT NOT NULL,
 remediation_type TEXT NOT NULL,
 status TEXT NOT NULL,
 subsequent_recovery_case_id INTEGER,
 days_to_recurrence REAL,
 evidence_json TEXT NOT NULL,
 evaluated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_long_term_restrictions(
 restriction_id INTEGER PRIMARY KEY AUTOINCREMENT,
 recurrence_profile_id INTEGER NOT NULL,
 signature TEXT NOT NULL,
 status TEXT NOT NULL,
 trigger_recovery_case_id INTEGER NOT NULL,
 trigger_reason TEXT NOT NULL,
 recurrence_count INTEGER NOT NULL,
 failed_effective_remediation_count INTEGER NOT NULL,
 requires_human_exception INTEGER NOT NULL DEFAULT 1,
 started_at TEXT NOT NULL,
 released_at TEXT,
 released_by TEXT,
 release_reason TEXT
);
CREATE TABLE IF NOT EXISTS origin_threshold_restriction_exceptions(
 exception_id INTEGER PRIMARY KEY AUTOINCREMENT,
 restriction_id INTEGER NOT NULL,
 decision TEXT NOT NULL,
 approved_by TEXT NOT NULL,
 reason TEXT NOT NULL,
 created_at TEXT NOT NULL,
 consumed_at TEXT
);
CREATE TABLE IF NOT EXISTS origin_threshold_restriction_scopes(
 scope_id INTEGER PRIMARY KEY AUTOINCREMENT,
 restriction_id INTEGER NOT NULL,
 scope_type TEXT NOT NULL,
 source_id TEXT,
 platform TEXT,
 rule_key TEXT,
 status TEXT NOT NULL,
 production_action TEXT NOT NULL,
 shadow_learning_enabled INTEGER NOT NULL DEFAULT 1,
 reason TEXT NOT NULL,
 created_at TEXT NOT NULL,
 released_at TEXT,
 UNIQUE(restriction_id,scope_type,source_id,platform,rule_key)
);
CREATE TABLE IF NOT EXISTS origin_threshold_scope_route_evaluations(
 scope_route_id INTEGER PRIMARY KEY AUTOINCREMENT,
 event_instance_id INTEGER NOT NULL,
 rule_key TEXT NOT NULL,
 trigger_source_id TEXT,
 candidate_source_ids_json TEXT NOT NULL,
 blocked_source_ids_json TEXT NOT NULL,
 safe_source_ids_json TEXT NOT NULL,
 selected_source_ids_json TEXT NOT NULL,
 route_status TEXT NOT NULL,
 production_recommendation TEXT NOT NULL,
 coverage_preserved INTEGER NOT NULL,
 reasons_json TEXT NOT NULL,
 evaluated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_scope_events(
 scope_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
 scope_id INTEGER,
 scope_route_id INTEGER,
 event_type TEXT NOT NULL,
 actor TEXT NOT NULL,
 detail_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_scope_reintegration_evidence(
 evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
 scope_id INTEGER NOT NULL,
 event_instance_id INTEGER NOT NULL,
 outcome TEXT NOT NULL,
 human_confirmed INTEGER NOT NULL,
 alternative_quality_delta REAL,
 false_corroboration INTEGER NOT NULL DEFAULT 0,
 missed_syndication INTEGER NOT NULL DEFAULT 0,
 notes TEXT,
 observed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_scope_reintegration_evaluations(
 reintegration_evaluation_id INTEGER PRIMARY KEY AUTOINCREMENT,
 scope_id INTEGER NOT NULL,
 shadow_count INTEGER NOT NULL,
 decisive_human_count INTEGER NOT NULL,
 safe_human_count INTEGER NOT NULL,
 distinct_event_count INTEGER NOT NULL,
 false_corroboration_count INTEGER NOT NULL,
 missed_syndication_count INTEGER NOT NULL,
 avg_alternative_quality_delta REAL,
 elapsed_hours REAL NOT NULL,
 remediation_effective INTEGER NOT NULL,
 recurrence_risk_band TEXT NOT NULL,
 required_shadow_count INTEGER NOT NULL,
 required_human_count INTEGER NOT NULL,
 required_distinct_events INTEGER NOT NULL,
 status TEXT NOT NULL,
 reasons_json TEXT NOT NULL,
 evaluated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_scope_reintegration_reviews(
 review_id INTEGER PRIMARY KEY AUTOINCREMENT,
 scope_id INTEGER NOT NULL,
 reintegration_evaluation_id INTEGER NOT NULL,
 decision TEXT NOT NULL,
 reviewer TEXT NOT NULL,
 reason TEXT NOT NULL,
 reviewed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_scope_reintegration_canaries(
 canary_id INTEGER PRIMARY KEY AUTOINCREMENT,
 scope_id INTEGER NOT NULL,
 reintegration_evaluation_id INTEGER NOT NULL,
 status TEXT NOT NULL,
 max_assignments INTEGER NOT NULL,
 assigned_count INTEGER NOT NULL DEFAULT 0,
 safe_count INTEGER NOT NULL DEFAULT 0,
 unsafe_count INTEGER NOT NULL DEFAULT 0,
 hold_count INTEGER NOT NULL DEFAULT 0,
 approved_by TEXT NOT NULL,
 started_at TEXT NOT NULL,
 completed_at TEXT,
 rollback_reason TEXT
);
CREATE TABLE IF NOT EXISTS origin_threshold_scope_reintegration_assignments(
 assignment_id INTEGER PRIMARY KEY AUTOINCREMENT,
 canary_id INTEGER NOT NULL,
 event_instance_id INTEGER NOT NULL,
 assigned_at TEXT NOT NULL,
 outcome TEXT,
 human_confirmed INTEGER,
 false_corroboration INTEGER NOT NULL DEFAULT 0,
 missed_syndication INTEGER NOT NULL DEFAULT 0,
 outcome_at TEXT,
 UNIQUE(canary_id,event_instance_id)
);
CREATE TABLE IF NOT EXISTS origin_threshold_scope_reintegration_events(
 reintegration_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
 scope_id INTEGER NOT NULL,
 canary_id INTEGER,
 event_type TEXT NOT NULL,
 actor TEXT NOT NULL,
 detail_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_post_reintegration_observations(
 post_observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
 scope_id INTEGER NOT NULL,
 canary_id INTEGER NOT NULL,
 event_instance_id INTEGER NOT NULL,
 human_outcome TEXT NOT NULL,
 critical INTEGER NOT NULL DEFAULT 0,
 false_corroboration INTEGER NOT NULL DEFAULT 0,
 missed_syndication INTEGER NOT NULL DEFAULT 0,
 coverage_quality_delta REAL,
 reintegrated_correct INTEGER NOT NULL,
 base_correct INTEGER,
 alternative_correct INTEGER,
 counterfactual_class TEXT NOT NULL,
 observed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_post_reintegration_evaluations(
 post_evaluation_id INTEGER PRIMARY KEY AUTOINCREMENT,
 scope_id INTEGER NOT NULL,
 canary_id INTEGER NOT NULL,
 window_size INTEGER NOT NULL,
 sample_count INTEGER NOT NULL,
 regression_count INTEGER NOT NULL,
 false_corroboration_count INTEGER NOT NULL,
 missed_syndication_count INTEGER NOT NULL,
 critical_regression_count INTEGER NOT NULL,
 coverage_regression_count INTEGER NOT NULL,
 status TEXT NOT NULL,
 reasons_json TEXT NOT NULL,
 evaluated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_scope_reisolations(
 reisolation_id INTEGER PRIMARY KEY AUTOINCREMENT,
 scope_id INTEGER NOT NULL,
 canary_id INTEGER NOT NULL,
 trigger_post_observation_id INTEGER,
 trigger_post_evaluation_id INTEGER,
 status TEXT NOT NULL,
 reason TEXT NOT NULL,
 failure_count INTEGER NOT NULL,
 requirement_penalty_level INTEGER NOT NULL,
 reactivated_at TEXT NOT NULL,
 cleared_at TEXT,
 cleared_by TEXT,
 clear_reason TEXT
);
CREATE TABLE IF NOT EXISTS origin_threshold_post_reintegration_events(
 post_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
 scope_id INTEGER NOT NULL,
 canary_id INTEGER NOT NULL,
 event_type TEXT NOT NULL,
 actor TEXT NOT NULL,
 detail_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_post_reintegration_root_causes(
 post_root_cause_id INTEGER PRIMARY KEY AUTOINCREMENT,
 reisolation_id INTEGER NOT NULL UNIQUE,
 scope_id INTEGER NOT NULL,
 canary_id INTEGER NOT NULL,
 trigger_post_observation_id INTEGER,
 root_cause_type TEXT NOT NULL,
 secondary_root_cause_type TEXT,
 severity TEXT NOT NULL,
 evidence_json TEXT NOT NULL,
 reasons_json TEXT NOT NULL,
 attributed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_post_reintegration_remediation_routes(
 remediation_route_id INTEGER PRIMARY KEY AUTOINCREMENT,
 post_root_cause_id INTEGER NOT NULL,
 reisolation_id INTEGER NOT NULL,
 required_remediation_type TEXT NOT NULL,
 blocked_remediation_types_json TEXT NOT NULL,
 escalation_level INTEGER NOT NULL,
 architecture_review_required INTEGER NOT NULL DEFAULT 0,
 reason TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_post_reintegration_root_reviews(
 post_root_review_id INTEGER PRIMARY KEY AUTOINCREMENT,
 post_root_cause_id INTEGER NOT NULL,
 decision TEXT NOT NULL,
 reviewer TEXT NOT NULL,
 reason TEXT NOT NULL,
 reviewed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_post_reintegration_remediation_attempts(
 post_remediation_attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
 remediation_route_id INTEGER NOT NULL,
 remediation_id INTEGER NOT NULL,
 remediation_type TEXT NOT NULL,
 matched_required_type INTEGER NOT NULL,
 prior_same_type_failure_count INTEGER NOT NULL,
 accepted_for_gate INTEGER NOT NULL,
 reason TEXT NOT NULL,
 recorded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_architecture_remediation_plans(
 architecture_plan_id INTEGER PRIMARY KEY AUTOINCREMENT,
 scope_id INTEGER NOT NULL,
 reisolation_id INTEGER NOT NULL,
 remediation_route_id INTEGER NOT NULL,
 status TEXT NOT NULL,
 required_step_count INTEGER NOT NULL,
 created_by TEXT NOT NULL,
 rationale TEXT NOT NULL,
 created_at TEXT NOT NULL,
 approved_by TEXT,
 approved_at TEXT,
 approval_reason TEXT
);
CREATE TABLE IF NOT EXISTS origin_threshold_architecture_remediation_steps(
 architecture_step_id INTEGER PRIMARY KEY AUTOINCREMENT,
 architecture_plan_id INTEGER NOT NULL,
 step_order INTEGER NOT NULL,
 remediation_type TEXT NOT NULL,
 required INTEGER NOT NULL DEFAULT 1,
 status TEXT NOT NULL,
 remediation_id INTEGER,
 completed_by TEXT,
 completed_at TEXT,
 completion_reason TEXT,
 UNIQUE(architecture_plan_id,step_order)
);
CREATE TABLE IF NOT EXISTS origin_threshold_architecture_plan_reviews(
 architecture_review_id INTEGER PRIMARY KEY AUTOINCREMENT,
 architecture_plan_id INTEGER NOT NULL,
 decision TEXT NOT NULL,
 reviewer TEXT NOT NULL,
 reason TEXT NOT NULL,
 reviewed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_architecture_validation_evidence(
 architecture_evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
 architecture_plan_id INTEGER NOT NULL,
 event_instance_id INTEGER NOT NULL,
 outcome TEXT NOT NULL,
 human_confirmed INTEGER NOT NULL,
 false_corroboration INTEGER NOT NULL DEFAULT 0,
 missed_syndication INTEGER NOT NULL DEFAULT 0,
 quality_delta REAL,
 observed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_architecture_plan_evaluations(
 architecture_evaluation_id INTEGER PRIMARY KEY AUTOINCREMENT,
 architecture_plan_id INTEGER NOT NULL,
 completed_required_steps INTEGER NOT NULL,
 required_step_count INTEGER NOT NULL,
 shadow_count INTEGER NOT NULL,
 human_safe_count INTEGER NOT NULL,
 distinct_event_count INTEGER NOT NULL,
 false_corroboration_count INTEGER NOT NULL,
 missed_syndication_count INTEGER NOT NULL,
 avg_quality_delta REAL,
 status TEXT NOT NULL,
 reasons_json TEXT NOT NULL,
 evaluated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_architecture_plan_runtime_outcomes(
 architecture_runtime_outcome_id INTEGER PRIMARY KEY AUTOINCREMENT,
 architecture_plan_id INTEGER NOT NULL,
 scope_id INTEGER NOT NULL,
 canary_id INTEGER NOT NULL,
 root_cause_type TEXT NOT NULL,
 plan_signature TEXT NOT NULL,
 status TEXT NOT NULL,
 released_at TEXT NOT NULL,
 first_observed_at TEXT,
 last_observed_at TEXT,
 observation_count INTEGER NOT NULL DEFAULT 0,
 healthy_observation_count INTEGER NOT NULL DEFAULT 0,
 regression_observation_count INTEGER NOT NULL DEFAULT 0,
 reisolation_id INTEGER,
 reisolated_at TEXT,
 days_to_reisolation REAL,
 finalized_at TEXT,
 UNIQUE(architecture_plan_id,canary_id)
);
CREATE TABLE IF NOT EXISTS origin_threshold_architecture_plan_effectiveness_profiles(
 architecture_effectiveness_profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
 root_cause_type TEXT NOT NULL,
 plan_signature TEXT NOT NULL,
 attempt_count INTEGER NOT NULL,
 sustained_success_count INTEGER NOT NULL,
 recurrence_failure_count INTEGER NOT NULL,
 active_run_count INTEGER NOT NULL,
 success_rate REAL,
 avg_days_to_reisolation REAL,
 confidence_band TEXT NOT NULL,
 effectiveness_score REAL,
 reasons_json TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 UNIQUE(root_cause_type,plan_signature)
);
CREATE TABLE IF NOT EXISTS origin_threshold_architecture_plan_recommendations(
 architecture_recommendation_id INTEGER PRIMARY KEY AUTOINCREMENT,
 root_cause_type TEXT NOT NULL,
 blocked_types_json TEXT NOT NULL,
 recommended_signature TEXT NOT NULL,
 recommended_steps_json TEXT NOT NULL,
 source TEXT NOT NULL,
 confidence_band TEXT NOT NULL,
 evidence_attempt_count INTEGER NOT NULL,
 effectiveness_score REAL,
 reasons_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_architecture_runtime_contexts(
 architecture_runtime_context_id INTEGER PRIMARY KEY AUTOINCREMENT,
 architecture_runtime_outcome_id INTEGER NOT NULL UNIQUE,
 scope_type TEXT NOT NULL,
 source_id TEXT,
 platform TEXT,
 rule_key TEXT,
 secondary_root_cause_type TEXT,
 alternative_route_available INTEGER NOT NULL DEFAULT 0,
 plan_step_count INTEGER NOT NULL,
 context_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_architecture_comparative_scores(
 architecture_comparative_score_id INTEGER PRIMARY KEY AUTOINCREMENT,
 root_cause_type TEXT NOT NULL,
 plan_signature TEXT NOT NULL,
 context_signature TEXT NOT NULL,
 attempt_count INTEGER NOT NULL,
 decisive_count INTEGER NOT NULL,
 sustained_success_count INTEGER NOT NULL,
 recurrence_failure_count INTEGER NOT NULL,
 bayesian_success_rate REAL NOT NULL,
 wilson_lower_bound REAL NOT NULL,
 median_survival_days REAL,
 context_similarity REAL NOT NULL,
 evidence_factor REAL NOT NULL,
 complexity_penalty REAL NOT NULL,
 recurrence_severity_penalty REAL NOT NULL,
 comparative_score REAL NOT NULL,
 confidence_band TEXT NOT NULL,
 reasons_json TEXT NOT NULL,
 scored_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_architecture_context_recommendations(
 context_recommendation_id INTEGER PRIMARY KEY AUTOINCREMENT,
 root_cause_type TEXT NOT NULL,
 context_signature TEXT NOT NULL,
 blocked_types_json TEXT NOT NULL,
 selected_plan_signature TEXT NOT NULL,
 selected_steps_json TEXT NOT NULL,
 source TEXT NOT NULL,
 confidence_band TEXT NOT NULL,
 comparative_score REAL,
 runner_up_score REAL,
 score_margin REAL,
 evidence_attempt_count INTEGER NOT NULL,
 reasons_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_architecture_recommendation_challenges(
 challenge_id INTEGER PRIMARY KEY AUTOINCREMENT,
 scope_id INTEGER NOT NULL,
 root_cause_type TEXT NOT NULL,
 context_signature TEXT NOT NULL,
 recommendation_source TEXT NOT NULL,
 recommended_signature TEXT NOT NULL,
 recommended_steps_json TEXT NOT NULL,
 deterministic_signature TEXT NOT NULL,
 deterministic_steps_json TEXT NOT NULL,
 recommended_score REAL,
 deterministic_score REAL,
 status TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_architecture_challenge_shadow_outcomes(
 challenge_shadow_id INTEGER PRIMARY KEY AUTOINCREMENT,
 challenge_id INTEGER NOT NULL,
 event_instance_id INTEGER NOT NULL,
 recommended_outcome TEXT NOT NULL,
 deterministic_outcome TEXT NOT NULL,
 human_confirmed INTEGER NOT NULL,
 recommended_quality_delta REAL,
 deterministic_quality_delta REAL,
 observed_at TEXT NOT NULL,
 UNIQUE(challenge_id,event_instance_id)
);
CREATE TABLE IF NOT EXISTS origin_threshold_architecture_challenge_evaluations(
 challenge_evaluation_id INTEGER PRIMARY KEY AUTOINCREMENT,
 challenge_id INTEGER NOT NULL,
 decisive_count INTEGER NOT NULL,
 distinct_event_count INTEGER NOT NULL,
 recommended_win_count INTEGER NOT NULL,
 deterministic_win_count INTEGER NOT NULL,
 tie_count INTEGER NOT NULL,
 recommended_loss_count INTEGER NOT NULL,
 recommended_win_rate REAL,
 status TEXT NOT NULL,
 reasons_json TEXT NOT NULL,
 evaluated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_architecture_challenge_human_decisions(
 challenge_decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
 challenge_id INTEGER NOT NULL,
 decision TEXT NOT NULL,
 reviewer TEXT NOT NULL,
 reason TEXT NOT NULL,
 challenge_evaluation_id INTEGER,
 decided_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_architecture_challenge_runtime_results(
 challenge_runtime_result_id INTEGER PRIMARY KEY AUTOINCREMENT,
 challenge_id INTEGER NOT NULL UNIQUE,
 architecture_plan_id INTEGER,
 architecture_runtime_outcome_id INTEGER,
 human_decision TEXT NOT NULL,
 selected_signature TEXT NOT NULL,
 selected_side TEXT NOT NULL,
 runtime_status TEXT NOT NULL,
 counterfactual_verdict TEXT,
 days_to_reisolation REAL,
 finalized_at TEXT
);
CREATE TABLE IF NOT EXISTS origin_threshold_architecture_recommendation_quality_profiles(
 recommendation_quality_profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
 root_cause_type TEXT NOT NULL UNIQUE,
 challenge_count INTEGER NOT NULL,
 accepted_count INTEGER NOT NULL,
 baseline_selected_count INTEGER NOT NULL,
 hold_count INTEGER NOT NULL,
 runtime_decisive_count INTEGER NOT NULL,
 recommendation_helpful_count INTEGER NOT NULL,
 recommendation_harmful_count INTEGER NOT NULL,
 recommendation_neutral_count INTEGER NOT NULL,
 acceptance_rate REAL,
 helpful_rate REAL,
 harmful_rate REAL,
 confidence_band TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_policy_candidates(
 policy_candidate_id INTEGER PRIMARY KEY AUTOINCREMENT,
 root_cause_type TEXT NOT NULL,
 quality_profile_id INTEGER NOT NULL,
 runtime_decisive_count INTEGER NOT NULL,
 helpful_rate REAL NOT NULL,
 harmful_rate REAL NOT NULL,
 acceptance_rate REAL,
 baseline_selected_count INTEGER NOT NULL,
 status TEXT NOT NULL,
 reasons_json TEXT NOT NULL,
 evaluated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_policy_states(
 policy_state_id INTEGER PRIMARY KEY AUTOINCREMENT,
 root_cause_type TEXT NOT NULL UNIQUE,
 mode TEXT NOT NULL,
 candidate_id INTEGER,
 canary_max_assignments INTEGER NOT NULL DEFAULT 3,
 canary_assigned_count INTEGER NOT NULL DEFAULT 0,
 canary_helpful_count INTEGER NOT NULL DEFAULT 0,
 canary_harmful_count INTEGER NOT NULL DEFAULT 0,
 canary_neutral_count INTEGER NOT NULL DEFAULT 0,
 promoted_at TEXT,
 rolled_back_at TEXT,
 rollback_reason TEXT,
 updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_policy_reviews(
 policy_review_id INTEGER PRIMARY KEY AUTOINCREMENT,
 root_cause_type TEXT NOT NULL,
 candidate_id INTEGER,
 decision TEXT NOT NULL,
 reviewer TEXT NOT NULL,
 reason TEXT NOT NULL,
 reviewed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_policy_canary_assignments(
 policy_canary_assignment_id INTEGER PRIMARY KEY AUTOINCREMENT,
 root_cause_type TEXT NOT NULL,
 challenge_id INTEGER NOT NULL UNIQUE,
 assignment_number INTEGER NOT NULL,
 status TEXT NOT NULL,
 assigned_at TEXT NOT NULL,
 completed_at TEXT,
 verdict TEXT
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_policy_events(
 policy_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
 root_cause_type TEXT NOT NULL,
 event_type TEXT NOT NULL,
 actor TEXT NOT NULL,
 detail_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_policy_recovery_cases(
 policy_recovery_case_id INTEGER PRIMARY KEY AUTOINCREMENT,
 root_cause_type TEXT NOT NULL,
 rollback_number INTEGER NOT NULL,
 trigger_policy_event_id INTEGER,
 trigger_challenge_id INTEGER,
 failure_type TEXT NOT NULL,
 status TEXT NOT NULL,
 rollback_reason TEXT NOT NULL,
 opened_at TEXT NOT NULL,
 ready_at TEXT,
 requalified_at TEXT,
 UNIQUE(root_cause_type,rollback_number)
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_policy_recovery_remediations(
 policy_recovery_remediation_id INTEGER PRIMARY KEY AUTOINCREMENT,
 policy_recovery_case_id INTEGER NOT NULL,
 remediation_type TEXT NOT NULL,
 remediation_ref TEXT NOT NULL,
 status TEXT NOT NULL,
 submitted_by TEXT NOT NULL,
 notes TEXT NOT NULL,
 submitted_at TEXT NOT NULL,
 effective_by TEXT,
 effective_at TEXT
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_policy_recovery_evidence(
 policy_recovery_evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
 policy_recovery_case_id INTEGER NOT NULL,
 challenge_id INTEGER NOT NULL,
 verdict TEXT NOT NULL,
 human_confirmed INTEGER NOT NULL,
 notes TEXT NOT NULL,
 observed_at TEXT NOT NULL,
 UNIQUE(policy_recovery_case_id,challenge_id)
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_policy_recovery_evaluations(
 policy_recovery_evaluation_id INTEGER PRIMARY KEY AUTOINCREMENT,
 policy_recovery_case_id INTEGER NOT NULL,
 rollback_number INTEGER NOT NULL,
 decisive_count INTEGER NOT NULL,
 helpful_count INTEGER NOT NULL,
 harmful_count INTEGER NOT NULL,
 neutral_count INTEGER NOT NULL,
 distinct_challenge_count INTEGER NOT NULL,
 required_decisive_count INTEGER NOT NULL,
 required_helpful_count INTEGER NOT NULL,
 remediation_effective INTEGER NOT NULL,
 long_term_shadow_only INTEGER NOT NULL,
 architecture_review_required INTEGER NOT NULL,
 status TEXT NOT NULL,
 reasons_json TEXT NOT NULL,
 evaluated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_policy_recovery_reviews(
 policy_recovery_review_id INTEGER PRIMARY KEY AUTOINCREMENT,
 policy_recovery_case_id INTEGER NOT NULL,
 decision TEXT NOT NULL,
 reviewer TEXT NOT NULL,
 reason TEXT NOT NULL,
 reviewed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_policy_recovery_events(
 policy_recovery_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
 policy_recovery_case_id INTEGER NOT NULL,
 event_type TEXT NOT NULL,
 actor TEXT NOT NULL,
 detail_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_algorithm_versions(
 algorithm_version_id INTEGER PRIMARY KEY AUTOINCREMENT,
 root_cause_type TEXT NOT NULL,
 version_label TEXT NOT NULL,
 parent_algorithm_version_id INTEGER,
 fingerprint TEXT NOT NULL,
 code_ref TEXT,
 config_ref TEXT,
 status TEXT NOT NULL,
 created_by TEXT NOT NULL,
 notes TEXT NOT NULL,
 created_at TEXT NOT NULL,
 UNIQUE(root_cause_type,version_label),
 UNIQUE(root_cause_type,fingerprint)
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_algorithm_lineage(
 algorithm_lineage_id INTEGER PRIMARY KEY AUTOINCREMENT,
 algorithm_version_id INTEGER NOT NULL,
 root_cause_type TEXT NOT NULL,
 entity_type TEXT NOT NULL,
 entity_id INTEGER NOT NULL,
 relation_type TEXT NOT NULL,
 created_at TEXT NOT NULL,
 UNIQUE(entity_type,entity_id,relation_type)
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_recovery_version_links(
 recovery_version_link_id INTEGER PRIMARY KEY AUTOINCREMENT,
 policy_recovery_case_id INTEGER NOT NULL UNIQUE,
 failed_algorithm_version_id INTEGER NOT NULL,
 successor_algorithm_version_id INTEGER,
 policy_recovery_remediation_id INTEGER,
 status TEXT NOT NULL,
 approved_by TEXT,
 approved_at TEXT,
 reason TEXT,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_algorithm_version_events(
 algorithm_version_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
 algorithm_version_id INTEGER NOT NULL,
 event_type TEXT NOT NULL,
 actor TEXT NOT NULL,
 detail_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_algorithm_runtime_cohorts(
 algorithm_runtime_cohort_id INTEGER PRIMARY KEY AUTOINCREMENT,
 algorithm_version_id INTEGER NOT NULL,
 root_cause_type TEXT NOT NULL,
 challenge_id INTEGER NOT NULL,
 challenge_runtime_result_id INTEGER NOT NULL UNIQUE,
 architecture_runtime_outcome_id INTEGER,
 context_signature TEXT NOT NULL,
 runtime_phase TEXT NOT NULL,
 selected_side TEXT NOT NULL,
 runtime_status TEXT NOT NULL,
 counterfactual_verdict TEXT,
 days_to_reisolation REAL,
 started_at TEXT NOT NULL,
 finalized_at TEXT
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_algorithm_version_profiles(
 algorithm_version_profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
 algorithm_version_id INTEGER NOT NULL,
 root_cause_type TEXT NOT NULL,
 context_signature TEXT NOT NULL,
 total_runtime_count INTEGER NOT NULL,
 decisive_runtime_count INTEGER NOT NULL,
 canary_runtime_count INTEGER NOT NULL,
 production_runtime_count INTEGER NOT NULL,
 helpful_count INTEGER NOT NULL,
 harmful_count INTEGER NOT NULL,
 neutral_count INTEGER NOT NULL,
 rollback_count INTEGER NOT NULL,
 helpful_rate REAL,
 harmful_rate REAL,
 median_survival_days REAL,
 confidence_band TEXT NOT NULL,
 safety_band TEXT NOT NULL,
 promotion_memory_status TEXT NOT NULL,
 reasons_json TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 UNIQUE(algorithm_version_id,context_signature)
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_algorithm_version_evaluations(
 algorithm_version_evaluation_id INTEGER PRIMARY KEY AUTOINCREMENT,
 algorithm_version_id INTEGER NOT NULL,
 root_cause_type TEXT NOT NULL,
 context_signature TEXT NOT NULL,
 decisive_runtime_count INTEGER NOT NULL,
 canary_runtime_count INTEGER NOT NULL,
 production_runtime_count INTEGER NOT NULL,
 helpful_count INTEGER NOT NULL,
 harmful_count INTEGER NOT NULL,
 neutral_count INTEGER NOT NULL,
 helpful_rate REAL,
 harmful_rate REAL,
 median_survival_days REAL,
 status TEXT NOT NULL,
 reasons_json TEXT NOT NULL,
 evaluated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_version_promotion_gates(
 version_promotion_gate_id INTEGER PRIMARY KEY AUTOINCREMENT,
 algorithm_version_id INTEGER NOT NULL,
 root_cause_type TEXT NOT NULL,
 selected_context_signature TEXT,
 incumbent_algorithm_version_id INTEGER,
 candidate_score REAL,
 incumbent_score REAL,
 score_margin REAL,
 candidate_decisive_count INTEGER NOT NULL,
 candidate_canary_count INTEGER NOT NULL,
 candidate_helpful_count INTEGER NOT NULL,
 candidate_harmful_count INTEGER NOT NULL,
 status TEXT NOT NULL,
 supersede_allowed INTEGER NOT NULL,
 reasons_json TEXT NOT NULL,
 evaluated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_version_supersede_comparisons(
 supersede_comparison_id INTEGER PRIMARY KEY AUTOINCREMENT,
 candidate_algorithm_version_id INTEGER NOT NULL,
 incumbent_algorithm_version_id INTEGER NOT NULL,
 root_cause_type TEXT NOT NULL,
 context_signature TEXT NOT NULL,
 candidate_decisive_count INTEGER NOT NULL,
 incumbent_decisive_count INTEGER NOT NULL,
 candidate_wilson_lower REAL NOT NULL,
 incumbent_wilson_lower REAL NOT NULL,
 candidate_median_survival_days REAL,
 incumbent_median_survival_days REAL,
 candidate_score REAL NOT NULL,
 incumbent_score REAL NOT NULL,
 score_margin REAL NOT NULL,
 status TEXT NOT NULL,
 reasons_json TEXT NOT NULL,
 compared_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_version_promotion_reviews(
 version_promotion_review_id INTEGER PRIMARY KEY AUTOINCREMENT,
 algorithm_version_id INTEGER NOT NULL,
 version_promotion_gate_id INTEGER NOT NULL,
 decision TEXT NOT NULL,
 reviewer TEXT NOT NULL,
 reason TEXT NOT NULL,
 incumbent_algorithm_version_id INTEGER,
 reviewed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_version_promotion_events(
 version_promotion_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
 algorithm_version_id INTEGER NOT NULL,
 root_cause_type TEXT NOT NULL,
 event_type TEXT NOT NULL,
 actor TEXT NOT NULL,
 detail_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_supersede_runtime_guard_evaluations(
 supersede_runtime_guard_evaluation_id INTEGER PRIMARY KEY AUTOINCREMENT,
 failing_algorithm_version_id INTEGER NOT NULL,
 root_cause_type TEXT NOT NULL,
 context_signature TEXT,
 fallback_algorithm_version_id INTEGER,
 failing_verdict TEXT NOT NULL,
 fallback_decisive_count INTEGER NOT NULL,
 fallback_production_count INTEGER NOT NULL,
 fallback_helpful_count INTEGER NOT NULL,
 fallback_harmful_count INTEGER NOT NULL,
 fallback_median_survival_days REAL,
 fallback_safety_band TEXT,
 fallback_memory_status TEXT,
 status TEXT NOT NULL,
 action TEXT NOT NULL,
 reasons_json TEXT NOT NULL,
 evaluated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_version_fallbacks(
 version_fallback_id INTEGER PRIMARY KEY AUTOINCREMENT,
 root_cause_type TEXT NOT NULL,
 failing_algorithm_version_id INTEGER NOT NULL,
 fallback_algorithm_version_id INTEGER,
 trigger_challenge_id INTEGER,
 guard_evaluation_id INTEGER NOT NULL,
 action TEXT NOT NULL,
 status TEXT NOT NULL,
 recovery_case_id INTEGER,
 reason TEXT NOT NULL,
 executed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_supersede_runtime_guard_events(
 supersede_runtime_guard_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
 root_cause_type TEXT NOT NULL,
 failing_algorithm_version_id INTEGER NOT NULL,
 fallback_algorithm_version_id INTEGER,
 event_type TEXT NOT NULL,
 actor TEXT NOT NULL,
 detail_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_fallback_verification_generations(
 fallback_verification_generation_id INTEGER PRIMARY KEY AUTOINCREMENT,
 version_fallback_id INTEGER NOT NULL UNIQUE,
 root_cause_type TEXT NOT NULL,
 failing_algorithm_version_id INTEGER NOT NULL,
 fallback_algorithm_version_id INTEGER NOT NULL,
 pair_signature TEXT NOT NULL,
 status TEXT NOT NULL,
 max_observations INTEGER NOT NULL,
 observation_count INTEGER NOT NULL DEFAULT 0,
 helpful_count INTEGER NOT NULL DEFAULT 0,
 harmful_count INTEGER NOT NULL DEFAULT 0,
 neutral_count INTEGER NOT NULL DEFAULT 0,
 opened_at TEXT NOT NULL,
 completed_at TEXT
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_fallback_verification_observations(
 fallback_verification_observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
 fallback_verification_generation_id INTEGER NOT NULL,
 challenge_id INTEGER NOT NULL,
 verdict TEXT NOT NULL,
 observed_at TEXT NOT NULL,
 UNIQUE(fallback_verification_generation_id,challenge_id)
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_fallback_pair_profiles(
 fallback_pair_profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
 root_cause_type TEXT NOT NULL,
 pair_signature TEXT NOT NULL UNIQUE,
 failing_algorithm_version_id INTEGER NOT NULL,
 fallback_algorithm_version_id INTEGER NOT NULL,
 executed_fallback_count INTEGER NOT NULL,
 failed_verification_count INTEGER NOT NULL,
 stable_verification_count INTEGER NOT NULL,
 anti_ping_pong_blocked INTEGER NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_fallback_verification_events(
 fallback_verification_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
 fallback_verification_generation_id INTEGER NOT NULL,
 event_type TEXT NOT NULL,
 actor TEXT NOT NULL,
 detail_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_fallback_family_profiles(
 fallback_family_profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
 root_cause_type TEXT NOT NULL,
 family_root_algorithm_version_id INTEGER NOT NULL,
 fallback_target_algorithm_version_id INTEGER NOT NULL,
 family_signature TEXT NOT NULL UNIQUE,
 executed_fallback_count INTEGER NOT NULL,
 distinct_failing_version_count INTEGER NOT NULL,
 stable_verification_count INTEGER NOT NULL,
 watch_verification_count INTEGER NOT NULL,
 failed_verification_count INTEGER NOT NULL,
 circuit_state TEXT NOT NULL,
 architecture_review_required INTEGER NOT NULL,
 reasons_json TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_fallback_family_events(
 fallback_family_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
 fallback_family_profile_id INTEGER NOT NULL,
 event_type TEXT NOT NULL,
 actor TEXT NOT NULL,
 detail_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_fallback_family_reviews(
 fallback_family_review_id INTEGER PRIMARY KEY AUTOINCREMENT,
 fallback_family_profile_id INTEGER NOT NULL,
 decision TEXT NOT NULL,
 reviewer TEXT NOT NULL,
 reason TEXT NOT NULL,
 reviewed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_fallback_family_recovery_cases(
 family_recovery_case_id INTEGER PRIMARY KEY AUTOINCREMENT,
 fallback_family_profile_id INTEGER NOT NULL,
 root_cause_type TEXT NOT NULL,
 family_signature TEXT NOT NULL,
 recovery_number INTEGER NOT NULL,
 status TEXT NOT NULL,
 candidate_algorithm_version_id INTEGER,
 canary_max_fallbacks INTEGER NOT NULL DEFAULT 1,
 canary_used_fallbacks INTEGER NOT NULL DEFAULT 0,
 opened_at TEXT NOT NULL,
 ready_at TEXT,
 rearmed_at TEXT,
 stabilized_at TEXT,
 UNIQUE(fallback_family_profile_id,recovery_number)
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_fallback_family_recovery_remediations(
 family_recovery_remediation_id INTEGER PRIMARY KEY AUTOINCREMENT,
 family_recovery_case_id INTEGER NOT NULL,
 remediation_type TEXT NOT NULL,
 remediation_ref TEXT NOT NULL,
 status TEXT NOT NULL,
 submitted_by TEXT NOT NULL,
 notes TEXT NOT NULL,
 submitted_at TEXT NOT NULL,
 reviewed_by TEXT,
 reviewed_at TEXT,
 review_reason TEXT
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_fallback_family_recovery_evidence(
 family_recovery_evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
 family_recovery_case_id INTEGER NOT NULL,
 challenge_id INTEGER NOT NULL,
 candidate_algorithm_version_id INTEGER NOT NULL,
 verdict TEXT NOT NULL,
 human_confirmed INTEGER NOT NULL,
 notes TEXT NOT NULL,
 observed_at TEXT NOT NULL,
 UNIQUE(family_recovery_case_id,challenge_id)
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_fallback_family_recovery_evaluations(
 family_recovery_evaluation_id INTEGER PRIMARY KEY AUTOINCREMENT,
 family_recovery_case_id INTEGER NOT NULL,
 architecture_review_confirmed INTEGER NOT NULL,
 remediation_effective INTEGER NOT NULL,
 candidate_version_ready INTEGER NOT NULL,
 decisive_count INTEGER NOT NULL,
 helpful_count INTEGER NOT NULL,
 harmful_count INTEGER NOT NULL,
 neutral_count INTEGER NOT NULL,
 distinct_challenge_count INTEGER NOT NULL,
 status TEXT NOT NULL,
 reasons_json TEXT NOT NULL,
 evaluated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_fallback_family_recovery_reviews(
 family_recovery_review_id INTEGER PRIMARY KEY AUTOINCREMENT,
 family_recovery_case_id INTEGER NOT NULL,
 decision TEXT NOT NULL,
 reviewer TEXT NOT NULL,
 reason TEXT NOT NULL,
 reviewed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_fallback_family_recovery_events(
 family_recovery_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
 family_recovery_case_id INTEGER NOT NULL,
 event_type TEXT NOT NULL,
 actor TEXT NOT NULL,
 detail_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_fallback_family_generation_outcomes(
 family_generation_outcome_id INTEGER PRIMARY KEY AUTOINCREMENT,
 family_recovery_case_id INTEGER NOT NULL UNIQUE,
 fallback_family_profile_id INTEGER NOT NULL,
 root_cause_type TEXT NOT NULL,
 family_signature TEXT NOT NULL,
 candidate_algorithm_version_id INTEGER NOT NULL,
 family_recovery_remediation_id INTEGER,
 remediation_type TEXT,
 remediation_ref TEXT,
 status TEXT NOT NULL,
 stabilized_at TEXT NOT NULL,
 first_observed_at TEXT,
 last_observed_at TEXT,
 observation_count INTEGER NOT NULL DEFAULT 0,
 healthy_observation_count INTEGER NOT NULL DEFAULT 0,
 harmful_observation_count INTEGER NOT NULL DEFAULT 0,
 next_circuit_opened_at TEXT,
 days_to_family_recurrence REAL,
 finalized_at TEXT
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_fallback_family_remediation_effectiveness_profiles(
 family_remediation_effectiveness_profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
 family_signature TEXT NOT NULL,
 remediation_type TEXT NOT NULL,
 remediation_ref TEXT NOT NULL,
 attempt_count INTEGER NOT NULL,
 active_count INTEGER NOT NULL,
 sustained_success_count INTEGER NOT NULL,
 recurrence_failure_count INTEGER NOT NULL,
 success_rate REAL,
 avg_days_to_family_recurrence REAL,
 confidence_band TEXT NOT NULL,
 effectiveness_band TEXT NOT NULL,
 reasons_json TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 UNIQUE(family_signature,remediation_type,remediation_ref)
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_fallback_family_generation_events(
 family_generation_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
 family_generation_outcome_id INTEGER NOT NULL,
 event_type TEXT NOT NULL,
 actor TEXT NOT NULL,
 detail_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_fallback_family_remediation_rankings(
 family_remediation_ranking_id INTEGER PRIMARY KEY AUTOINCREMENT,
 family_recovery_case_id INTEGER NOT NULL,
 family_signature TEXT NOT NULL,
 historical_family_signature TEXT NOT NULL,
 remediation_type TEXT NOT NULL,
 remediation_ref TEXT NOT NULL,
 context_similarity REAL NOT NULL,
 attempt_count INTEGER NOT NULL,
 decisive_count INTEGER NOT NULL,
 sustained_success_count INTEGER NOT NULL,
 recurrence_failure_count INTEGER NOT NULL,
 wilson_lower_bound REAL NOT NULL,
 survival_score REAL NOT NULL,
 evidence_score REAL NOT NULL,
 recurrence_penalty REAL NOT NULL,
 conservative_score REAL NOT NULL,
 confidence_band TEXT NOT NULL,
 effectiveness_band TEXT NOT NULL,
 rank_state TEXT NOT NULL,
 rank_position INTEGER NOT NULL,
 reasons_json TEXT NOT NULL,
 ranked_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_fallback_family_remediation_recommendations(
 family_remediation_recommendation_id INTEGER PRIMARY KEY AUTOINCREMENT,
 family_recovery_case_id INTEGER NOT NULL,
 family_signature TEXT NOT NULL,
 selected_ranking_id INTEGER,
 source TEXT NOT NULL,
 status TEXT NOT NULL,
 recommended_remediation_type TEXT,
 recommended_remediation_ref TEXT,
 recommended_score REAL,
 score_margin REAL,
 human_selection_required INTEGER NOT NULL,
 reasons_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_fallback_family_remediation_selection_reviews(
 family_remediation_selection_review_id INTEGER PRIMARY KEY AUTOINCREMENT,
 family_recovery_case_id INTEGER NOT NULL,
 family_remediation_recommendation_id INTEGER NOT NULL,
 family_remediation_ranking_id INTEGER,
 decision TEXT NOT NULL,
 selected_remediation_type TEXT,
 selected_remediation_ref TEXT,
 reviewer TEXT NOT NULL,
 reason TEXT NOT NULL,
 reviewed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_fallback_family_remediation_ranking_events(
 family_remediation_ranking_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
 family_recovery_case_id INTEGER NOT NULL,
 event_type TEXT NOT NULL,
 actor TEXT NOT NULL,
 detail_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_fallback_family_recommendation_outcomes(
 family_recommendation_outcome_id INTEGER PRIMARY KEY AUTOINCREMENT,
 family_recovery_case_id INTEGER NOT NULL UNIQUE,
 family_signature TEXT NOT NULL,
 family_remediation_recommendation_id INTEGER,
 family_remediation_selection_review_id INTEGER,
 family_generation_outcome_id INTEGER NOT NULL UNIQUE,
 recommended_remediation_type TEXT,
 recommended_remediation_ref TEXT,
 recommended_score REAL,
 selected_remediation_type TEXT,
 selected_remediation_ref TEXT,
 selected_score REAL,
 recommendation_accepted INTEGER NOT NULL,
 human_override INTEGER NOT NULL,
 generation_status TEXT NOT NULL,
 outcome_class TEXT NOT NULL,
 selection_regret_score REAL NOT NULL DEFAULT 0,
 resolved_at TEXT,
 reasons_json TEXT NOT NULL,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_fallback_family_recommendation_effectiveness_profiles(
 family_recommendation_effectiveness_profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
 family_signature TEXT NOT NULL UNIQUE,
 recommendation_count INTEGER NOT NULL,
 human_selection_count INTEGER NOT NULL,
 acceptance_count INTEGER NOT NULL,
 override_count INTEGER NOT NULL,
 resolved_count INTEGER NOT NULL,
 recommendation_helpful_count INTEGER NOT NULL,
 recommendation_harmful_count INTEGER NOT NULL,
 override_success_count INTEGER NOT NULL,
 override_failure_count INTEGER NOT NULL,
 acceptance_rate REAL,
 recommendation_helpful_rate REAL,
 override_success_rate REAL,
 avg_selection_regret REAL,
 calibration_band TEXT NOT NULL,
 reasons_json TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS origin_threshold_recommendation_fallback_family_recommendation_outcome_events(
 family_recommendation_outcome_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
 family_recommendation_outcome_id INTEGER NOT NULL,
 event_type TEXT NOT NULL,
 actor TEXT NOT NULL,
 detail_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alternative_route_evaluations(
 route_evaluation_id INTEGER PRIMARY KEY AUTOINCREMENT,
 trigger_decision_id INTEGER,
 event_instance_id INTEGER NOT NULL,
 quarantined_source_id TEXT NOT NULL,
 rule_key TEXT NOT NULL,
 candidate_decision_ids_json TEXT NOT NULL,
 selected_decision_ids_json TEXT NOT NULL,
 independence_groups_json TEXT NOT NULL,
 human_confirmed_route INTEGER NOT NULL,
 safe_candidate_count INTEGER NOT NULL,
 independent_group_count INTEGER NOT NULL,
 route_status TEXT NOT NULL,
 production_recommendation TEXT NOT NULL,
 coverage_preserved INTEGER NOT NULL,
 reasons_json TEXT NOT NULL,
 evaluated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alternative_route_events(
 route_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
 route_evaluation_id INTEGER NOT NULL,
 event_type TEXT NOT NULL,
 actor TEXT NOT NULL,
 detail_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS verification_continuity_snapshots(
 continuity_snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
 source_id TEXT NOT NULL,
 rule_key TEXT NOT NULL,
 quarantined_decision_count INTEGER NOT NULL,
 routed_verified_count INTEGER NOT NULL,
 degraded_possible_count INTEGER NOT NULL,
 no_safe_route_count INTEGER NOT NULL,
 coverage_preservation_rate REAL,
 measured_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS preventive_quarantines(
 quarantine_id INTEGER PRIMARY KEY AUTOINCREMENT,
 source_id TEXT NOT NULL,
 rule_key TEXT NOT NULL,
 trigger_recovery_case_id INTEGER NOT NULL,
 status TEXT NOT NULL,
 trigger_reason TEXT NOT NULL,
 started_at TEXT NOT NULL,
 released_at TEXT,
 released_by TEXT,
 release_reason TEXT,
 metadata_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS preventive_quarantine_events(
 quarantine_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
 quarantine_id INTEGER NOT NULL,
 event_type TEXT NOT NULL,
 actor TEXT NOT NULL,
 detail_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS preventive_reintegration_evaluations(
 reintegration_evaluation_id INTEGER PRIMARY KEY AUTOINCREMENT,
 quarantine_id INTEGER NOT NULL,
 shadow_decision_count INTEGER NOT NULL,
 confirmed_outcome_count INTEGER NOT NULL,
 safe_outcome_count INTEGER NOT NULL,
 missed_critical_count INTEGER NOT NULL,
 false_hold_count INTEGER NOT NULL,
 false_hold_rate REAL,
 independent_alternative_count INTEGER NOT NULL,
 elapsed_hours REAL NOT NULL,
 recovery_requalified INTEGER NOT NULL,
 status TEXT NOT NULL,
 reasons_json TEXT NOT NULL,
 evaluated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS preventive_quarantine_release_reviews(
 release_review_id INTEGER PRIMARY KEY AUTOINCREMENT,
 quarantine_id INTEGER NOT NULL,
 decision TEXT NOT NULL,
 reviewer TEXT NOT NULL,
 reason TEXT NOT NULL,
 reintegration_evaluation_id INTEGER,
 reviewed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS preventive_recurrence_profiles(
 recurrence_profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
 source_id TEXT NOT NULL,
 rule_key TEXT NOT NULL,
 recurrence_count INTEGER NOT NULL,
 requalified_failure_count INTEGER NOT NULL,
 repeated_root_cause_count INTEGER NOT NULL,
 ineffective_remediation_count INTEGER NOT NULL,
 risk_band TEXT NOT NULL,
 long_term_restricted INTEGER NOT NULL DEFAULT 0,
 reasons_json TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 UNIQUE(source_id,rule_key)
);
CREATE TABLE IF NOT EXISTS preventive_recurrence_evaluations(
 recurrence_evaluation_id INTEGER PRIMARY KEY AUTOINCREMENT,
 recovery_case_id INTEGER NOT NULL,
 source_id TEXT NOT NULL,
 rule_key TEXT NOT NULL,
 recurrence_count INTEGER NOT NULL,
 repeated_root_cause INTEGER NOT NULL,
 previous_remediation_ref TEXT,
 remediation_effective TEXT NOT NULL,
 required_shadow_decisions INTEGER NOT NULL,
 required_confirmed_outcomes INTEGER NOT NULL,
 max_false_hold_rate REAL NOT NULL,
 human_exception_required INTEGER NOT NULL DEFAULT 0,
 risk_band TEXT NOT NULL,
 reasons_json TEXT NOT NULL,
 evaluated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS preventive_recurrence_exceptions(
 exception_id INTEGER PRIMARY KEY AUTOINCREMENT,
 recovery_case_id INTEGER NOT NULL,
 source_id TEXT NOT NULL,
 rule_key TEXT NOT NULL,
 decision TEXT NOT NULL,
 approved_by TEXT NOT NULL,
 reason TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS preventive_recovery_cases(
 recovery_case_id INTEGER PRIMARY KEY AUTOINCREMENT,
 source_id TEXT NOT NULL,
 rule_key TEXT NOT NULL,
 failed_promotion_id INTEGER NOT NULL,
 status TEXT NOT NULL,
 rollback_reason TEXT NOT NULL,
 root_cause TEXT,
 root_cause_by TEXT,
 root_cause_at TEXT,
 remediation_ref TEXT,
 remediation_notes TEXT,
 remediation_by TEXT,
 remediation_at TEXT,
 opened_at TEXT NOT NULL,
 ready_at TEXT,
 requalified_by TEXT,
 requalified_at TEXT,
 metadata_json TEXT NOT NULL,
 UNIQUE(failed_promotion_id)
);
CREATE TABLE IF NOT EXISTS preventive_recovery_evaluations(
 recovery_evaluation_id INTEGER PRIMARY KEY AUTOINCREMENT,
 recovery_case_id INTEGER NOT NULL,
 shadow_decision_count INTEGER NOT NULL,
 confirmed_outcome_count INTEGER NOT NULL,
 safe_outcome_count INTEGER NOT NULL,
 missed_critical_count INTEGER NOT NULL,
 false_conservative_hold_count INTEGER NOT NULL,
 false_conservative_hold_rate REAL,
 status TEXT NOT NULL,
 reasons_json TEXT NOT NULL,
 evaluated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS preventive_recovery_events(
 recovery_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
 recovery_case_id INTEGER NOT NULL,
 event_type TEXT NOT NULL,
 actor TEXT NOT NULL,
 detail_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS preventive_full_runtime_observations(
 runtime_observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
 promotion_id INTEGER NOT NULL,
 outcome_id INTEGER NOT NULL UNIQUE,
 decision_id INTEGER NOT NULL,
 outcome_class TEXT NOT NULL,
 missed_critical_failure INTEGER NOT NULL DEFAULT 0,
 false_conservative_hold INTEGER NOT NULL DEFAULT 0,
 critical_prevented INTEGER NOT NULL DEFAULT 0,
 observed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS preventive_full_runtime_guard_evaluations(
 guard_evaluation_id INTEGER PRIMARY KEY AUTOINCREMENT,
 promotion_id INTEGER NOT NULL,
 sample_count INTEGER NOT NULL,
 recent5_sample_count INTEGER NOT NULL,
 recent5_false_hold_rate REAL,
 recent10_sample_count INTEGER NOT NULL,
 recent10_false_hold_rate REAL,
 missed_critical_count INTEGER NOT NULL,
 prevented_critical_count INTEGER NOT NULL,
 status TEXT NOT NULL,
 action TEXT NOT NULL,
 reasons_json TEXT NOT NULL,
 evaluated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS preventive_full_runtime_guard_events(
 guard_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
 promotion_id INTEGER NOT NULL,
 event_type TEXT NOT NULL,
 outcome_id INTEGER,
 actor TEXT NOT NULL,
 detail_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS preventive_policy_outcomes(
 outcome_id INTEGER PRIMARY KEY AUTOINCREMENT,
 outcome_key TEXT NOT NULL UNIQUE,
 decision_id INTEGER NOT NULL,
 event_instance_id INTEGER,
 source_id TEXT NOT NULL,
 rule_key TEXT NOT NULL,
 policy_mode TEXT NOT NULL,
 base_action TEXT NOT NULL,
 preventive_action TEXT NOT NULL,
 event_truth TEXT NOT NULL,
 outcome_class TEXT NOT NULL,
 critical_prevented INTEGER NOT NULL DEFAULT 0,
 false_conservative_hold INTEGER NOT NULL DEFAULT 0,
 confirmed_by TEXT NOT NULL,
 rationale_json TEXT NOT NULL,
 observed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS preventive_canary_safety_evaluations(
 evaluation_id INTEGER PRIMARY KEY AUTOINCREMENT,
 canary_id INTEGER NOT NULL,
 sample_count INTEGER NOT NULL,
 prevented_critical_count INTEGER NOT NULL,
 false_conservative_hold_count INTEGER NOT NULL,
 false_conservative_hold_rate REAL,
 status TEXT NOT NULL,
 reasons_json TEXT NOT NULL,
 evaluated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS preventive_full_promotions(
 promotion_id INTEGER PRIMARY KEY AUTOINCREMENT,
 source_id TEXT NOT NULL,
 rule_key TEXT NOT NULL,
 canary_id INTEGER NOT NULL,
 status TEXT NOT NULL,
 promoted_by TEXT NOT NULL,
 promoted_at TEXT NOT NULL,
 ended_at TEXT,
 rollback_reason TEXT,
 metadata_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS preventive_final_reviews(
 final_review_id INTEGER PRIMARY KEY AUTOINCREMENT,
 canary_id INTEGER NOT NULL,
 decision TEXT NOT NULL,
 reviewer TEXT NOT NULL,
 reason TEXT,
 promotion_id INTEGER,
 reviewed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS preventive_policy_canary_events(
 canary_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
 canary_id INTEGER NOT NULL,
 event_type TEXT NOT NULL,
 decision_id INTEGER,
 actor TEXT NOT NULL,
 detail_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS decision_evidence_clusters(
 cluster_id INTEGER PRIMARY KEY AUTOINCREMENT,
 cluster_key TEXT NOT NULL UNIQUE,
 event_instance_id INTEGER,
 goal_profile TEXT NOT NULL,
 proposed_event_truth TEXT NOT NULL,
 critical_error_type TEXT,
 status TEXT NOT NULL,
 severity TEXT NOT NULL,
 evidence_count INTEGER NOT NULL DEFAULT 0,
 independent_source_count INTEGER NOT NULL DEFAULT 0,
 confirmed_count INTEGER NOT NULL DEFAULT 0,
 rejected_count INTEGER NOT NULL DEFAULT 0,
 resolution_confidence TEXT NOT NULL,
 resolved_outcome TEXT,
 resolved_by TEXT,
 resolved_at TEXT,
 closure_status TEXT NOT NULL DEFAULT 'OPEN',
 root_cause_status TEXT NOT NULL DEFAULT 'UNATTRIBUTED',
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS decision_evidence_cluster_links(
 link_id INTEGER PRIMARY KEY AUTOINCREMENT,
 cluster_id INTEGER NOT NULL,
 evidence_id INTEGER NOT NULL UNIQUE,
 linked_at TEXT NOT NULL,
 FOREIGN KEY(cluster_id) REFERENCES decision_evidence_clusters(cluster_id),
 FOREIGN KEY(evidence_id) REFERENCES decision_outcome_evidence(evidence_id)
);
CREATE TABLE IF NOT EXISTS root_cause_attributions(
 attribution_id INTEGER PRIMARY KEY AUTOINCREMENT,
 cluster_id INTEGER NOT NULL,
 category TEXT NOT NULL,
 component TEXT,
 source_kind TEXT,
 source_id TEXT,
 rule_key TEXT,
 confidence TEXT NOT NULL,
 status TEXT NOT NULL,
 rationale_json TEXT NOT NULL,
 backlog_id INTEGER,
 attributed_by TEXT NOT NULL,
 attributed_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 UNIQUE(cluster_id,category,component,source_kind,source_id,rule_key),
 FOREIGN KEY(cluster_id) REFERENCES decision_evidence_clusters(cluster_id)
);
CREATE TABLE IF NOT EXISTS cluster_closure_checks(
 closure_check_id INTEGER PRIMARY KEY AUTOINCREMENT,
 cluster_id INTEGER NOT NULL,
 status TEXT NOT NULL,
 unresolved_critical_evidence INTEGER NOT NULL,
 open_backlog_count INTEGER NOT NULL,
 verified_backlog_count INTEGER NOT NULL,
 reasons_json TEXT NOT NULL,
 checked_by TEXT NOT NULL,
 checked_at TEXT NOT NULL,
 FOREIGN KEY(cluster_id) REFERENCES decision_evidence_clusters(cluster_id)
);
CREATE TABLE IF NOT EXISTS decision_evidence_priority_state(
 evidence_id INTEGER PRIMARY KEY,
 priority TEXT NOT NULL,
 priority_score INTEGER NOT NULL,
 sla_due_at TEXT,
 overdue INTEGER NOT NULL DEFAULT 0,
 independent_source_count INTEGER NOT NULL DEFAULT 1,
 corroboration_count INTEGER NOT NULL DEFAULT 0,
 resolution_confidence TEXT NOT NULL,
 expires_at TEXT,
 auto_resolution_eligible INTEGER NOT NULL DEFAULT 0,
 cluster_key TEXT,
 reasons_json TEXT NOT NULL,
 last_evaluated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS decision_evidence_queue_events(
 queue_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
 evidence_id INTEGER NOT NULL,
 event_type TEXT NOT NULL,
 actor TEXT NOT NULL,
 detail_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS decision_outcome_evidence(
 evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
 evidence_key TEXT NOT NULL UNIQUE,
 event_instance_id INTEGER,
 change_id INTEGER,
 goal_profile TEXT NOT NULL,
 evidence_type TEXT NOT NULL,
 proposed_outcome TEXT NOT NULL,
 proposed_event_truth TEXT NOT NULL,
 proposed_critical_error_type TEXT,
 source_kind TEXT NOT NULL,
 source_ref TEXT,
 confidence TEXT NOT NULL,
 status TEXT NOT NULL,
 user_impact REAL NOT NULL,
 core_relevance REAL NOT NULL,
 evidence_json TEXT NOT NULL,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS decision_outcome_confirmations(
 confirmation_id INTEGER PRIMARY KEY AUTOINCREMENT,
 evidence_id INTEGER NOT NULL,
 decision TEXT NOT NULL,
 reviewer TEXT NOT NULL,
 reason TEXT,
 decision_quality_observation_id INTEGER,
 metadata_json TEXT NOT NULL,
 confirmed_at TEXT NOT NULL,
 FOREIGN KEY(evidence_id) REFERENCES decision_outcome_evidence(evidence_id)
);
CREATE TABLE IF NOT EXISTS decision_quality_observations(
 decision_observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
 change_id INTEGER,
 event_id INTEGER,
 goal_profile TEXT NOT NULL,
 decision_outcome TEXT NOT NULL,
 event_truth TEXT NOT NULL,
 decision_action TEXT,
 source_confidence TEXT,
 critical_error_type TEXT,
 core_relevance REAL NOT NULL,
 user_impact REAL NOT NULL,
 successful_decision INTEGER NOT NULL,
 failed_decision INTEGER NOT NULL,
 metadata_json TEXT NOT NULL,
 observed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS goal_relevance_diagnostics(
 diagnostic_id INTEGER PRIMARY KEY AUTOINCREMENT,
 goal_profile TEXT NOT NULL,
 scope_key TEXT NOT NULL,
 sample_count INTEGER NOT NULL,
 core_relevance_rate REAL,
 successful_decision_rate REAL,
 failed_decision_rate REAL,
 critical_error_count INTEGER NOT NULL,
 false_verified_count INTEGER NOT NULL,
 cancellation_miss_count INTEGER NOT NULL,
 support_only_count INTEGER NOT NULL,
 status TEXT NOT NULL,
 reasons_json TEXT NOT NULL,
 evaluated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS post_promotion_runtime_observations(
 observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
 promotion_id INTEGER NOT NULL,
 change_id INTEGER NOT NULL,
 goal_profile TEXT NOT NULL,
 base_verdict TEXT NOT NULL,
 full_verdict TEXT NOT NULL,
 base_weighted_score REAL,
 full_weighted_score REAL,
 diverged INTEGER NOT NULL,
 false_optimism INTEGER NOT NULL,
 created_at TEXT NOT NULL,
 UNIQUE(promotion_id,change_id),
 FOREIGN KEY(promotion_id) REFERENCES adaptive_full_promotions(promotion_id)
);
CREATE TABLE IF NOT EXISTS post_promotion_guard_evaluations(
 guard_id INTEGER PRIMARY KEY AUTOINCREMENT,
 promotion_id INTEGER NOT NULL,
 goal_profile TEXT NOT NULL,
 policy_version TEXT NOT NULL,
 status TEXT NOT NULL,
 sample_count INTEGER NOT NULL,
 recent7_count INTEGER NOT NULL,
 recent7_divergence_rate REAL,
 recent14_count INTEGER NOT NULL,
 recent14_divergence_rate REAL,
 false_optimism_count INTEGER NOT NULL DEFAULT 0,
 canary_divergence_rate REAL,
 drift_from_canary REAL,
 stable_full INTEGER NOT NULL DEFAULT 0,
 reasons_json TEXT NOT NULL,
 evaluated_at TEXT NOT NULL,
 FOREIGN KEY(promotion_id) REFERENCES adaptive_full_promotions(promotion_id)
);
CREATE TABLE IF NOT EXISTS adaptive_full_promotions(
 promotion_id INTEGER PRIMARY KEY AUTOINCREMENT,
 lease_id INTEGER NOT NULL,
 candidate_id INTEGER NOT NULL,
 goal_profile TEXT NOT NULL,
 policy_version TEXT NOT NULL,
 status TEXT NOT NULL,
 adaptive_weights_json TEXT NOT NULL,
 base_weights_json TEXT NOT NULL,
 promoted_by TEXT NOT NULL,
 promoted_at TEXT NOT NULL,
 ended_at TEXT,
 rollback_reason TEXT,
 metadata_json TEXT NOT NULL,
 FOREIGN KEY(lease_id) REFERENCES adaptive_promotion_leases(lease_id)
);
CREATE TABLE IF NOT EXISTS adaptive_promotion_reviews(
 review_id INTEGER PRIMARY KEY AUTOINCREMENT,
 candidate_id INTEGER NOT NULL,
 decision TEXT NOT NULL,
 reviewer TEXT NOT NULL,
 reason TEXT,
 reviewed_at TEXT NOT NULL,
 metadata_json TEXT NOT NULL,
 FOREIGN KEY(candidate_id) REFERENCES adaptive_promotion_candidates(candidate_id)
);
CREATE TABLE IF NOT EXISTS adaptive_promotion_leases(
 lease_id INTEGER PRIMARY KEY AUTOINCREMENT,
 candidate_id INTEGER NOT NULL,
 goal_profile TEXT NOT NULL,
 policy_version TEXT NOT NULL,
 status TEXT NOT NULL,
 mode TEXT NOT NULL,
 max_canary_changes INTEGER NOT NULL,
 used_canary_changes INTEGER NOT NULL DEFAULT 0,
 adaptive_weights_json TEXT NOT NULL,
 base_weights_json TEXT NOT NULL,
 approved_by TEXT NOT NULL,
 approved_at TEXT NOT NULL,
 started_at TEXT NOT NULL,
 ended_at TEXT,
 rollback_reason TEXT,
 metadata_json TEXT NOT NULL,
 FOREIGN KEY(candidate_id) REFERENCES adaptive_promotion_candidates(candidate_id)
);
CREATE TABLE IF NOT EXISTS adaptive_promotion_lease_events(
 event_id INTEGER PRIMARY KEY AUTOINCREMENT,
 lease_id INTEGER NOT NULL,
 event_type TEXT NOT NULL,
 change_id INTEGER,
 actor TEXT NOT NULL,
 detail_json TEXT NOT NULL,
 created_at TEXT NOT NULL,
 FOREIGN KEY(lease_id) REFERENCES adaptive_promotion_leases(lease_id)
);
CREATE TABLE IF NOT EXISTS rolling_shadow_stability_evaluations(
 rolling_id INTEGER PRIMARY KEY AUTOINCREMENT,
 goal_profile TEXT,
 scope_key TEXT NOT NULL,
 policy_version TEXT NOT NULL,
 status TEXT NOT NULL,
 cumulative_status TEXT NOT NULL,
 total_samples INTEGER NOT NULL,
 downgrade_detected INTEGER NOT NULL DEFAULT 0,
 previous_status TEXT,
 windows_json TEXT NOT NULL,
 reasons_json TEXT NOT NULL,
 evaluated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS adaptive_promotion_candidates(
 candidate_id INTEGER PRIMARY KEY AUTOINCREMENT,
 goal_profile TEXT,
 scope_key TEXT NOT NULL,
 policy_version TEXT NOT NULL,
 status TEXT NOT NULL,
 rolling_id INTEGER,
 total_samples INTEGER NOT NULL,
 agreement_rate REAL,
 unsafe_improved INTEGER NOT NULL DEFAULT 0,
 criteria_json TEXT NOT NULL,
 reasons_json TEXT NOT NULL,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shadow_safety_evaluations(
 safety_id INTEGER PRIMARY KEY AUTOINCREMENT,
 goal_profile TEXT,
 scope_key TEXT NOT NULL,
 policy_version TEXT NOT NULL,
 status TEXT NOT NULL,
 total INTEGER NOT NULL,
 agreements INTEGER NOT NULL,
 disagreements INTEGER NOT NULL,
 agreement_rate REAL,
 critical_false_improved INTEGER NOT NULL DEFAULT 0,
 unsafe_improved INTEGER NOT NULL DEFAULT 0,
 conservative_false_regressed INTEGER NOT NULL DEFAULT 0,
 confusion_matrix_json TEXT NOT NULL,
 reasons_json TEXT NOT NULL,
 evaluated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS adaptive_shadow_verdicts(
 shadow_id INTEGER PRIMARY KEY AUTOINCREMENT,
 change_id INTEGER NOT NULL,
 baseline_daily_run_id TEXT,
 post_daily_run_id TEXT,
 goal_profile TEXT NOT NULL,
 base_verdict TEXT NOT NULL,
 shadow_verdict TEXT NOT NULL,
 base_weighted_score REAL,
 shadow_weighted_score REAL,
 agrees INTEGER NOT NULL,
 adaptive_sample_count INTEGER DEFAULT 0,
 base_weights_json TEXT NOT NULL,
 shadow_weights_json TEXT NOT NULL,
 reasons_json TEXT,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS improvement_changes(
 change_id INTEGER PRIMARY KEY AUTOINCREMENT,
 change_uuid TEXT NOT NULL UNIQUE,
 backlog_id INTEGER,
 title TEXT NOT NULL,
 description TEXT,
 component TEXT,
 version_label TEXT,
 actor TEXT NOT NULL,
 applied_at TEXT NOT NULL,
 metadata_json TEXT,
 FOREIGN KEY(backlog_id) REFERENCES improvement_backlog_items(backlog_id)
);
CREATE TABLE IF NOT EXISTS change_daily_run_links(
 link_id INTEGER PRIMARY KEY AUTOINCREMENT,
 change_id INTEGER NOT NULL,
 daily_run_id TEXT NOT NULL,
 relation TEXT NOT NULL,
 linked_at TEXT NOT NULL,
 FOREIGN KEY(change_id) REFERENCES improvement_changes(change_id),
 FOREIGN KEY(daily_run_id) REFERENCES daily_runs(daily_run_id)
);
CREATE TABLE IF NOT EXISTS improvement_changes_metric_effects(
 effect_id INTEGER PRIMARY KEY AUTOINCREMENT,
 change_id INTEGER NOT NULL,
 daily_run_id TEXT NOT NULL,
 measured_at TEXT NOT NULL,
 correction_rate REAL,
 access_failure_rate REAL,
 field_coverage_rate REAL,
 known_field_rate REAL,
 source_yield_rate REAL,
 recovery_success_rate REAL,
 baseline_daily_run_id TEXT,
 metadata_json TEXT,
 FOREIGN KEY(change_id) REFERENCES improvement_changes(change_id)
);
CREATE TABLE IF NOT EXISTS adaptive_weight_observations(
 observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
 goal_profile TEXT NOT NULL,
 metric_name TEXT NOT NULL,
 change_id INTEGER,
 verdict TEXT,
 delta REAL,
 direction_score REAL,
 evidence_strength REAL DEFAULT 1.0,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS adaptive_weight_profiles(
 profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
 goal_profile TEXT NOT NULL UNIQUE,
 base_weights_json TEXT NOT NULL,
 adaptive_weights_json TEXT NOT NULL,
 sample_count INTEGER DEFAULT 0,
 last_recomputed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS improvement_backlog_items(
 backlog_id INTEGER PRIMARY KEY AUTOINCREMENT,
 backlog_uuid TEXT NOT NULL UNIQUE,
 source_id TEXT,
 field_name TEXT,
 title TEXT NOT NULL,
 priority TEXT NOT NULL,
 sample_confidence TEXT NOT NULL,
 hotspot_score INTEGER DEFAULT 0,
 goal_profile TEXT,
 goal_weights_json TEXT,
 status TEXT NOT NULL DEFAULT 'OPEN',
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 opened_by TEXT,
 owner TEXT,
 rejection_reason TEXT,
 metadata_json TEXT
);
CREATE TABLE IF NOT EXISTS improvement_backlog_history(
 history_id INTEGER PRIMARY KEY AUTOINCREMENT,
 backlog_id INTEGER NOT NULL,
 from_status TEXT,
 to_status TEXT NOT NULL,
 actor TEXT NOT NULL,
 note TEXT,
 created_at TEXT NOT NULL,
 FOREIGN KEY(backlog_id) REFERENCES improvement_backlog_items(backlog_id)
);
CREATE TABLE IF NOT EXISTS improvement_effect_snapshots(
 snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
 backlog_id INTEGER NOT NULL,
 phase TEXT NOT NULL,
 captured_at TEXT NOT NULL,
 review_count INTEGER DEFAULT 0,
 correction_rate REAL,
 access_failure_rate REAL,
 field_coverage_rate REAL,
 known_field_rate REAL,
 source_yield_rate REAL,
 recovery_success_rate REAL,
 metadata_json TEXT,
 FOREIGN KEY(backlog_id) REFERENCES improvement_backlog_items(backlog_id)
);
CREATE TABLE IF NOT EXISTS human_review_actions(
 action_id INTEGER PRIMARY KEY AUTOINCREMENT,
 action_uuid TEXT NOT NULL UNIQUE,
 review_type TEXT NOT NULL,
 target_id INTEGER,
 event_instance_id INTEGER,
 field_name TEXT,
 recovery_id INTEGER,
 action TEXT NOT NULL,
 actor TEXT NOT NULL,
 reason TEXT,
 old_value_json TEXT,
 new_value_json TEXT,
 evidence_json TEXT,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS human_review_state(
 review_key TEXT PRIMARY KEY,
 review_type TEXT NOT NULL,
 target_id INTEGER,
 event_instance_id INTEGER,
 field_name TEXT,
 recovery_id INTEGER,
 state TEXT NOT NULL,
 last_action_id INTEGER,
 updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS daily_metric_snapshots(
 snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
 daily_run_id TEXT NOT NULL UNIQUE,
 run_date TEXT NOT NULL,
 captured_at TEXT NOT NULL,
 payload_json TEXT NOT NULL,
 event_confidence_json TEXT,
 field_confidence_json TEXT,
 source_metrics_json TEXT,
 human_review_metrics_json TEXT,
 hotspot_json TEXT,
 backlog_json TEXT,
 p0_count INTEGER DEFAULT 0,
 health TEXT,
 immutable_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS daily_runs(
 daily_run_id TEXT PRIMARY KEY, run_date TEXT NOT NULL, mode TEXT NOT NULL,
 started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL,
 root_lineage_id TEXT, discovery_lineage_count INTEGER DEFAULT 0,
 acquisition_run_count INTEGER DEFAULT 0, recovery_run_count INTEGER DEFAULT 0,
 metric_status TEXT, report_status TEXT, summary_json TEXT
);
CREATE TABLE IF NOT EXISTS daily_run_lineages(
 link_id INTEGER PRIMARY KEY AUTOINCREMENT, daily_run_id TEXT NOT NULL,
 lineage_id TEXT NOT NULL, role TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS observation_lineages(
 lineage_id TEXT PRIMARY KEY,
 root_run_type TEXT NOT NULL,
 root_source_id TEXT,
 root_query TEXT,
 root_url TEXT,
 created_at TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'ACTIVE',
 final_event_instance_id INTEGER,
 metadata_json TEXT
);
CREATE TABLE IF NOT EXISTS observation_run_links(
 link_id INTEGER PRIMARY KEY AUTOINCREMENT,
 lineage_id TEXT NOT NULL,
 observation_id INTEGER NOT NULL,
 parent_observation_id INTEGER,
 stage TEXT NOT NULL,
 created_at TEXT NOT NULL,
 FOREIGN KEY(lineage_id) REFERENCES observation_lineages(lineage_id),
 FOREIGN KEY(observation_id) REFERENCES observation_runs(observation_id),
 FOREIGN KEY(parent_observation_id) REFERENCES observation_runs(observation_id)
);
CREATE TABLE IF NOT EXISTS observation_post_links(
 link_id INTEGER PRIMARY KEY AUTOINCREMENT,
 lineage_id TEXT NOT NULL,
 observation_id INTEGER,
 post_id INTEGER NOT NULL,
 source_id TEXT,
 role TEXT NOT NULL,
 created_at TEXT NOT NULL,
 FOREIGN KEY(lineage_id) REFERENCES observation_lineages(lineage_id),
 FOREIGN KEY(observation_id) REFERENCES observation_runs(observation_id),
 FOREIGN KEY(post_id) REFERENCES raw_posts(post_id)
);
CREATE TABLE IF NOT EXISTS observation_event_links(
 link_id INTEGER PRIMARY KEY AUTOINCREMENT,
 lineage_id TEXT NOT NULL,
 observation_id INTEGER,
 event_instance_id INTEGER NOT NULL,
 role TEXT NOT NULL,
 created_at TEXT NOT NULL,
 FOREIGN KEY(lineage_id) REFERENCES observation_lineages(lineage_id),
 FOREIGN KEY(observation_id) REFERENCES observation_runs(observation_id),
 FOREIGN KEY(event_instance_id) REFERENCES event_instances(event_instance_id)
);
CREATE TABLE IF NOT EXISTS change_effect_verdicts(
 verdict_id INTEGER PRIMARY KEY AUTOINCREMENT,
 change_id INTEGER NOT NULL,
 baseline_daily_run_id TEXT,
 post_daily_run_id TEXT,
 verdict TEXT NOT NULL,
 comparable_metric_count INTEGER DEFAULT 0,
 improved_metric_count INTEGER DEFAULT 0,
 regressed_metric_count INTEGER DEFAULT 0,
 unchanged_metric_count INTEGER DEFAULT 0,
 score REAL,
 weighted_score REAL,
 goal_profile TEXT,
 metric_weights_json TEXT,
 improved_metrics_json TEXT,
 regressed_metrics_json TEXT,
 unchanged_metrics_json TEXT,
 reasons_json TEXT,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS improvement_changes(
 change_id INTEGER PRIMARY KEY AUTOINCREMENT,
 change_uuid TEXT NOT NULL UNIQUE,
 backlog_id INTEGER,
 title TEXT NOT NULL,
 description TEXT,
 component TEXT,
 version_label TEXT,
 actor TEXT NOT NULL,
 applied_at TEXT NOT NULL,
 metadata_json TEXT,
 FOREIGN KEY(backlog_id) REFERENCES improvement_backlog_items(backlog_id)
);
CREATE TABLE IF NOT EXISTS change_daily_run_links(
 link_id INTEGER PRIMARY KEY AUTOINCREMENT,
 change_id INTEGER NOT NULL,
 daily_run_id TEXT NOT NULL,
 relation TEXT NOT NULL,
 linked_at TEXT NOT NULL,
 FOREIGN KEY(change_id) REFERENCES improvement_changes(change_id),
 FOREIGN KEY(daily_run_id) REFERENCES daily_runs(daily_run_id)
);
CREATE TABLE IF NOT EXISTS improvement_changes_metric_effects(
 effect_id INTEGER PRIMARY KEY AUTOINCREMENT,
 change_id INTEGER NOT NULL,
 daily_run_id TEXT NOT NULL,
 measured_at TEXT NOT NULL,
 correction_rate REAL,
 access_failure_rate REAL,
 field_coverage_rate REAL,
 known_field_rate REAL,
 source_yield_rate REAL,
 recovery_success_rate REAL,
 baseline_daily_run_id TEXT,
 metadata_json TEXT,
 FOREIGN KEY(change_id) REFERENCES improvement_changes(change_id)
);
CREATE TABLE IF NOT EXISTS adaptive_weight_observations(
 observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
 goal_profile TEXT NOT NULL,
 metric_name TEXT NOT NULL,
 change_id INTEGER,
 verdict TEXT,
 delta REAL,
 direction_score REAL,
 evidence_strength REAL DEFAULT 1.0,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS adaptive_weight_profiles(
 profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
 goal_profile TEXT NOT NULL UNIQUE,
 base_weights_json TEXT NOT NULL,
 adaptive_weights_json TEXT NOT NULL,
 sample_count INTEGER DEFAULT 0,
 last_recomputed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS improvement_backlog_items(
 backlog_id INTEGER PRIMARY KEY AUTOINCREMENT,
 backlog_uuid TEXT NOT NULL UNIQUE,
 source_id TEXT,
 field_name TEXT,
 title TEXT NOT NULL,
 priority TEXT NOT NULL,
 sample_confidence TEXT NOT NULL,
 hotspot_score INTEGER DEFAULT 0,
 goal_profile TEXT,
 goal_weights_json TEXT,
 status TEXT NOT NULL DEFAULT 'OPEN',
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 opened_by TEXT,
 owner TEXT,
 rejection_reason TEXT,
 metadata_json TEXT
);
CREATE TABLE IF NOT EXISTS improvement_backlog_history(
 history_id INTEGER PRIMARY KEY AUTOINCREMENT,
 backlog_id INTEGER NOT NULL,
 from_status TEXT,
 to_status TEXT NOT NULL,
 actor TEXT NOT NULL,
 note TEXT,
 created_at TEXT NOT NULL,
 FOREIGN KEY(backlog_id) REFERENCES improvement_backlog_items(backlog_id)
);
CREATE TABLE IF NOT EXISTS improvement_effect_snapshots(
 snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
 backlog_id INTEGER NOT NULL,
 phase TEXT NOT NULL,
 captured_at TEXT NOT NULL,
 review_count INTEGER DEFAULT 0,
 correction_rate REAL,
 access_failure_rate REAL,
 field_coverage_rate REAL,
 known_field_rate REAL,
 source_yield_rate REAL,
 recovery_success_rate REAL,
 metadata_json TEXT,
 FOREIGN KEY(backlog_id) REFERENCES improvement_backlog_items(backlog_id)
);
CREATE TABLE IF NOT EXISTS human_review_actions(
 action_id INTEGER PRIMARY KEY AUTOINCREMENT,
 action_uuid TEXT NOT NULL UNIQUE,
 review_type TEXT NOT NULL,
 target_id INTEGER,
 event_instance_id INTEGER,
 field_name TEXT,
 recovery_id INTEGER,
 action TEXT NOT NULL,
 actor TEXT NOT NULL,
 reason TEXT,
 old_value_json TEXT,
 new_value_json TEXT,
 evidence_json TEXT,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS human_review_state(
 review_key TEXT PRIMARY KEY,
 review_type TEXT NOT NULL,
 target_id INTEGER,
 event_instance_id INTEGER,
 field_name TEXT,
 recovery_id INTEGER,
 state TEXT NOT NULL,
 last_action_id INTEGER,
 updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS daily_metric_snapshots(
 snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
 daily_run_id TEXT NOT NULL UNIQUE,
 run_date TEXT NOT NULL,
 captured_at TEXT NOT NULL,
 payload_json TEXT NOT NULL,
 event_confidence_json TEXT,
 field_confidence_json TEXT,
 source_metrics_json TEXT,
 human_review_metrics_json TEXT,
 hotspot_json TEXT,
 backlog_json TEXT,
 p0_count INTEGER DEFAULT 0,
 health TEXT,
 immutable_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS daily_runs(
 daily_run_id TEXT PRIMARY KEY, run_date TEXT NOT NULL, mode TEXT NOT NULL,
 started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL,
 root_lineage_id TEXT, discovery_lineage_count INTEGER DEFAULT 0,
 acquisition_run_count INTEGER DEFAULT 0, recovery_run_count INTEGER DEFAULT 0,
 metric_status TEXT, report_status TEXT, summary_json TEXT
);
CREATE TABLE IF NOT EXISTS daily_run_lineages(
 link_id INTEGER PRIMARY KEY AUTOINCREMENT, daily_run_id TEXT NOT NULL,
 lineage_id TEXT NOT NULL, role TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS observation_lineages(
 lineage_id TEXT PRIMARY KEY,
 root_run_type TEXT NOT NULL,
 root_source_id TEXT,
 root_query TEXT,
 root_url TEXT,
 created_at TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'ACTIVE',
 final_event_instance_id INTEGER,
 metadata_json TEXT
);
CREATE TABLE IF NOT EXISTS observation_run_links(
 link_id INTEGER PRIMARY KEY AUTOINCREMENT,
 lineage_id TEXT NOT NULL,
 observation_id INTEGER NOT NULL,
 parent_observation_id INTEGER,
 stage TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS observation_post_links(
 link_id INTEGER PRIMARY KEY AUTOINCREMENT,
 lineage_id TEXT NOT NULL,
 observation_id INTEGER,
 post_id INTEGER NOT NULL,
 source_id TEXT,
 role TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS observation_event_links(
 link_id INTEGER PRIMARY KEY AUTOINCREMENT,
 lineage_id TEXT NOT NULL,
 observation_id INTEGER,
 event_instance_id INTEGER NOT NULL,
 role TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS observation_runs(
 observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
 lineage_id TEXT,
 run_type TEXT NOT NULL,
 source_id TEXT,
 target_url TEXT,
 query_text TEXT,
 started_at TEXT NOT NULL,
 finished_at TEXT,
 result_status TEXT NOT NULL,
 discovered_count INTEGER DEFAULT 0,
 rawpost_new_count INTEGER DEFAULT 0,
 rawpost_duplicate_count INTEGER DEFAULT 0,
 acquisition_attempt_count INTEGER DEFAULT 0,
 acquisition_success_count INTEGER DEFAULT 0,
 acquisition_failure_count INTEGER DEFAULT 0,
 recovery_attempt_count INTEGER DEFAULT 0,
 recovery_success_count INTEGER DEFAULT 0,
 error_code TEXT,
 error_message TEXT,
 metadata_json TEXT
);
CREATE TABLE IF NOT EXISTS observation_rawpost_events(
 event_id INTEGER PRIMARY KEY AUTOINCREMENT,
 observation_id INTEGER NOT NULL,
 post_id INTEGER,
 source_id TEXT NOT NULL,
 source_url TEXT,
 event_kind TEXT NOT NULL,
 created_at TEXT NOT NULL,
 FOREIGN KEY(observation_id) REFERENCES observation_runs(observation_id),
 FOREIGN KEY(post_id) REFERENCES raw_posts(post_id)
);
CREATE TABLE IF NOT EXISTS observation_recovery_events(
 event_id INTEGER PRIMARY KEY AUTOINCREMENT,
 observation_id INTEGER NOT NULL,
 recovery_id INTEGER,
 source_id TEXT,
 event_hint TEXT,
 event_kind TEXT NOT NULL,
 created_at TEXT NOT NULL,
 FOREIGN KEY(observation_id) REFERENCES observation_runs(observation_id)
);
CREATE TABLE IF NOT EXISTS evidence_metrics_v2_snapshots(
 metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
 window_label TEXT NOT NULL,
 metric_scope TEXT NOT NULL,
 source_id TEXT,
 event_count INTEGER DEFAULT 0,
 field_total INTEGER DEFAULT 0,
 field_verified INTEGER DEFAULT 0,
 field_expected INTEGER DEFAULT 0,
 field_inferred INTEGER DEFAULT 0,
 field_conflict INTEGER DEFAULT 0,
 field_unknown INTEGER DEFAULT 0,
 expected_to_verified_promotions INTEGER DEFAULT 0,
 expected_to_verified_opportunities INTEGER DEFAULT 0,
 source_yield_events INTEGER DEFAULT 0,
 source_yield_posts INTEGER DEFAULT 0,
 access_attempts INTEGER DEFAULT 0,
 access_failures INTEGER DEFAULT 0,
 primary_recovery_attempts INTEGER DEFAULT 0,
 primary_recovery_success INTEGER DEFAULT 0,
 generated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_metrics_snapshots(
 metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
 source_id TEXT NOT NULL,
 platform TEXT NOT NULL,
 window_label TEXT NOT NULL,
 discovered_count INTEGER DEFAULT 0,
 new_count INTEGER DEFAULT 0,
 duplicate_count INTEGER DEFAULT 0,
 acquisition_attempts INTEGER DEFAULT 0,
 acquisition_full INTEGER DEFAULT 0,
 acquisition_body_only INTEGER DEFAULT 0,
 acquisition_partial INTEGER DEFAULT 0,
 acquisition_failed INTEGER DEFAULT 0,
 poster_success INTEGER DEFAULT 0,
 recovery_attempts INTEGER DEFAULT 0,
 recovery_resolved INTEGER DEFAULT 0,
 recovery_pending INTEGER DEFAULT 0,
 human_review_count INTEGER DEFAULT 0,
 revision_count INTEGER DEFAULT 0,
 cancellation_count INTEGER DEFAULT 0,
 critical_cancellation_miss INTEGER DEFAULT 0,
 freshness_checks INTEGER DEFAULT 0,
 freshness_change_detected INTEGER DEFAULT 0,
 generated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cross_source_runs(
 run_id INTEGER PRIMARY KEY AUTOINCREMENT,
 recovery_id INTEGER NOT NULL,
 provider TEXT NOT NULL,
 query TEXT NOT NULL,
 result_count INTEGER DEFAULT 0,
 matched_count INTEGER DEFAULT 0,
 started_at TEXT NOT NULL,
 finished_at TEXT,
 status TEXT NOT NULL,
 error TEXT,
 FOREIGN KEY(recovery_id) REFERENCES recovery_queue(recovery_id)
);
CREATE TABLE IF NOT EXISTS recovery_queue(
 recovery_id INTEGER PRIMARY KEY AUTOINCREMENT,
 post_id INTEGER NOT NULL,
 source_id TEXT NOT NULL,
 event_hint TEXT,
 reason TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'PENDING',
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 UNIQUE(post_id, reason),
 FOREIGN KEY(post_id) REFERENCES raw_posts(post_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_fixture_key ON raw_posts(fixture_key) WHERE fixture_key IS NOT NULL;
"""

def init_db(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    _add_column_if_missing(con, "evidences", "context_id", "TEXT")
    con.commit()
    return con


def _add_column_if_missing(con, table: str, column: str, sql_type: str) -> None:
    """`CREATE TABLE IF NOT EXISTS` never adds a column to an already-existing
    table, and this file's own deployed SQLite predates `context_id`
    (v0.81.2, Event Context Safety - which evidence came from which segment
    of a multi-program post). SQLite has no `ADD COLUMN IF NOT EXISTS`, so
    check first; a fresh database already has the column from SCHEMA above and
    this is a no-op for it.
    """
    existing = {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")

def reset_runtime_tables(con):
    con.execute("DELETE FROM acquired_media")
    con.execute("DELETE FROM recovery_queue")
    con.execute("DELETE FROM acquisition_runs")
    con.execute("DELETE FROM evidences")
    con.execute("DELETE FROM event_candidates")
    con.execute("DELETE FROM raw_posts")
    con.execute("DELETE FROM collector_runs")
    con.commit()

def seed_sources(con, sources):
    for s in sources:
        con.execute("""INSERT OR REPLACE INTO sources(
            source_id,platform,source_role,name,status,authority_level,access_state)
            VALUES(?,?,?,?,?,?,?)""",
            (s["source_id"],s["platform"],s["source_role"],s["name"],s.get("status","ACTIVE"),
             s.get("authority_level","UNKNOWN"),s.get("access_state","UNKNOWN")))
    con.commit()

def persist_fixture(con, key, source_id, title, body, events):
    now = datetime.now(timezone.utc).isoformat()
    raw_hash = hashlib.sha256(f"{title}\n{body}".encode("utf-8")).hexdigest()
    cur = con.execute("INSERT INTO raw_posts(fixture_key,source_id,external_key,title,body,acquisition_quality,raw_hash,collected_at) VALUES(?,?,?,?,?,?,?,?)",
                      (key,source_id,f"fixture:{key}",title,body,"FULL",raw_hash,now))
    post_id = cur.lastrowid
    persist_events(con, post_id, events)
    con.commit()

def persist_events(con, post_id, events):
    for ev in events:
        cur = con.execute("""INSERT INTO event_candidates(post_id,name,event_type,event_date,start_time,end_time,end_day_offset,fee,venue,dj,status,core_complete)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (post_id, ev.name, ev.event_type, ev.date, ev.start_time, ev.end_time, ev.end_day_offset, ev.fee, ev.venue, ev.dj, ev.status, int(ev.core_complete)))
        cid = cur.lastrowid
        for e in ev.evidences:
            con.execute("INSERT INTO evidences(candidate_id,field,value,raw_text,evidence_type,source_role,inference,context_id) VALUES(?,?,?,?,?,?,?,?)",
                        (cid,e.field,json.dumps(e.value, ensure_ascii=False) if isinstance(e.value,(dict,list)) else str(e.value),e.raw_text,e.evidence_type,e.source_role,e.inference,e.context_id))

def persist_raw_post(con, post):
    now = datetime.now(timezone.utc).isoformat()
    ext = post.source_url or hashlib.sha256(f"{post.source_id}|{post.title}|{post.published_at}".encode()).hexdigest()
    external_key = f"{post.source_id}|{ext}"
    raw_hash = hashlib.sha256(f"{post.title}\n{post.body}\n{post.raw_json or ''}".encode("utf-8")).hexdigest()
    existing = con.execute("SELECT post_id FROM raw_posts WHERE external_key=?", (external_key,)).fetchone()
    if existing:
        return existing["post_id"], False
    cur = con.execute("""INSERT INTO raw_posts(source_id,source_url,external_key,published_at,title,body,cafe_name,thumbnail_url,discovery_query,acquisition_quality,raw_json,raw_hash,collected_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (post.source_id,post.source_url,external_key,post.published_at,post.title,post.body,post.cafe_name,post.thumbnail_url,post.discovery_query,post.acquisition_quality,post.raw_json,raw_hash,now))
    con.commit()
    return cur.lastrowid, True

def update_raw_post_acquisition(con, post_id, *, body=None, acquisition_quality=None):
    if body is not None and acquisition_quality is not None:
        con.execute("UPDATE raw_posts SET body=?, acquisition_quality=? WHERE post_id=?", (body, acquisition_quality, post_id))
    elif body is not None:
        con.execute("UPDATE raw_posts SET body=? WHERE post_id=?", (body, post_id))
    elif acquisition_quality is not None:
        con.execute("UPDATE raw_posts SET acquisition_quality=? WHERE post_id=?", (acquisition_quality, post_id))
    con.commit()

def persist_acquisition_result(con, result, *, mode="live", started_at=None):
    now = datetime.now(timezone.utc).isoformat()
    started_at = started_at or now
    cur = con.execute("""INSERT INTO acquisition_runs(post_id,source_id,source_url,mode,status,http_status,final_url,content_type,body_chars,image_count,poster_candidate_count,started_at,finished_at,error_code,error)
    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
    (result.post_id,result.source_id,result.source_url,mode,result.status,result.http_status,result.final_url,result.content_type,
     result.body_chars,len(result.images),len(result.poster_candidates),started_at,result.acquired_at or now,result.error_code,result.error))
    aid = cur.lastrowid
    poster_set = set(result.poster_candidates)
    for url in result.images:
        con.execute("INSERT INTO acquired_media(acquisition_id,post_id,media_url,media_type,poster_candidate) VALUES(?,?,?,?,?)",
                    (aid,result.post_id,url,"IMAGE",int(url in poster_set)))
    con.commit()
    return aid

def enqueue_recovery(con, post_id, source_id, event_hint, reason):
    now = datetime.now(timezone.utc).isoformat()
    con.execute("""INSERT INTO recovery_queue(post_id,source_id,event_hint,reason,state,created_at,updated_at)
    VALUES(?,?,?,?,?,?,?)
    ON CONFLICT(post_id,reason) DO UPDATE SET updated_at=excluded.updated_at""",
    (post_id,source_id,event_hint,reason,"PENDING",now,now))
    con.commit()

def pending_metadata_posts(con):
    return con.execute("""SELECT post_id,source_id,source_url,title,body,published_at,acquisition_quality
                          FROM raw_posts
                          WHERE source_url IS NOT NULL AND source_url<>'' AND acquisition_quality='METADATA_ONLY'
                          ORDER BY post_id""").fetchall()


def list_pending_recovery(con):
    return con.execute("""SELECT rq.*, rp.source_url, rp.title AS post_title
                          FROM recovery_queue rq
                          JOIN raw_posts rp ON rp.post_id=rq.post_id
                          WHERE rq.state='PENDING'
                          ORDER BY rq.recovery_id""").fetchall()

def update_recovery_state(con, recovery_id, state):
    now=datetime.now(timezone.utc).isoformat()
    con.execute("UPDATE recovery_queue SET state=?, updated_at=? WHERE recovery_id=?",(state,now,recovery_id))
    con.commit()

def persist_cross_source_run(con, recovery_id, provider, query, result_count, matched_count, started_at, status, error=None):
    finished=datetime.now(timezone.utc).isoformat()
    con.execute("""INSERT INTO cross_source_runs(recovery_id,provider,query,result_count,matched_count,started_at,finished_at,status,error)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (recovery_id,provider,query,result_count,matched_count,started_at,finished,status,error))
    con.commit()

def upsert_event_instance(con, identity_key, normalized_name, event_date, normalized_venue, status):
    now=datetime.now(timezone.utc).isoformat()
    row=con.execute("SELECT event_instance_id FROM event_instances WHERE identity_key=?",(identity_key,)).fetchone()
    if row:
        eid=row["event_instance_id"]
        con.execute("""UPDATE event_instances
                       SET normalized_name=?,event_date=?,normalized_venue=?,status=?,updated_at=?
                       WHERE event_instance_id=?""",
                    (normalized_name,event_date,normalized_venue,status,now,eid))
    else:
        cur=con.execute("""INSERT INTO event_instances(identity_key,normalized_name,event_date,normalized_venue,status,source_count,created_at,updated_at)
                           VALUES(?,?,?,?,?,?,?,?)""",
                        (identity_key,normalized_name,event_date,normalized_venue,status,0,now,now))
        eid=cur.lastrowid
    con.commit()
    return eid

def link_candidate_to_instance(con, event_instance_id, candidate_id, source_id):
    now=datetime.now(timezone.utc).isoformat()
    con.execute("""INSERT OR IGNORE INTO event_instance_candidates(event_instance_id,candidate_id,source_id,linked_at)
                   VALUES(?,?,?,?)""",(event_instance_id,candidate_id,source_id,now))
    n=con.execute("SELECT COUNT(DISTINCT source_id) AS n FROM event_instance_candidates WHERE event_instance_id=?",(event_instance_id,)).fetchone()["n"]
    con.execute("UPDATE event_instances SET source_count=?,updated_at=? WHERE event_instance_id=?",(n,now,event_instance_id))
    con.commit()

def event_candidates_for_post(con, post_id):
    return con.execute("SELECT * FROM event_candidates WHERE post_id=? ORDER BY candidate_id",(post_id,)).fetchall()

def event_instance_summary(con):
    return con.execute("""SELECT ei.*,
        COUNT(eic.candidate_id) AS candidate_count,
        COUNT(DISTINCT eic.source_id) AS distinct_sources
        FROM event_instances ei
        LEFT JOIN event_instance_candidates eic ON eic.event_instance_id=ei.event_instance_id
        GROUP BY ei.event_instance_id ORDER BY ei.event_instance_id""").fetchall()


def persist_metrics_snapshot(con, row):
    con.execute("""INSERT INTO source_metrics_snapshots(
        source_id,platform,window_label,discovered_count,new_count,duplicate_count,
        acquisition_attempts,acquisition_full,acquisition_body_only,acquisition_partial,acquisition_failed,
        poster_success,recovery_attempts,recovery_resolved,recovery_pending,human_review_count,
        revision_count,cancellation_count,critical_cancellation_miss,freshness_checks,freshness_change_detected,generated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (row["source_id"],row["platform"],row["window_label"],row["discovered_count"],row["new_count"],row["duplicate_count"],
         row["acquisition_attempts"],row["acquisition_full"],row["acquisition_body_only"],row["acquisition_partial"],row["acquisition_failed"],
         row["poster_success"],row["recovery_attempts"],row["recovery_resolved"],row["recovery_pending"],row["human_review_count"],
         row.get("revision_count",0),row.get("cancellation_count",0),row.get("critical_cancellation_miss",0),
         row.get("freshness_checks",0),row.get("freshness_change_detected",0),row["generated_at"]))
    con.commit()


def persist_event_revision(con, *, event_instance_id, candidate_id, source_id, revision_role,
                           effective_at=None, field_changes=None, raw_summary=None, is_current=True):
    now=datetime.now(timezone.utc).isoformat()
    if revision_role in ("UPDATE","CANCELLATION") and is_current:
        con.execute("UPDATE event_revisions SET is_current=0 WHERE event_instance_id=?",(event_instance_id,))
    cur=con.execute("""INSERT INTO event_revisions(
        event_instance_id,candidate_id,source_id,revision_role,effective_at,observed_at,
        field_changes_json,raw_summary,is_current)
        VALUES(?,?,?,?,?,?,?,?,?)""",
        (event_instance_id,candidate_id,source_id,revision_role,effective_at,now,
         json.dumps(field_changes or {},ensure_ascii=False),raw_summary,int(is_current)))
    con.commit()
    return cur.lastrowid

def persist_refresh_check(con, *, event_instance_id, checked_at, scheduled_event_date,
                          hours_before_start, status_before, status_after,
                          change_detected=False, cancellation_detected=False,
                          critical_miss=False, source_id=None, notes=None):
    con.execute("""INSERT INTO event_refresh_checks(
        event_instance_id,checked_at,scheduled_event_date,hours_before_start,status_before,status_after,
        change_detected,cancellation_detected,critical_miss,source_id,notes)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (event_instance_id,checked_at,scheduled_event_date,hours_before_start,status_before,status_after,
         int(change_detected),int(cancellation_detected),int(critical_miss),source_id,notes))
    con.commit()

def revision_history(con, event_instance_id):
    return con.execute("SELECT * FROM event_revisions WHERE event_instance_id=? ORDER BY revision_id",
                       (event_instance_id,)).fetchall()


def upsert_event_field_state(con, *, event_instance_id, field_name, value=None, confidence="UNKNOWN",
                             evidence_ids=None, expected_value=None, verified_value=None, source_scope=None):
    now=datetime.now(timezone.utc).isoformat()
    con.execute("""INSERT INTO event_field_states(
        event_instance_id,field_name,value,confidence,evidence_ids_json,expected_value,verified_value,source_scope,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?)
        ON CONFLICT(event_instance_id,field_name) DO UPDATE SET
          value=excluded.value,
          confidence=excluded.confidence,
          evidence_ids_json=excluded.evidence_ids_json,
          expected_value=excluded.expected_value,
          verified_value=excluded.verified_value,
          source_scope=excluded.source_scope,
          updated_at=excluded.updated_at""",
        (event_instance_id,field_name,value,confidence,json.dumps(evidence_ids or []),
         expected_value,verified_value,source_scope,now))
    con.commit()

def get_event_field_states(con, event_instance_id):
    return con.execute("""SELECT * FROM event_field_states
                          WHERE event_instance_id=? ORDER BY field_name""",
                       (event_instance_id,)).fetchall()


def update_source_access(con, source_id, *, authority_level=None, access_state=None):
    row=con.execute("SELECT * FROM sources WHERE source_id=?",(source_id,)).fetchone()
    if not row:
        raise KeyError(f"Unknown source_id: {source_id}")
    authority=authority_level if authority_level is not None else row["authority_level"]
    access=access_state if access_state is not None else row["access_state"]
    con.execute("UPDATE sources SET authority_level=?,access_state=? WHERE source_id=?",
                (authority,access,source_id))
    con.commit()

def classify_media_record(con, media_id, media_class, reason):
    con.execute("UPDATE acquired_media SET media_class=?,media_class_reason=? WHERE media_id=?",
                (media_class,reason,media_id))
    con.commit()

def media_rows_for_post(con, post_id):
    return con.execute("""SELECT am.* FROM acquired_media am
                          WHERE am.post_id=? ORDER BY am.media_id""",(post_id,)).fetchall()


def persist_evidence_metrics_v2(con, row):
    con.execute("""INSERT INTO evidence_metrics_v2_snapshots(
        window_label,metric_scope,source_id,event_count,field_total,field_verified,field_expected,
        field_inferred,field_conflict,field_unknown,expected_to_verified_promotions,
        expected_to_verified_opportunities,source_yield_events,source_yield_posts,
        access_attempts,access_failures,primary_recovery_attempts,primary_recovery_success,generated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (row["window_label"],row["metric_scope"],row.get("source_id"),row["event_count"],row["field_total"],
         row["field_verified"],row["field_expected"],row["field_inferred"],row["field_conflict"],row["field_unknown"],
         row["expected_to_verified_promotions"],row["expected_to_verified_opportunities"],
         row["source_yield_events"],row["source_yield_posts"],row["access_attempts"],row["access_failures"],
         row["primary_recovery_attempts"],row["primary_recovery_success"],row["generated_at"]))
    con.commit()


def create_lineage(con, *, root_run_type, root_source_id=None, root_query=None, root_url=None, metadata=None):
    import uuid
    now=datetime.now(timezone.utc).isoformat()
    lineage_id=str(uuid.uuid4())
    con.execute("""INSERT INTO observation_lineages(
        lineage_id,root_run_type,root_source_id,root_query,root_url,created_at,status,metadata_json)
        VALUES(?,?,?,?,?,?,?,?)""",
        (lineage_id,root_run_type,root_source_id,root_query,root_url,now,"ACTIVE",
         json.dumps(metadata or {},ensure_ascii=False)))
    con.commit()
    return lineage_id

def create_lineage(con, *, root_run_type, root_source_id=None, root_query=None, root_url=None, metadata=None):
    import uuid
    now=datetime.now(timezone.utc).isoformat()
    lineage_id=str(uuid.uuid4())
    con.execute("""INSERT INTO observation_lineages(
        lineage_id,root_run_type,root_source_id,root_query,root_url,created_at,status,metadata_json)
        VALUES(?,?,?,?,?,?,?,?)""",
        (lineage_id,root_run_type,root_source_id,root_query,root_url,now,"ACTIVE",
         json.dumps(metadata or {},ensure_ascii=False)))
    con.commit()
    return lineage_id

def start_observation(con, *, run_type, source_id=None, target_url=None, query_text=None,
                      metadata=None, lineage_id=None, parent_observation_id=None, stage=None):
    now=datetime.now(timezone.utc).isoformat()
    if lineage_id is None:
        lineage_id=create_lineage(con,root_run_type=run_type,root_source_id=source_id,
                                  root_query=query_text,root_url=target_url,metadata=metadata)
    cur=con.execute("""INSERT INTO observation_runs(
        lineage_id,run_type,source_id,target_url,query_text,started_at,result_status,metadata_json)
        VALUES(?,?,?,?,?,?,?,?)""",
        (lineage_id,run_type,source_id,target_url,query_text,now,"RUNNING",
         json.dumps(metadata or {},ensure_ascii=False)))
    obs_id=cur.lastrowid
    con.execute("""INSERT INTO observation_run_links(
        lineage_id,observation_id,parent_observation_id,stage,created_at)
        VALUES(?,?,?,?,?)""",(lineage_id,obs_id,parent_observation_id,stage or run_type,now))
    con.commit()
    return obs_id
    return observation_id
    return cur.lastrowid

def finish_observation(con, observation_id, *, result_status="PASS",
                       discovered_count=0, rawpost_new_count=0, rawpost_duplicate_count=0,
                       acquisition_attempt_count=0, acquisition_success_count=0, acquisition_failure_count=0,
                       recovery_attempt_count=0, recovery_success_count=0,
                       error_code=None, error_message=None, metadata=None):
    now=datetime.now(timezone.utc).isoformat()
    con.execute("""UPDATE observation_runs SET
        finished_at=?,result_status=?,discovered_count=?,rawpost_new_count=?,rawpost_duplicate_count=?,
        acquisition_attempt_count=?,acquisition_success_count=?,acquisition_failure_count=?,
        recovery_attempt_count=?,recovery_success_count=?,error_code=?,error_message=?,
        metadata_json=COALESCE(?,metadata_json)
        WHERE observation_id=?""",
        (now,result_status,discovered_count,rawpost_new_count,rawpost_duplicate_count,
         acquisition_attempt_count,acquisition_success_count,acquisition_failure_count,
         recovery_attempt_count,recovery_success_count,error_code,error_message,
         json.dumps(metadata,ensure_ascii=False) if metadata is not None else None,observation_id))
    con.commit()

def record_observation_rawpost(con, observation_id, *, post_id, source_id, source_url, event_kind):
    now=datetime.now(timezone.utc).isoformat()
    con.execute("""INSERT INTO observation_rawpost_events(
        observation_id,post_id,source_id,source_url,event_kind,created_at)
        VALUES(?,?,?,?,?,?)""",
        (observation_id,post_id,source_id,source_url,event_kind,now))
    con.commit()

def record_observation_recovery(con, observation_id, *, recovery_id, source_id, event_hint, event_kind):
    now=datetime.now(timezone.utc).isoformat()
    con.execute("""INSERT INTO observation_recovery_events(
        observation_id,recovery_id,source_id,event_hint,event_kind,created_at)
        VALUES(?,?,?,?,?,?)""",
        (observation_id,recovery_id,source_id,event_hint,event_kind,now))
    con.commit()


def link_observation_post(con, *, lineage_id, observation_id, post_id, source_id=None, role="DISCOVERED"):
    now=datetime.now(timezone.utc).isoformat()
    con.execute("""INSERT INTO observation_post_links(
        lineage_id,observation_id,post_id,source_id,role,created_at)
        VALUES(?,?,?,?,?,?)""",
        (lineage_id,observation_id,post_id,source_id,role,now))
    con.commit()

def link_observation_event(con, *, lineage_id, observation_id, event_instance_id, role="RESULT"):
    now=datetime.now(timezone.utc).isoformat()
    con.execute("""INSERT INTO observation_event_links(
        lineage_id,observation_id,event_instance_id,role,created_at)
        VALUES(?,?,?,?,?)""",
        (lineage_id,observation_id,event_instance_id,role,now))
    con.execute("""UPDATE observation_lineages
                   SET final_event_instance_id=? WHERE lineage_id=?""",
                (event_instance_id,lineage_id))
    con.commit()

def close_lineage(con, lineage_id, status="COMPLETE"):
    con.execute("UPDATE observation_lineages SET status=? WHERE lineage_id=?",(status,lineage_id))
    con.commit()

def lineage_trace(con, lineage_id):
    lineage=con.execute("SELECT * FROM observation_lineages WHERE lineage_id=?",(lineage_id,)).fetchone()
    runs=con.execute("""SELECT r.*,l.parent_observation_id,l.stage
                        FROM observation_runs r
                        JOIN observation_run_links l ON l.observation_id=r.observation_id
                        WHERE r.lineage_id=?
                        ORDER BY r.observation_id""",(lineage_id,)).fetchall()
    posts=con.execute("""SELECT opl.*,rp.title,rp.source_url
                         FROM observation_post_links opl
                         JOIN raw_posts rp ON rp.post_id=opl.post_id
                         WHERE opl.lineage_id=?
                         ORDER BY opl.link_id""",(lineage_id,)).fetchall()
    events=con.execute("""SELECT oel.*,ei.identity_key,ei.status
                          FROM observation_event_links oel
                          JOIN event_instances ei ON ei.event_instance_id=oel.event_instance_id
                          WHERE oel.lineage_id=?
                          ORDER BY oel.link_id""",(lineage_id,)).fetchall()
    return {
        "lineage":dict(lineage) if lineage else None,
        "runs":[dict(x) for x in runs],
        "posts":[dict(x) for x in posts],
        "events":[dict(x) for x in events],
    }


def link_observation_post(con, *, lineage_id, observation_id, post_id, source_id=None, role="DISCOVERED"):
    now=datetime.now(timezone.utc).isoformat()
    con.execute("""INSERT INTO observation_post_links(
        lineage_id,observation_id,post_id,source_id,role,created_at) VALUES(?,?,?,?,?,?)""",
        (lineage_id,observation_id,post_id,source_id,role,now))
    con.commit()

def link_observation_event(con, *, lineage_id, observation_id, event_instance_id, role="RESULT"):
    now=datetime.now(timezone.utc).isoformat()
    con.execute("""INSERT INTO observation_event_links(
        lineage_id,observation_id,event_instance_id,role,created_at) VALUES(?,?,?,?,?)""",
        (lineage_id,observation_id,event_instance_id,role,now))
    con.execute("UPDATE observation_lineages SET final_event_instance_id=? WHERE lineage_id=?",
                (event_instance_id,lineage_id))
    con.commit()

def close_lineage(con, lineage_id, status="COMPLETE"):
    con.execute("UPDATE observation_lineages SET status=? WHERE lineage_id=?",(status,lineage_id))
    con.commit()

def lineage_trace(con, lineage_id):
    lineage=con.execute("SELECT * FROM observation_lineages WHERE lineage_id=?",(lineage_id,)).fetchone()
    runs=con.execute("""SELECT r.*,l.parent_observation_id,l.stage FROM observation_runs r
                        JOIN observation_run_links l ON l.observation_id=r.observation_id
                        WHERE r.lineage_id=? ORDER BY r.observation_id""",(lineage_id,)).fetchall()
    posts=con.execute("""SELECT opl.*,rp.title,rp.source_url FROM observation_post_links opl
                         JOIN raw_posts rp ON rp.post_id=opl.post_id WHERE opl.lineage_id=?
                         ORDER BY opl.link_id""",(lineage_id,)).fetchall()
    events=con.execute("""SELECT oel.*,ei.identity_key,ei.status FROM observation_event_links oel
                          JOIN event_instances ei ON ei.event_instance_id=oel.event_instance_id
                          WHERE oel.lineage_id=? ORDER BY oel.link_id""",(lineage_id,)).fetchall()
    return {"lineage":dict(lineage) if lineage else None,"runs":[dict(x) for x in runs],
            "posts":[dict(x) for x in posts],"events":[dict(x) for x in events]}


def latest_lineage_for_post(con, post_id):
    row=con.execute("""SELECT lineage_id,observation_id
                       FROM observation_post_links
                       WHERE post_id=?
                       ORDER BY link_id DESC LIMIT 1""",(post_id,)).fetchone()
    if not row:
        return None
    return {"lineage_id":row["lineage_id"],"observation_id":row["observation_id"]}

def latest_stage_observation(con, lineage_id, stage):
    row=con.execute("""SELECT r.observation_id,r.lineage_id
                       FROM observation_runs r
                       JOIN observation_run_links l ON l.observation_id=r.observation_id
                       WHERE r.lineage_id=? AND l.stage=?
                       ORDER BY r.observation_id DESC LIMIT 1""",(lineage_id,stage)).fetchone()
    return dict(row) if row else None

def recovery_parent_for_post(con, post_id):
    origin=latest_lineage_for_post(con,post_id)
    if not origin:
        return None
    acq=latest_stage_observation(con,origin["lineage_id"],"ACQUISITION")
    if acq:
        return {"lineage_id":origin["lineage_id"],"observation_id":acq["observation_id"]}
    return origin


def create_daily_run(con, *, run_date, mode, root_lineage_id=None):
    import uuid
    now=datetime.now(timezone.utc).isoformat(); rid=str(uuid.uuid4())
    con.execute("""INSERT INTO daily_runs(
      daily_run_id,run_date,mode,started_at,status,root_lineage_id)
      VALUES(?,?,?,?,?,?)""",(rid,run_date,mode,now,"RUNNING",root_lineage_id))
    con.commit(); return rid

def link_daily_lineage(con, *, daily_run_id, lineage_id, role="SOURCE"):
    now=datetime.now(timezone.utc).isoformat()
    con.execute("INSERT INTO daily_run_lineages(daily_run_id,lineage_id,role,created_at) VALUES(?,?,?,?)",
                (daily_run_id,lineage_id,role,now)); con.commit()

def finish_daily_run(con,daily_run_id,*,status,discovery_lineage_count=0,
                     acquisition_run_count=0,recovery_run_count=0,
                     metric_status=None,report_status=None,summary=None):
    now=datetime.now(timezone.utc).isoformat()
    con.execute("""UPDATE daily_runs SET finished_at=?,status=?,discovery_lineage_count=?,
      acquisition_run_count=?,recovery_run_count=?,metric_status=?,report_status=?,summary_json=?
      WHERE daily_run_id=?""",
      (now,status,discovery_lineage_count,acquisition_run_count,recovery_run_count,
       metric_status,report_status,json.dumps(summary or {},ensure_ascii=False),daily_run_id))
    con.commit()

def daily_run_trace(con,daily_run_id):
    run=con.execute("SELECT * FROM daily_runs WHERE daily_run_id=?",(daily_run_id,)).fetchone()
    links=con.execute("""SELECT drl.*,ol.root_run_type,ol.root_source_id,ol.status lineage_status,
      ol.final_event_instance_id FROM daily_run_lineages drl
      JOIN observation_lineages ol ON ol.lineage_id=drl.lineage_id
      WHERE drl.daily_run_id=? ORDER BY drl.link_id""",(daily_run_id,)).fetchall()
    return {"daily_run":dict(run) if run else None,"lineages":[dict(x) for x in links]}


def create_human_review_action(con, *, review_type, action, actor,
                               target_id=None, event_instance_id=None, field_name=None,
                               recovery_id=None, reason=None, old_value=None, new_value=None,
                               evidence=None):
    import uuid
    now=datetime.now(timezone.utc).isoformat()
    action_uuid=str(uuid.uuid4())
    cur=con.execute("""INSERT INTO human_review_actions(
        action_uuid,review_type,target_id,event_instance_id,field_name,recovery_id,
        action,actor,reason,old_value_json,new_value_json,evidence_json,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (action_uuid,review_type,target_id,event_instance_id,field_name,recovery_id,
         action,actor,reason,
         json.dumps(old_value,ensure_ascii=False) if old_value is not None else None,
         json.dumps(new_value,ensure_ascii=False) if new_value is not None else None,
         json.dumps(evidence or {},ensure_ascii=False),now))
    action_id=cur.lastrowid
    con.commit()
    return action_id,action_uuid

def upsert_human_review_state(con, *, review_key, review_type, state, last_action_id,
                              target_id=None,event_instance_id=None,field_name=None,recovery_id=None):
    now=datetime.now(timezone.utc).isoformat()
    con.execute("""INSERT INTO human_review_state(
        review_key,review_type,target_id,event_instance_id,field_name,recovery_id,
        state,last_action_id,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?)
        ON CONFLICT(review_key) DO UPDATE SET
          review_type=excluded.review_type,
          target_id=excluded.target_id,
          event_instance_id=excluded.event_instance_id,
          field_name=excluded.field_name,
          recovery_id=excluded.recovery_id,
          state=excluded.state,
          last_action_id=excluded.last_action_id,
          updated_at=excluded.updated_at""",
        (review_key,review_type,target_id,event_instance_id,field_name,recovery_id,
         state,last_action_id,now))
    con.commit()

def list_human_review_actions(con, limit=100):
    return con.execute("""SELECT * FROM human_review_actions
                          ORDER BY action_id DESC LIMIT ?""",(limit,)).fetchall()

def get_human_review_state(con, review_key):
    return con.execute("SELECT * FROM human_review_state WHERE review_key=?",(review_key,)).fetchone()


def create_backlog_item(con, *, source_id, field_name, title, priority, sample_confidence,
                        hotspot_score=0, opened_by="system", owner=None, metadata=None,
                        goal_profile=None, goal_weights=None):
    import uuid
    now=datetime.now(timezone.utc).isoformat()
    backlog_uuid=str(uuid.uuid4())
    cur=con.execute("""INSERT INTO improvement_backlog_items(
        backlog_uuid,source_id,field_name,title,priority,sample_confidence,hotspot_score,
        goal_profile,goal_weights_json,status,created_at,updated_at,opened_by,owner,metadata_json)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (backlog_uuid,source_id,field_name,title,priority,sample_confidence,hotspot_score,
         goal_profile,json.dumps(goal_weights or {},ensure_ascii=False),
         "OPEN",now,now,opened_by,owner,json.dumps(metadata or {},ensure_ascii=False)))
    backlog_id=cur.lastrowid
    con.execute("""INSERT INTO improvement_backlog_history(
        backlog_id,from_status,to_status,actor,note,created_at)
        VALUES(?,?,?,?,?,?)""",(backlog_id,None,"OPEN",opened_by,"created",now))
    con.commit()
    return backlog_id,backlog_uuid

def update_backlog_status(con, backlog_id, *, to_status, actor="operator", note=None,
                          owner=None, rejection_reason=None):
    row=con.execute("SELECT status FROM improvement_backlog_items WHERE backlog_id=?",
                    (backlog_id,)).fetchone()
    if not row:
        raise KeyError("backlog not found")
    now=datetime.now(timezone.utc).isoformat()
    from_status=row["status"]
    con.execute("""UPDATE improvement_backlog_items SET
        status=?,updated_at=?,owner=COALESCE(?,owner),
        rejection_reason=COALESCE(?,rejection_reason)
        WHERE backlog_id=?""",
        (to_status,now,owner,rejection_reason,backlog_id))
    con.execute("""INSERT INTO improvement_backlog_history(
        backlog_id,from_status,to_status,actor,note,created_at)
        VALUES(?,?,?,?,?,?)""",
        (backlog_id,from_status,to_status,actor,note,now))
    con.commit()

def persist_effect_snapshot(con, *, backlog_id, phase, metrics, metadata=None):
    now=datetime.now(timezone.utc).isoformat()
    cur=con.execute("""INSERT INTO improvement_effect_snapshots(
        backlog_id,phase,captured_at,review_count,correction_rate,access_failure_rate,
        field_coverage_rate,known_field_rate,source_yield_rate,recovery_success_rate,metadata_json)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (backlog_id,phase,now,
         metrics.get("review_count",0),metrics.get("correction_rate"),
         metrics.get("access_failure_rate"),metrics.get("field_coverage_rate"),
         metrics.get("known_field_rate"),metrics.get("source_yield_rate"),
         metrics.get("recovery_success_rate"),
         json.dumps(metadata or {},ensure_ascii=False)))
    con.commit()
    return cur.lastrowid

def backlog_row(con, backlog_id):
    return con.execute("SELECT * FROM improvement_backlog_items WHERE backlog_id=?",
                       (backlog_id,)).fetchone()

def backlog_history(con, backlog_id):
    return con.execute("""SELECT * FROM improvement_backlog_history
                          WHERE backlog_id=? ORDER BY history_id""",(backlog_id,)).fetchall()

def effect_snapshots(con, backlog_id):
    return con.execute("""SELECT * FROM improvement_effect_snapshots
                          WHERE backlog_id=? ORDER BY snapshot_id""",(backlog_id,)).fetchall()


def create_improvement_change(con, *, backlog_id=None, title, description=None,
                              component=None, version_label=None, actor="operator", metadata=None):
    import uuid
    now=datetime.now(timezone.utc).isoformat()
    cuuid=str(uuid.uuid4())
    cur=con.execute("""INSERT INTO improvement_changes(
        change_uuid,backlog_id,title,description,component,version_label,actor,applied_at,metadata_json)
        VALUES(?,?,?,?,?,?,?,?,?)""",
        (cuuid,backlog_id,title,description,component,version_label,actor,now,
         json.dumps(metadata or {},ensure_ascii=False)))
    con.commit()
    return cur.lastrowid,cuuid

def link_change_daily_run(con, *, change_id, daily_run_id, relation="POST_CHANGE"):
    now=datetime.now(timezone.utc).isoformat()
    con.execute("""INSERT INTO change_daily_run_links(
        change_id,daily_run_id,relation,linked_at) VALUES(?,?,?,?)""",
        (change_id,daily_run_id,relation,now))
    con.commit()

def persist_change_metric_effect(con, *, change_id, daily_run_id, metrics,
                                 baseline_daily_run_id=None, metadata=None):
    now=datetime.now(timezone.utc).isoformat()
    cur=con.execute("""INSERT INTO improvement_changes_metric_effects(
        change_id,daily_run_id,measured_at,correction_rate,access_failure_rate,
        field_coverage_rate,known_field_rate,source_yield_rate,recovery_success_rate,
        baseline_daily_run_id,metadata_json)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (change_id,daily_run_id,now,metrics.get("correction_rate"),
         metrics.get("access_failure_rate"),metrics.get("field_coverage_rate"),
         metrics.get("known_field_rate"),metrics.get("source_yield_rate"),
         metrics.get("recovery_success_rate"),baseline_daily_run_id,
         json.dumps(metadata or {},ensure_ascii=False)))
    con.commit()
    return cur.lastrowid

def change_row(con, change_id):
    return con.execute("SELECT * FROM improvement_changes WHERE change_id=?",(change_id,)).fetchone()

def change_links(con, change_id):
    return con.execute("""SELECT cdl.*,dr.run_date,dr.status,dr.mode
                          FROM change_daily_run_links cdl
                          JOIN daily_runs dr ON dr.daily_run_id=cdl.daily_run_id
                          WHERE cdl.change_id=? ORDER BY cdl.link_id""",(change_id,)).fetchall()

def change_effect_rows(con, change_id):
    return con.execute("""SELECT * FROM improvement_changes_metric_effects
                          WHERE change_id=? ORDER BY effect_id""",(change_id,)).fetchall()


def persist_daily_metric_snapshot(con, *, daily_run_id, run_date, payload, immutable_hash):
    now=datetime.now(timezone.utc).isoformat()
    con.execute("""INSERT INTO daily_metric_snapshots(
      daily_run_id,run_date,captured_at,payload_json,event_confidence_json,
      field_confidence_json,source_metrics_json,human_review_metrics_json,
      hotspot_json,backlog_json,p0_count,health,immutable_hash)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (daily_run_id,run_date,now,
       json.dumps(payload,ensure_ascii=False,sort_keys=True),
       json.dumps(payload.get("event_confidence_distribution",{}),ensure_ascii=False,sort_keys=True),
       json.dumps(payload.get("field_confidence_distribution",{}),ensure_ascii=False,sort_keys=True),
       json.dumps(payload.get("source_operations",[]),ensure_ascii=False,sort_keys=True),
       json.dumps(payload.get("human_in_loop_metrics",{}),ensure_ascii=False,sort_keys=True),
       json.dumps(payload.get("correction_hotspots",{}),ensure_ascii=False,sort_keys=True),
       json.dumps(payload.get("improvement_backlog",{}),ensure_ascii=False,sort_keys=True),
       payload.get("p0_count",0),payload.get("health"),immutable_hash))
    con.commit()

def daily_metric_snapshot(con,daily_run_id):
    return con.execute("SELECT * FROM daily_metric_snapshots WHERE daily_run_id=?",(daily_run_id,)).fetchone()

def list_daily_metric_snapshots(con):
    return con.execute("""SELECT snapshot_id,daily_run_id,run_date,captured_at,p0_count,
                          health,immutable_hash FROM daily_metric_snapshots
                          ORDER BY snapshot_id""").fetchall()


def persist_change_effect_verdict(con, *, change_id, baseline_daily_run_id, post_daily_run_id,
                                  verdict, comparable_metric_count, improved_metric_count,
                                  regressed_metric_count, unchanged_metric_count, score,
                                  improved_metrics, regressed_metrics, unchanged_metrics, reasons,
                                  weighted_score=None, goal_profile=None, metric_weights=None):
    now=datetime.now(timezone.utc).isoformat()
    cur=con.execute("""INSERT INTO change_effect_verdicts(
        change_id,baseline_daily_run_id,post_daily_run_id,verdict,
        comparable_metric_count,improved_metric_count,regressed_metric_count,
        unchanged_metric_count,score,weighted_score,goal_profile,metric_weights_json,
        improved_metrics_json,regressed_metrics_json,unchanged_metrics_json,reasons_json,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (change_id,baseline_daily_run_id,post_daily_run_id,verdict,
         comparable_metric_count,improved_metric_count,regressed_metric_count,
         unchanged_metric_count,score,weighted_score,goal_profile,
         json.dumps(metric_weights or {},ensure_ascii=False),
         json.dumps(improved_metrics,ensure_ascii=False),
         json.dumps(regressed_metrics,ensure_ascii=False),
         json.dumps(unchanged_metrics,ensure_ascii=False),
         json.dumps(reasons,ensure_ascii=False),now))
    con.commit()
    return cur.lastrowid

def latest_change_effect_verdict(con, change_id):
    return con.execute("""SELECT * FROM change_effect_verdicts
                          WHERE change_id=? ORDER BY verdict_id DESC LIMIT 1""",(change_id,)).fetchone()

def change_effect_verdict_rows(con, change_id):
    return con.execute("""SELECT * FROM change_effect_verdicts
                          WHERE change_id=? ORDER BY verdict_id""",(change_id,)).fetchall()


def upsert_adaptive_weight_profile(con, *, goal_profile, base_weights, adaptive_weights, sample_count):
    now=datetime.now(timezone.utc).isoformat()
    con.execute("""INSERT INTO adaptive_weight_profiles(
        goal_profile,base_weights_json,adaptive_weights_json,sample_count,last_recomputed_at)
        VALUES(?,?,?,?,?)
        ON CONFLICT(goal_profile) DO UPDATE SET
          base_weights_json=excluded.base_weights_json,
          adaptive_weights_json=excluded.adaptive_weights_json,
          sample_count=excluded.sample_count,
          last_recomputed_at=excluded.last_recomputed_at""",
        (goal_profile,json.dumps(base_weights,ensure_ascii=False),
         json.dumps(adaptive_weights,ensure_ascii=False),sample_count,now))
    con.commit()

def adaptive_weight_profile(con, goal_profile):
    return con.execute("""SELECT * FROM adaptive_weight_profiles
                          WHERE goal_profile=?""",(goal_profile,)).fetchone()

def insert_adaptive_weight_observation(con, *, goal_profile, metric_name, change_id=None,
                                       verdict=None, delta=None, direction_score=None,
                                       evidence_strength=1.0):
    now=datetime.now(timezone.utc).isoformat()
    con.execute("""INSERT INTO adaptive_weight_observations(
        goal_profile,metric_name,change_id,verdict,delta,direction_score,evidence_strength,created_at)
        VALUES(?,?,?,?,?,?,?,?)""",
        (goal_profile,metric_name,change_id,verdict,delta,direction_score,evidence_strength,now))
    con.commit()

def adaptive_weight_observations(con, goal_profile):
    return con.execute("""SELECT * FROM adaptive_weight_observations
                          WHERE goal_profile=? ORDER BY observation_id""",(goal_profile,)).fetchall()


def persist_adaptive_shadow_verdict(con, *, change_id, baseline_daily_run_id, post_daily_run_id,
                                    goal_profile, base_verdict, shadow_verdict,
                                    base_weighted_score, shadow_weighted_score, agrees,
                                    adaptive_sample_count, base_weights, shadow_weights, reasons):
    now=datetime.now(timezone.utc).isoformat()
    cur=con.execute("""INSERT INTO adaptive_shadow_verdicts(
        change_id,baseline_daily_run_id,post_daily_run_id,goal_profile,
        base_verdict,shadow_verdict,base_weighted_score,shadow_weighted_score,
        agrees,adaptive_sample_count,base_weights_json,shadow_weights_json,
        reasons_json,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (change_id,baseline_daily_run_id,post_daily_run_id,goal_profile,
         base_verdict,shadow_verdict,base_weighted_score,shadow_weighted_score,
         1 if agrees else 0,adaptive_sample_count,
         json.dumps(base_weights,ensure_ascii=False),
         json.dumps(shadow_weights,ensure_ascii=False),
         json.dumps(reasons or [],ensure_ascii=False),now))
    con.commit()
    return cur.lastrowid

def adaptive_shadow_rows(con, change_id=None):
    if change_id is None:
        return con.execute("""SELECT * FROM adaptive_shadow_verdicts
                              ORDER BY shadow_id""").fetchall()
    return con.execute("""SELECT * FROM adaptive_shadow_verdicts
                          WHERE change_id=? ORDER BY shadow_id""",(change_id,)).fetchall()

def latest_adaptive_shadow(con, change_id):
    return con.execute("""SELECT * FROM adaptive_shadow_verdicts
                          WHERE change_id=? ORDER BY shadow_id DESC LIMIT 1""",(change_id,)).fetchone()

def adaptive_shadow_agreement_stats(con, goal_profile=None):
    where=""
    params=()
    if goal_profile:
        where=" WHERE goal_profile=?"
        params=(goal_profile,)
    rows=con.execute(f"""SELECT COUNT(*) total,
        SUM(CASE WHEN agrees=1 THEN 1 ELSE 0 END) agreements,
        SUM(CASE WHEN agrees=0 THEN 1 ELSE 0 END) disagreements
        FROM adaptive_shadow_verdicts{where}""",params).fetchone()
    total=rows["total"] or 0
    agreements=rows["agreements"] or 0
    return {
        "goal_profile":goal_profile,
        "total":total,
        "agreements":agreements,
        "disagreements":rows["disagreements"] or 0,
        "agreement_rate":round(agreements/total,4) if total else None
    }


def adaptive_shadow_for_pair(con, change_id, baseline_daily_run_id, post_daily_run_id):
    return con.execute("""SELECT * FROM adaptive_shadow_verdicts
                          WHERE change_id=? AND baseline_daily_run_id=? AND post_daily_run_id=?
                          ORDER BY shadow_id DESC LIMIT 1""",
                       (change_id,baseline_daily_run_id,post_daily_run_id)).fetchone()


def persist_shadow_safety_evaluation(con, *, goal_profile, policy_version, status,
                                     total, agreements, disagreements, agreement_rate,
                                     critical_false_improved, unsafe_improved,
                                     conservative_false_regressed,
                                     confusion_matrix, reasons):
    now=datetime.now(timezone.utc).isoformat()
    scope_key=goal_profile or "ALL"
    cur=con.execute("""INSERT INTO shadow_safety_evaluations(
        goal_profile,scope_key,policy_version,status,total,agreements,disagreements,
        agreement_rate,critical_false_improved,unsafe_improved,
        conservative_false_regressed,confusion_matrix_json,reasons_json,evaluated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (goal_profile,scope_key,policy_version,status,total,agreements,disagreements,
         agreement_rate,critical_false_improved,unsafe_improved,
         conservative_false_regressed,
         json.dumps(confusion_matrix,ensure_ascii=False),
         json.dumps(reasons,ensure_ascii=False),now))
    con.commit()
    return cur.lastrowid

def shadow_safety_evaluation_rows(con, goal_profile=None):
    if goal_profile is None:
        return con.execute("""SELECT * FROM shadow_safety_evaluations
                              ORDER BY safety_id""").fetchall()
    return con.execute("""SELECT * FROM shadow_safety_evaluations
                          WHERE goal_profile=? ORDER BY safety_id""",(goal_profile,)).fetchall()

def latest_shadow_safety_evaluation(con, goal_profile=None):
    if goal_profile is None:
        return con.execute("""SELECT * FROM shadow_safety_evaluations
                              WHERE scope_key='ALL'
                              ORDER BY safety_id DESC LIMIT 1""").fetchone()
    return con.execute("""SELECT * FROM shadow_safety_evaluations
                          WHERE goal_profile=?
                          ORDER BY safety_id DESC LIMIT 1""",(goal_profile,)).fetchone()


def adaptive_shadow_rows_by_goal(con, goal_profile=None):
    if goal_profile is None:
        return con.execute("""SELECT * FROM adaptive_shadow_verdicts
                              ORDER BY shadow_id""").fetchall()
    return con.execute("""SELECT * FROM adaptive_shadow_verdicts
                          WHERE goal_profile=? ORDER BY shadow_id""",(goal_profile,)).fetchall()


def persist_rolling_shadow_stability(con, *, goal_profile, policy_version, status,
                                     cumulative_status, total_samples,
                                     downgrade_detected, previous_status,
                                     windows, reasons):
    now=datetime.now(timezone.utc).isoformat()
    scope_key=goal_profile or "ALL"
    cur=con.execute("""INSERT INTO rolling_shadow_stability_evaluations(
        goal_profile,scope_key,policy_version,status,cumulative_status,total_samples,
        downgrade_detected,previous_status,windows_json,reasons_json,evaluated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (goal_profile,scope_key,policy_version,status,cumulative_status,total_samples,
         1 if downgrade_detected else 0,previous_status,
         json.dumps(windows,ensure_ascii=False),
         json.dumps(reasons,ensure_ascii=False),now))
    con.commit()
    return cur.lastrowid

def latest_rolling_shadow_stability(con, goal_profile=None):
    if goal_profile is None:
        return con.execute("""SELECT * FROM rolling_shadow_stability_evaluations
                              WHERE scope_key='ALL'
                              ORDER BY rolling_id DESC LIMIT 1""").fetchone()
    return con.execute("""SELECT * FROM rolling_shadow_stability_evaluations
                          WHERE goal_profile=?
                          ORDER BY rolling_id DESC LIMIT 1""",(goal_profile,)).fetchone()

def rolling_shadow_stability_rows(con, goal_profile=None):
    if goal_profile is None:
        return con.execute("""SELECT * FROM rolling_shadow_stability_evaluations
                              ORDER BY rolling_id""").fetchall()
    return con.execute("""SELECT * FROM rolling_shadow_stability_evaluations
                          WHERE goal_profile=? ORDER BY rolling_id""",(goal_profile,)).fetchall()

def latest_active_promotion_candidate(con, goal_profile=None):
    scope_key=goal_profile or "ALL"
    return con.execute("""SELECT * FROM adaptive_promotion_candidates
                          WHERE scope_key=? AND status IN ('CANDIDATE','HOLD')
                          ORDER BY candidate_id DESC LIMIT 1""",(scope_key,)).fetchone()

def create_or_get_promotion_candidate(con, *, goal_profile, policy_version, rolling_id,
                                      total_samples, agreement_rate, unsafe_improved,
                                      criteria, reasons):
    existing=latest_active_promotion_candidate(con,goal_profile)
    if existing:
        return existing["candidate_id"],False
    now=datetime.now(timezone.utc).isoformat()
    scope_key=goal_profile or "ALL"
    cur=con.execute("""INSERT INTO adaptive_promotion_candidates(
        goal_profile,scope_key,policy_version,status,rolling_id,total_samples,
        agreement_rate,unsafe_improved,criteria_json,reasons_json,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (goal_profile,scope_key,policy_version,"CANDIDATE",rolling_id,total_samples,
         agreement_rate,unsafe_improved,
         json.dumps(criteria,ensure_ascii=False),
         json.dumps(reasons,ensure_ascii=False),now,now))
    con.commit()
    return cur.lastrowid,True

def revoke_active_promotion_candidate(con, goal_profile=None, reason=None):
    row=latest_active_promotion_candidate(con,goal_profile)
    if not row:
        return None
    now=datetime.now(timezone.utc).isoformat()
    reasons=json.loads(row["reasons_json"] or "[]")
    if reason:
        reasons.append(reason)
    con.execute("""UPDATE adaptive_promotion_candidates
                   SET status='REVOKED',reasons_json=?,updated_at=?
                   WHERE candidate_id=?""",
                (json.dumps(reasons,ensure_ascii=False),now,row["candidate_id"]))
    con.commit()
    return row["candidate_id"]

def promotion_candidate_rows(con, goal_profile=None):
    if goal_profile is None:
        return con.execute("""SELECT * FROM adaptive_promotion_candidates
                              ORDER BY candidate_id""").fetchall()
    return con.execute("""SELECT * FROM adaptive_promotion_candidates
                          WHERE goal_profile=? ORDER BY candidate_id""",(goal_profile,)).fetchall()


def promotion_candidate_row(con, candidate_id):
    return con.execute("""SELECT * FROM adaptive_promotion_candidates
                          WHERE candidate_id=?""",(candidate_id,)).fetchone()

def update_promotion_candidate_status(con, candidate_id, status, reason=None):
    row=promotion_candidate_row(con,candidate_id)
    if not row:
        raise KeyError("promotion candidate not found")
    now=datetime.now(timezone.utc).isoformat()
    reasons=json.loads(row["reasons_json"] or "[]")
    if reason:
        reasons.append(reason)
    con.execute("""UPDATE adaptive_promotion_candidates
                   SET status=?,reasons_json=?,updated_at=?
                   WHERE candidate_id=?""",
                (status,json.dumps(reasons,ensure_ascii=False),now,candidate_id))
    con.commit()

def persist_promotion_review(con, *, candidate_id, decision, reviewer, reason=None, metadata=None):
    now=datetime.now(timezone.utc).isoformat()
    cur=con.execute("""INSERT INTO adaptive_promotion_reviews(
        candidate_id,decision,reviewer,reason,reviewed_at,metadata_json)
        VALUES(?,?,?,?,?,?)""",
        (candidate_id,decision,reviewer,reason,now,
         json.dumps(metadata or {},ensure_ascii=False)))
    con.commit()
    return cur.lastrowid

def promotion_review_rows(con, candidate_id=None):
    if candidate_id is None:
        return con.execute("""SELECT * FROM adaptive_promotion_reviews
                              ORDER BY review_id""").fetchall()
    return con.execute("""SELECT * FROM adaptive_promotion_reviews
                          WHERE candidate_id=? ORDER BY review_id""",(candidate_id,)).fetchall()

def create_promotion_lease(con, *, candidate_id, goal_profile, policy_version,
                           max_canary_changes, adaptive_weights, base_weights,
                           approved_by, metadata=None):
    now=datetime.now(timezone.utc).isoformat()
    existing=con.execute("""SELECT * FROM adaptive_promotion_leases
                            WHERE goal_profile=? AND status='ACTIVE'
                            ORDER BY lease_id DESC LIMIT 1""",(goal_profile,)).fetchone()
    if existing:
        raise ValueError("active promotion lease already exists for goal profile")
    cur=con.execute("""INSERT INTO adaptive_promotion_leases(
        candidate_id,goal_profile,policy_version,status,mode,max_canary_changes,
        used_canary_changes,adaptive_weights_json,base_weights_json,
        approved_by,approved_at,started_at,metadata_json)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (candidate_id,goal_profile,policy_version,"ACTIVE","CANARY",
         max_canary_changes,0,
         json.dumps(adaptive_weights,ensure_ascii=False),
         json.dumps(base_weights,ensure_ascii=False),
         approved_by,now,now,json.dumps(metadata or {},ensure_ascii=False)))
    con.commit()
    return cur.lastrowid

def active_promotion_lease(con, goal_profile):
    return con.execute("""SELECT * FROM adaptive_promotion_leases
                          WHERE goal_profile=? AND status='ACTIVE'
                          ORDER BY lease_id DESC LIMIT 1""",(goal_profile,)).fetchone()

def promotion_lease_row(con, lease_id):
    return con.execute("""SELECT * FROM adaptive_promotion_leases
                          WHERE lease_id=?""",(lease_id,)).fetchone()

def promotion_lease_rows(con, goal_profile=None):
    if goal_profile is None:
        return con.execute("""SELECT * FROM adaptive_promotion_leases
                              ORDER BY lease_id""").fetchall()
    return con.execute("""SELECT * FROM adaptive_promotion_leases
                          WHERE goal_profile=? ORDER BY lease_id""",(goal_profile,)).fetchall()

def persist_promotion_lease_event(con, *, lease_id, event_type, actor, change_id=None, detail=None):
    now=datetime.now(timezone.utc).isoformat()
    cur=con.execute("""INSERT INTO adaptive_promotion_lease_events(
        lease_id,event_type,change_id,actor,detail_json,created_at)
        VALUES(?,?,?,?,?,?)""",
        (lease_id,event_type,change_id,actor,
         json.dumps(detail or {},ensure_ascii=False),now))
    con.commit()
    return cur.lastrowid

def promotion_lease_event_rows(con, lease_id=None):
    if lease_id is None:
        return con.execute("""SELECT * FROM adaptive_promotion_lease_events
                              ORDER BY event_id""").fetchall()
    return con.execute("""SELECT * FROM adaptive_promotion_lease_events
                          WHERE lease_id=? ORDER BY event_id""",(lease_id,)).fetchall()

def consume_promotion_lease_change(con, lease_id, *, change_id, actor="system"):
    row=promotion_lease_row(con,lease_id)
    if not row or row["status"]!="ACTIVE":
        raise ValueError("promotion lease is not active")
    used=int(row["used_canary_changes"] or 0)+1
    maxc=int(row["max_canary_changes"])
    status="EXHAUSTED" if used>=maxc else "ACTIVE"
    ended=datetime.now(timezone.utc).isoformat() if status!="ACTIVE" else None
    con.execute("""UPDATE adaptive_promotion_leases
                   SET used_canary_changes=?,status=?,ended_at=COALESCE(?,ended_at)
                   WHERE lease_id=?""",(used,status,ended,lease_id))
    con.commit()
    persist_promotion_lease_event(
        con,lease_id=lease_id,event_type="CANARY_CHANGE_USED",
        change_id=change_id,actor=actor,
        detail={"used_canary_changes":used,"max_canary_changes":maxc,"status":status})
    return status,used

def rollback_promotion_lease(con, lease_id, *, actor, reason):
    row=promotion_lease_row(con,lease_id)
    if not row:
        raise KeyError("promotion lease not found")
    if row["status"] not in ("ACTIVE","EXHAUSTED"):
        return False
    now=datetime.now(timezone.utc).isoformat()
    con.execute("""UPDATE adaptive_promotion_leases
                   SET status='ROLLED_BACK',ended_at=?,rollback_reason=?
                   WHERE lease_id=?""",(now,reason,lease_id))
    con.commit()
    persist_promotion_lease_event(
        con,lease_id=lease_id,event_type="ROLLBACK",actor=actor,
        detail={"reason":reason})
    return True


def promotion_lease_for_change(con, change_id):
    return con.execute("""SELECT l.*
                          FROM adaptive_promotion_leases l
                          JOIN adaptive_promotion_lease_events e
                            ON e.lease_id=l.lease_id
                          WHERE e.change_id=? AND e.event_type='CANARY_CHANGE_USED'
                          ORDER BY e.event_id DESC LIMIT 1""",(change_id,)).fetchone()


def persist_canary_outcome_evaluation(con, *, lease_id, policy_version, status,
                                      completed_changes, safe_changes,
                                      divergent_changes, divergence_rate,
                                      false_optimism_count, base_improved_count,
                                      canary_improved_count, criteria, reasons):
    now=datetime.now(timezone.utc).isoformat()
    cur=con.execute("""INSERT INTO canary_outcome_evaluations(
        lease_id,policy_version,status,completed_changes,safe_changes,
        divergent_changes,divergence_rate,false_optimism_count,
        base_improved_count,canary_improved_count,criteria_json,reasons_json,evaluated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (lease_id,policy_version,status,completed_changes,safe_changes,
         divergent_changes,divergence_rate,false_optimism_count,
         base_improved_count,canary_improved_count,
         json.dumps(criteria,ensure_ascii=False),
         json.dumps(reasons,ensure_ascii=False),now))
    con.commit()
    return cur.lastrowid

def canary_outcome_rows(con, lease_id=None):
    if lease_id is None:
        return con.execute("""SELECT * FROM canary_outcome_evaluations
                              ORDER BY outcome_id""").fetchall()
    return con.execute("""SELECT * FROM canary_outcome_evaluations
                          WHERE lease_id=? ORDER BY outcome_id""",(lease_id,)).fetchall()

def latest_canary_outcome(con, lease_id):
    return con.execute("""SELECT * FROM canary_outcome_evaluations
                          WHERE lease_id=? ORDER BY outcome_id DESC LIMIT 1""",(lease_id,)).fetchone()

def persist_final_promotion_review(con, *, lease_id, candidate_id, goal_profile,
                                   decision, reviewer, reason=None, outcome_id=None,
                                   metadata=None):
    now=datetime.now(timezone.utc).isoformat()
    cur=con.execute("""INSERT INTO adaptive_final_promotion_reviews(
        lease_id,candidate_id,goal_profile,decision,reviewer,reason,outcome_id,
        reviewed_at,metadata_json)
        VALUES(?,?,?,?,?,?,?,?,?)""",
        (lease_id,candidate_id,goal_profile,decision,reviewer,reason,outcome_id,
         now,json.dumps(metadata or {},ensure_ascii=False)))
    con.commit()
    return cur.lastrowid

def final_promotion_review_rows(con, lease_id=None):
    if lease_id is None:
        return con.execute("""SELECT * FROM adaptive_final_promotion_reviews
                              ORDER BY final_review_id""").fetchall()
    return con.execute("""SELECT * FROM adaptive_final_promotion_reviews
                          WHERE lease_id=? ORDER BY final_review_id""",(lease_id,)).fetchall()

def extend_promotion_lease(con, lease_id, *, additional_changes, actor, reason=None):
    row=promotion_lease_row(con,lease_id)
    if not row:
        raise KeyError("promotion lease not found")
    if row["status"] not in ("ACTIVE","EXHAUSTED"):
        raise ValueError("only ACTIVE/EXHAUSTED lease can be extended")
    if additional_changes<1 or additional_changes>20:
        raise ValueError("additional_changes must be between 1 and 20")
    new_max=int(row["max_canary_changes"])+additional_changes
    con.execute("""UPDATE adaptive_promotion_leases
                   SET max_canary_changes=?,status='ACTIVE',ended_at=NULL
                   WHERE lease_id=?""",(new_max,lease_id))
    con.commit()
    persist_promotion_lease_event(
        con,lease_id=lease_id,event_type="LEASE_EXTENDED",actor=actor,
        detail={"additional_changes":additional_changes,"new_max_canary_changes":new_max,
                "reason":reason})
    return new_max

def create_full_promotion(con, *, lease_id, candidate_id, goal_profile,
                          policy_version, adaptive_weights, base_weights,
                          promoted_by, metadata=None):
    existing=active_full_promotion(con,goal_profile)
    if existing:
        raise ValueError("active full promotion already exists for goal profile")
    now=datetime.now(timezone.utc).isoformat()
    cur=con.execute("""INSERT INTO adaptive_full_promotions(
        lease_id,candidate_id,goal_profile,policy_version,status,
        adaptive_weights_json,base_weights_json,promoted_by,promoted_at,metadata_json)
        VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (lease_id,candidate_id,goal_profile,policy_version,"ACTIVE",
         json.dumps(adaptive_weights,ensure_ascii=False),
         json.dumps(base_weights,ensure_ascii=False),
         promoted_by,now,json.dumps(metadata or {},ensure_ascii=False)))
    con.commit()
    return cur.lastrowid

def active_full_promotion(con, goal_profile):
    return con.execute("""SELECT * FROM adaptive_full_promotions
                          WHERE goal_profile=? AND status IN ('ACTIVE','STABLE_FULL')
                          ORDER BY promotion_id DESC LIMIT 1""",(goal_profile,)).fetchone()

def full_promotion_rows(con, goal_profile=None):
    if goal_profile is None:
        return con.execute("""SELECT * FROM adaptive_full_promotions
                              ORDER BY promotion_id""").fetchall()
    return con.execute("""SELECT * FROM adaptive_full_promotions
                          WHERE goal_profile=? ORDER BY promotion_id""",(goal_profile,)).fetchall()

def rollback_full_promotion(con, goal_profile, *, actor, reason):
    row=active_full_promotion(con,goal_profile)
    if not row:
        return None
    now=datetime.now(timezone.utc).isoformat()
    con.execute("""UPDATE adaptive_full_promotions
                   SET status='ROLLED_BACK',ended_at=?,rollback_reason=?
                   WHERE promotion_id=?""",(now,reason,row["promotion_id"]))
    con.commit()
    persist_promotion_lease_event(
        con,lease_id=row["lease_id"],event_type="FULL_PROMOTION_ROLLBACK",
        actor=actor,detail={"promotion_id":row["promotion_id"],"reason":reason})
    return row["promotion_id"]


def persist_post_promotion_observation(con, *, promotion_id, change_id, goal_profile,
                                       base_verdict, full_verdict,
                                       base_weighted_score, full_weighted_score):
    now=datetime.now(timezone.utc).isoformat()
    diverged=int(base_verdict!=full_verdict)
    false_optimism=int(base_verdict!="IMPROVED" and full_verdict=="IMPROVED")
    con.execute("""INSERT OR IGNORE INTO post_promotion_runtime_observations(
        promotion_id,change_id,goal_profile,base_verdict,full_verdict,
        base_weighted_score,full_weighted_score,diverged,false_optimism,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (promotion_id,change_id,goal_profile,base_verdict,full_verdict,
         base_weighted_score,full_weighted_score,diverged,false_optimism,now))
    con.commit()
    return con.execute("""SELECT * FROM post_promotion_runtime_observations
                          WHERE promotion_id=? AND change_id=?""",
                       (promotion_id,change_id)).fetchone()

def post_promotion_observation_rows(con, promotion_id):
    return con.execute("""SELECT * FROM post_promotion_runtime_observations
                          WHERE promotion_id=? ORDER BY observation_id""",
                       (promotion_id,)).fetchall()

def persist_post_promotion_guard(con, *, promotion_id, goal_profile, policy_version,
                                 status, sample_count, recent7_count,
                                 recent7_divergence_rate, recent14_count,
                                 recent14_divergence_rate, false_optimism_count,
                                 canary_divergence_rate, drift_from_canary,
                                 stable_full, reasons):
    now=datetime.now(timezone.utc).isoformat()
    cur=con.execute("""INSERT INTO post_promotion_guard_evaluations(
        promotion_id,goal_profile,policy_version,status,sample_count,recent7_count,
        recent7_divergence_rate,recent14_count,recent14_divergence_rate,
        false_optimism_count,canary_divergence_rate,drift_from_canary,
        stable_full,reasons_json,evaluated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (promotion_id,goal_profile,policy_version,status,sample_count,recent7_count,
         recent7_divergence_rate,recent14_count,recent14_divergence_rate,
         false_optimism_count,canary_divergence_rate,drift_from_canary,
         int(stable_full),json.dumps(reasons,ensure_ascii=False),now))
    con.commit()
    return cur.lastrowid

def post_promotion_guard_rows(con, promotion_id=None):
    if promotion_id is None:
        return con.execute("""SELECT * FROM post_promotion_guard_evaluations
                              ORDER BY guard_id""").fetchall()
    return con.execute("""SELECT * FROM post_promotion_guard_evaluations
                          WHERE promotion_id=? ORDER BY guard_id""",
                       (promotion_id,)).fetchall()

def latest_post_promotion_guard(con, promotion_id):
    return con.execute("""SELECT * FROM post_promotion_guard_evaluations
                          WHERE promotion_id=? ORDER BY guard_id DESC LIMIT 1""",
                       (promotion_id,)).fetchone()

def mark_full_promotion_stable(con, promotion_id):
    con.execute("""UPDATE adaptive_full_promotions SET status='STABLE_FULL'
                   WHERE promotion_id=? AND status='ACTIVE'""",(promotion_id,))
    con.commit()


def persist_decision_quality_observation(con, *, goal_profile, decision_outcome,
                                         event_truth, decision_action=None,
                                         source_confidence=None,
                                         critical_error_type=None,
                                         core_relevance=1.0, user_impact=1.0,
                                         change_id=None,event_id=None,metadata=None):
    now=datetime.now(timezone.utc).isoformat()
    success=int(decision_outcome=="SUCCESS")
    failure=int(decision_outcome=="FAILURE")
    cur=con.execute("""INSERT INTO decision_quality_observations(
        change_id,event_id,goal_profile,decision_outcome,event_truth,decision_action,
        source_confidence,critical_error_type,core_relevance,user_impact,
        successful_decision,failed_decision,metadata_json,observed_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (change_id,event_id,goal_profile,decision_outcome,event_truth,decision_action,
         source_confidence,critical_error_type,float(core_relevance),float(user_impact),
         success,failure,json.dumps(metadata or {},ensure_ascii=False),now))
    con.commit()
    return cur.lastrowid

def decision_quality_rows(con, goal_profile=None):
    if goal_profile is None:
        return con.execute("""SELECT * FROM decision_quality_observations
                              ORDER BY decision_observation_id""").fetchall()
    return con.execute("""SELECT * FROM decision_quality_observations
                          WHERE goal_profile=? ORDER BY decision_observation_id""",
                       (goal_profile,)).fetchall()

def persist_goal_relevance_diagnostic(con, *, goal_profile, scope_key, sample_count,
                                      core_relevance_rate,successful_decision_rate,
                                      failed_decision_rate,critical_error_count,
                                      false_verified_count,cancellation_miss_count,
                                      support_only_count,status,reasons):
    now=datetime.now(timezone.utc).isoformat()
    cur=con.execute("""INSERT INTO goal_relevance_diagnostics(
        goal_profile,scope_key,sample_count,core_relevance_rate,
        successful_decision_rate,failed_decision_rate,critical_error_count,
        false_verified_count,cancellation_miss_count,support_only_count,
        status,reasons_json,evaluated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (goal_profile,scope_key,sample_count,core_relevance_rate,
         successful_decision_rate,failed_decision_rate,critical_error_count,
         false_verified_count,cancellation_miss_count,support_only_count,
         status,json.dumps(reasons,ensure_ascii=False),now))
    con.commit()
    return cur.lastrowid

def goal_relevance_diagnostic_rows(con, goal_profile=None):
    if goal_profile is None:
        return con.execute("""SELECT * FROM goal_relevance_diagnostics
                              ORDER BY diagnostic_id""").fetchall()
    return con.execute("""SELECT * FROM goal_relevance_diagnostics
                          WHERE goal_profile=? ORDER BY diagnostic_id""",
                       (goal_profile,)).fetchall()


def upsert_decision_outcome_evidence(con, *, evidence_key,event_instance_id,
                                     change_id,goal_profile,evidence_type,
                                     proposed_outcome,proposed_event_truth,
                                     proposed_critical_error_type,source_kind,
                                     source_ref,confidence,user_impact,
                                     core_relevance,evidence):
    now=datetime.now(timezone.utc).isoformat()
    existing=con.execute("""SELECT * FROM decision_outcome_evidence
                            WHERE evidence_key=?""",(evidence_key,)).fetchone()
    if existing:
        return existing["evidence_id"],False
    cur=con.execute("""INSERT INTO decision_outcome_evidence(
        evidence_key,event_instance_id,change_id,goal_profile,evidence_type,
        proposed_outcome,proposed_event_truth,proposed_critical_error_type,
        source_kind,source_ref,confidence,status,user_impact,core_relevance,
        evidence_json,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (evidence_key,event_instance_id,change_id,goal_profile,evidence_type,
         proposed_outcome,proposed_event_truth,proposed_critical_error_type,
         source_kind,source_ref,confidence,"PENDING",float(user_impact),
         float(core_relevance),json.dumps(evidence,ensure_ascii=False),now,now))
    con.commit()
    return cur.lastrowid,True

def decision_outcome_evidence_row(con,evidence_id):
    return con.execute("""SELECT * FROM decision_outcome_evidence
                          WHERE evidence_id=?""",(evidence_id,)).fetchone()

def decision_outcome_evidence_rows(con,status=None,goal_profile=None):
    q="SELECT * FROM decision_outcome_evidence WHERE 1=1"; args=[]
    if status:
        q+=" AND status=?"; args.append(status)
    if goal_profile:
        q+=" AND goal_profile=?"; args.append(goal_profile)
    q+=" ORDER BY evidence_id"
    return con.execute(q,args).fetchall()

def update_decision_outcome_evidence_status(con,evidence_id,status):
    now=datetime.now(timezone.utc).isoformat()
    con.execute("""UPDATE decision_outcome_evidence SET status=?,updated_at=?
                   WHERE evidence_id=?""",(status,now,evidence_id))
    con.commit()

def persist_decision_outcome_confirmation(con, *, evidence_id,decision,reviewer,
                                          reason=None,
                                          decision_quality_observation_id=None,
                                          metadata=None):
    now=datetime.now(timezone.utc).isoformat()
    cur=con.execute("""INSERT INTO decision_outcome_confirmations(
        evidence_id,decision,reviewer,reason,decision_quality_observation_id,
        metadata_json,confirmed_at) VALUES(?,?,?,?,?,?,?)""",
        (evidence_id,decision,reviewer,reason,decision_quality_observation_id,
         json.dumps(metadata or {},ensure_ascii=False),now))
    con.commit()
    return cur.lastrowid

def decision_outcome_confirmation_rows(con,evidence_id=None):
    if evidence_id is None:
        return con.execute("""SELECT * FROM decision_outcome_confirmations
                              ORDER BY confirmation_id""").fetchall()
    return con.execute("""SELECT * FROM decision_outcome_confirmations
                          WHERE evidence_id=? ORDER BY confirmation_id""",
                       (evidence_id,)).fetchall()


def upsert_decision_evidence_priority_state(
    con, *, evidence_id,priority,priority_score,sla_due_at,overdue,
    independent_source_count,corroboration_count,resolution_confidence,
    expires_at,auto_resolution_eligible,cluster_key,reasons,last_evaluated_at):
    con.execute("""INSERT INTO decision_evidence_priority_state(
        evidence_id,priority,priority_score,sla_due_at,overdue,
        independent_source_count,corroboration_count,resolution_confidence,
        expires_at,auto_resolution_eligible,cluster_key,reasons_json,last_evaluated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(evidence_id) DO UPDATE SET
          priority=excluded.priority,
          priority_score=excluded.priority_score,
          sla_due_at=excluded.sla_due_at,
          overdue=excluded.overdue,
          independent_source_count=excluded.independent_source_count,
          corroboration_count=excluded.corroboration_count,
          resolution_confidence=excluded.resolution_confidence,
          expires_at=excluded.expires_at,
          auto_resolution_eligible=excluded.auto_resolution_eligible,
          cluster_key=excluded.cluster_key,
          reasons_json=excluded.reasons_json,
          last_evaluated_at=excluded.last_evaluated_at""",
        (evidence_id,priority,int(priority_score),sla_due_at,int(overdue),
         int(independent_source_count),int(corroboration_count),resolution_confidence,
         expires_at,int(auto_resolution_eligible),cluster_key,
         json.dumps(reasons,ensure_ascii=False),last_evaluated_at))
    con.commit()

def decision_evidence_priority_rows(con, status=None):
    q="""SELECT p.*,e.status,e.goal_profile,e.evidence_type,e.proposed_outcome,
                e.proposed_event_truth,e.proposed_critical_error_type,
                e.source_kind,e.source_ref,e.confidence,e.event_instance_id,
                e.user_impact,e.core_relevance,e.created_at
         FROM decision_evidence_priority_state p
         JOIN decision_outcome_evidence e ON e.evidence_id=p.evidence_id"""
    args=[]
    if status:
        q+=" WHERE e.status=?"; args.append(status)
    q+=" ORDER BY p.priority_score DESC,p.overdue DESC,e.created_at,p.evidence_id"
    return con.execute(q,args).fetchall()

def persist_decision_evidence_queue_event(con, *, evidence_id,event_type,actor,
                                          detail=None):
    now=datetime.now(timezone.utc).isoformat()
    cur=con.execute("""INSERT INTO decision_evidence_queue_events(
        evidence_id,event_type,actor,detail_json,created_at)
        VALUES(?,?,?,?,?)""",
        (evidence_id,event_type,actor,json.dumps(detail or {},ensure_ascii=False),now))
    con.commit()
    return cur.lastrowid

def decision_evidence_queue_event_rows(con,evidence_id=None):
    if evidence_id is None:
        return con.execute("""SELECT * FROM decision_evidence_queue_events
                              ORDER BY queue_event_id""").fetchall()
    return con.execute("""SELECT * FROM decision_evidence_queue_events
                          WHERE evidence_id=? ORDER BY queue_event_id""",
                       (evidence_id,)).fetchall()


def upsert_decision_evidence_cluster(con, *, cluster_key,event_instance_id,
                                     goal_profile,proposed_event_truth,
                                     critical_error_type,status,severity,
                                     evidence_count,independent_source_count,
                                     confirmed_count,rejected_count,
                                     resolution_confidence,resolved_outcome=None,
                                     resolved_by=None,resolved_at=None):
    now=datetime.now(timezone.utc).isoformat()
    row=con.execute("""SELECT cluster_id,closure_status,root_cause_status
                       FROM decision_evidence_clusters
                       WHERE cluster_key=?""",(cluster_key,)).fetchone()
    if row:
        con.execute("""UPDATE decision_evidence_clusters SET
          event_instance_id=?,goal_profile=?,proposed_event_truth=?,
          critical_error_type=?,status=?,severity=?,evidence_count=?,
          independent_source_count=?,confirmed_count=?,rejected_count=?,
          resolution_confidence=?,resolved_outcome=COALESCE(?,resolved_outcome),
          resolved_by=COALESCE(?,resolved_by),resolved_at=COALESCE(?,resolved_at),
          updated_at=? WHERE cluster_id=?""",
          (event_instance_id,goal_profile,proposed_event_truth,critical_error_type,
           status,severity,evidence_count,independent_source_count,confirmed_count,
           rejected_count,resolution_confidence,resolved_outcome,resolved_by,
           resolved_at,now,row["cluster_id"]))
        con.commit()
        return row["cluster_id"],False
    cur=con.execute("""INSERT INTO decision_evidence_clusters(
      cluster_key,event_instance_id,goal_profile,proposed_event_truth,
      critical_error_type,status,severity,evidence_count,independent_source_count,
      confirmed_count,rejected_count,resolution_confidence,resolved_outcome,
      resolved_by,resolved_at,closure_status,root_cause_status,created_at,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (cluster_key,event_instance_id,goal_profile,proposed_event_truth,
       critical_error_type,status,severity,evidence_count,independent_source_count,
       confirmed_count,rejected_count,resolution_confidence,resolved_outcome,
       resolved_by,resolved_at,"OPEN","UNATTRIBUTED",now,now))
    con.commit()
    return cur.lastrowid,True

def link_evidence_cluster(con,cluster_id,evidence_id):
    now=datetime.now(timezone.utc).isoformat()
    con.execute("""INSERT OR IGNORE INTO decision_evidence_cluster_links(
      cluster_id,evidence_id,linked_at) VALUES(?,?,?)""",
      (cluster_id,evidence_id,now))
    con.commit()

def decision_evidence_cluster_rows(con,status=None):
    if status is None:
        return con.execute("""SELECT * FROM decision_evidence_clusters
                              ORDER BY severity DESC,cluster_id""").fetchall()
    return con.execute("""SELECT * FROM decision_evidence_clusters
                          WHERE status=? ORDER BY cluster_id""",(status,)).fetchall()

def decision_evidence_cluster_row(con,cluster_id):
    return con.execute("""SELECT * FROM decision_evidence_clusters
                          WHERE cluster_id=?""",(cluster_id,)).fetchone()

def cluster_evidence_rows(con,cluster_id):
    return con.execute("""SELECT e.* FROM decision_outcome_evidence e
      JOIN decision_evidence_cluster_links l ON l.evidence_id=e.evidence_id
      WHERE l.cluster_id=? ORDER BY e.evidence_id""",(cluster_id,)).fetchall()

def persist_root_cause_attribution(
    con, *, cluster_id,category,component,source_kind,source_id,rule_key,
    confidence,status,rationale,attributed_by,backlog_id=None):
    now=datetime.now(timezone.utc).isoformat()
    row=con.execute("""SELECT attribution_id FROM root_cause_attributions
      WHERE cluster_id=? AND category=? AND COALESCE(component,'')=COALESCE(?,'')
        AND COALESCE(source_kind,'')=COALESCE(?,'')
        AND COALESCE(source_id,'')=COALESCE(?,'')
        AND COALESCE(rule_key,'')=COALESCE(?,'')""",
      (cluster_id,category,component,source_kind,source_id,rule_key)).fetchone()
    if row:
        con.execute("""UPDATE root_cause_attributions SET
          confidence=?,status=?,rationale_json=?,
          backlog_id=COALESCE(?,backlog_id),attributed_by=?,updated_at=?
          WHERE attribution_id=?""",
          (confidence,status,json.dumps(rationale,ensure_ascii=False),
           backlog_id,attributed_by,now,row["attribution_id"]))
        aid=row["attribution_id"]
    else:
        cur=con.execute("""INSERT INTO root_cause_attributions(
          cluster_id,category,component,source_kind,source_id,rule_key,
          confidence,status,rationale_json,backlog_id,attributed_by,
          attributed_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (cluster_id,category,component,source_kind,source_id,rule_key,
           confidence,status,json.dumps(rationale,ensure_ascii=False),
           backlog_id,attributed_by,now,now))
        aid=cur.lastrowid
    con.execute("""UPDATE decision_evidence_clusters SET
      root_cause_status='ATTRIBUTED',updated_at=? WHERE cluster_id=?""",
      (now,cluster_id))
    con.commit()
    return aid

def root_cause_attribution_rows(con,cluster_id=None):
    if cluster_id is None:
        return con.execute("""SELECT * FROM root_cause_attributions
                              ORDER BY attribution_id""").fetchall()
    return con.execute("""SELECT * FROM root_cause_attributions
                          WHERE cluster_id=? ORDER BY attribution_id""",
                       (cluster_id,)).fetchall()

def link_root_cause_backlog(con,attribution_id,backlog_id):
    now=datetime.now(timezone.utc).isoformat()
    con.execute("""UPDATE root_cause_attributions
                   SET backlog_id=?,updated_at=? WHERE attribution_id=?""",
                (backlog_id,now,attribution_id))
    con.commit()

def persist_cluster_closure_check(con, *, cluster_id,status,
                                  unresolved_critical_evidence,
                                  open_backlog_count,verified_backlog_count,
                                  reasons,checked_by):
    now=datetime.now(timezone.utc).isoformat()
    cur=con.execute("""INSERT INTO cluster_closure_checks(
      cluster_id,status,unresolved_critical_evidence,open_backlog_count,
      verified_backlog_count,reasons_json,checked_by,checked_at)
      VALUES(?,?,?,?,?,?,?,?)""",
      (cluster_id,status,unresolved_critical_evidence,open_backlog_count,
       verified_backlog_count,json.dumps(reasons,ensure_ascii=False),
       checked_by,now))
    con.execute("""UPDATE decision_evidence_clusters
                   SET closure_status=?,updated_at=? WHERE cluster_id=?""",
                (status,now,cluster_id))
    con.commit()
    return cur.lastrowid

def cluster_closure_check_rows(con,cluster_id=None):
    if cluster_id is None:
        return con.execute("""SELECT * FROM cluster_closure_checks
                              ORDER BY closure_check_id""").fetchall()
    return con.execute("""SELECT * FROM cluster_closure_checks
                          WHERE cluster_id=? ORDER BY closure_check_id""",
                       (cluster_id,)).fetchall()


def persist_source_reliability_observation(
    con, *, observation_key,source_id,rule_key,outcome,severity,weight,
    cluster_id=None,attribution_id=None,evidence_id=None,rationale=None):
    now=datetime.now(timezone.utc).isoformat()
    row=con.execute("""SELECT reliability_observation_id
                       FROM source_reliability_observations
                       WHERE observation_key=?""",(observation_key,)).fetchone()
    if row:
        return row["reliability_observation_id"],False
    cur=con.execute("""INSERT INTO source_reliability_observations(
      observation_key,source_id,rule_key,outcome,severity,weight,cluster_id,
      attribution_id,evidence_id,rationale_json,observed_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
      (observation_key,source_id,rule_key,outcome,severity,float(weight),
       cluster_id,attribution_id,evidence_id,
       json.dumps(rationale or [],ensure_ascii=False),now))
    con.commit()
    return cur.lastrowid,True

def source_reliability_observation_rows(con,source_id=None,rule_key=None):
    q="SELECT * FROM source_reliability_observations WHERE 1=1"; args=[]
    if source_id is not None:
        q+=" AND source_id=?"; args.append(source_id)
    if rule_key is not None:
        q+=" AND rule_key=?"; args.append(rule_key)
    q+=" ORDER BY reliability_observation_id"
    return con.execute(q,args).fetchall()

def upsert_source_reliability_profile(
    con, *, source_id,rule_key,score,band,critical_failure_count,
    success_count,observation_count,consecutive_success_count,
    last_critical_at,last_success_at,reasons):
    now=datetime.now(timezone.utc).isoformat()
    con.execute("""INSERT INTO source_reliability_profiles(
      source_id,rule_key,score,band,critical_failure_count,success_count,
      observation_count,consecutive_success_count,last_critical_at,last_success_at,
      reasons_json,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
      ON CONFLICT(source_id,rule_key) DO UPDATE SET
        score=excluded.score,band=excluded.band,
        critical_failure_count=excluded.critical_failure_count,
        success_count=excluded.success_count,
        observation_count=excluded.observation_count,
        consecutive_success_count=excluded.consecutive_success_count,
        last_critical_at=excluded.last_critical_at,
        last_success_at=excluded.last_success_at,
        reasons_json=excluded.reasons_json,updated_at=excluded.updated_at""",
      (source_id,rule_key,float(score),band,int(critical_failure_count),
       int(success_count),int(observation_count),int(consecutive_success_count),
       last_critical_at,last_success_at,json.dumps(reasons,ensure_ascii=False),now))
    con.commit()
    return con.execute("""SELECT * FROM source_reliability_profiles
                          WHERE source_id=? AND rule_key=?""",
                       (source_id,rule_key)).fetchone()

def source_reliability_profile_row(con,source_id,rule_key):
    return con.execute("""SELECT * FROM source_reliability_profiles
                          WHERE source_id=? AND rule_key=?""",
                       (source_id,rule_key)).fetchone()

def source_reliability_profile_rows(con,source_id=None):
    if source_id is None:
        return con.execute("""SELECT * FROM source_reliability_profiles
                              ORDER BY score,source_id,rule_key""").fetchall()
    return con.execute("""SELECT * FROM source_reliability_profiles
                          WHERE source_id=? ORDER BY score,rule_key""",
                       (source_id,)).fetchall()

def persist_preventive_verification_decision(
    con, *, decision_key,event_instance_id,source_id,rule_key,base_eligible,
    independent_source_count,human_confirmed,existing_verified,
    reliability_score,reliability_band,shadow_action,production_action,
    production_mode,canary_id,reasons):
    now=datetime.now(timezone.utc).isoformat()
    row=con.execute("""SELECT decision_id FROM preventive_verification_decisions
                       WHERE decision_key=?""",(decision_key,)).fetchone()
    if row:
        return row["decision_id"],False
    cur=con.execute("""INSERT INTO preventive_verification_decisions(
      decision_key,event_instance_id,source_id,rule_key,base_eligible,
      independent_source_count,human_confirmed,existing_verified,
      reliability_score,reliability_band,shadow_action,production_action,
      production_mode,canary_id,reasons_json,evaluated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (decision_key,event_instance_id,source_id,rule_key,int(base_eligible),
       int(independent_source_count),int(human_confirmed),int(existing_verified),
       float(reliability_score),reliability_band,shadow_action,production_action,
       production_mode,canary_id,json.dumps(reasons,ensure_ascii=False),now))
    con.commit()
    return cur.lastrowid,True

def preventive_verification_decision_rows(con,source_id=None):
    if source_id is None:
        return con.execute("""SELECT * FROM preventive_verification_decisions
                              ORDER BY decision_id""").fetchall()
    return con.execute("""SELECT * FROM preventive_verification_decisions
                          WHERE source_id=? ORDER BY decision_id""",
                       (source_id,)).fetchall()

def create_preventive_policy_canary(
    con, *, source_id,rule_key,max_decisions,approved_by,metadata=None):
    active=con.execute("""SELECT * FROM preventive_policy_canaries
      WHERE source_id=? AND rule_key=? AND status='ACTIVE'
      ORDER BY canary_id DESC LIMIT 1""",(source_id,rule_key)).fetchone()
    if active:
        return active["canary_id"],False
    now=datetime.now(timezone.utc).isoformat()
    cur=con.execute("""INSERT INTO preventive_policy_canaries(
      source_id,rule_key,status,max_decisions,used_decisions,approved_by,
      approved_at,metadata_json) VALUES(?,?,?,?,?,?,?,?)""",
      (source_id,rule_key,"ACTIVE",int(max_decisions),0,approved_by,now,
       json.dumps(metadata or {},ensure_ascii=False)))
    cid=cur.lastrowid
    con.execute("""INSERT INTO preventive_policy_canary_events(
      canary_id,event_type,actor,detail_json,created_at)
      VALUES(?,?,?,?,?)""",(cid,"CANARY_STARTED",approved_by,
       json.dumps({"max_decisions":int(max_decisions)},ensure_ascii=False),now))
    con.commit()
    return cid,True

def active_preventive_policy_canary(con,source_id,rule_key):
    return con.execute("""SELECT * FROM preventive_policy_canaries
      WHERE source_id=? AND rule_key=? AND status='ACTIVE'
      ORDER BY canary_id DESC LIMIT 1""",(source_id,rule_key)).fetchone()

def consume_preventive_policy_canary(con,canary_id,decision_id):
    row=con.execute("""SELECT * FROM preventive_policy_canaries
                       WHERE canary_id=?""",(canary_id,)).fetchone()
    if not row or row["status"]!="ACTIVE":
        return None
    now=datetime.now(timezone.utc).isoformat()
    used=row["used_decisions"]+1
    status="EXHAUSTED" if used>=row["max_decisions"] else "ACTIVE"
    ended=now if status=="EXHAUSTED" else None
    con.execute("""UPDATE preventive_policy_canaries
      SET used_decisions=?,status=?,ended_at=COALESCE(?,ended_at)
      WHERE canary_id=?""",(used,status,ended,canary_id))
    con.execute("""INSERT INTO preventive_policy_canary_events(
      canary_id,event_type,decision_id,actor,detail_json,created_at)
      VALUES(?,?,?,?,?,?)""",(canary_id,"DECISION_USED",decision_id,
       "preventive-policy",json.dumps({"used_decisions":used,"status":status},
       ensure_ascii=False),now))
    con.commit()
    return status

def rollback_preventive_policy_canary(con,canary_id,actor,reason):
    row=con.execute("""SELECT * FROM preventive_policy_canaries
                       WHERE canary_id=?""",(canary_id,)).fetchone()
    if not row:
        raise KeyError("preventive canary not found")
    now=datetime.now(timezone.utc).isoformat()
    con.execute("""UPDATE preventive_policy_canaries
      SET status='ROLLED_BACK',ended_at=?,rollback_reason=?
      WHERE canary_id=?""",(now,reason,canary_id))
    con.execute("""INSERT INTO preventive_policy_canary_events(
      canary_id,event_type,actor,detail_json,created_at)
      VALUES(?,?,?,?,?)""",(canary_id,"ROLLBACK",actor,
       json.dumps({"reason":reason},ensure_ascii=False),now))
    con.commit()

def preventive_policy_canary_rows(con):
    return con.execute("""SELECT * FROM preventive_policy_canaries
                          ORDER BY canary_id""").fetchall()

def preventive_policy_canary_event_rows(con,canary_id=None):
    if canary_id is None:
        return con.execute("""SELECT * FROM preventive_policy_canary_events
                              ORDER BY canary_event_id""").fetchall()
    return con.execute("""SELECT * FROM preventive_policy_canary_events
                          WHERE canary_id=? ORDER BY canary_event_id""",
                       (canary_id,)).fetchall()


def persist_preventive_policy_outcome(
    con, *, outcome_key,decision_id,event_instance_id,source_id,rule_key,
    policy_mode,base_action,preventive_action,event_truth,outcome_class,
    critical_prevented,false_conservative_hold,confirmed_by,rationale):
    now=datetime.now(timezone.utc).isoformat()
    row=con.execute("SELECT outcome_id FROM preventive_policy_outcomes WHERE outcome_key=?",
                    (outcome_key,)).fetchone()
    if row: return row["outcome_id"],False
    cur=con.execute("""INSERT INTO preventive_policy_outcomes(
      outcome_key,decision_id,event_instance_id,source_id,rule_key,policy_mode,
      base_action,preventive_action,event_truth,outcome_class,critical_prevented,
      false_conservative_hold,confirmed_by,rationale_json,observed_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (outcome_key,decision_id,event_instance_id,source_id,rule_key,policy_mode,
       base_action,preventive_action,event_truth,outcome_class,int(critical_prevented),
       int(false_conservative_hold),confirmed_by,json.dumps(rationale,ensure_ascii=False),now))
    con.commit(); return cur.lastrowid,True

def preventive_policy_outcome_rows(con,canary_id=None):
    q="""SELECT o.*,d.canary_id FROM preventive_policy_outcomes o
         JOIN preventive_verification_decisions d ON d.decision_id=o.decision_id"""
    args=[]
    if canary_id is not None:
        q+=" WHERE d.canary_id=?"; args.append(canary_id)
    q+=" ORDER BY o.outcome_id"
    return con.execute(q,args).fetchall()

def persist_preventive_canary_safety_evaluation(
    con, *, canary_id,sample_count,prevented_critical_count,
    false_conservative_hold_count,false_conservative_hold_rate,status,reasons):
    now=datetime.now(timezone.utc).isoformat()
    cur=con.execute("""INSERT INTO preventive_canary_safety_evaluations(
      canary_id,sample_count,prevented_critical_count,false_conservative_hold_count,
      false_conservative_hold_rate,status,reasons_json,evaluated_at)
      VALUES(?,?,?,?,?,?,?,?)""",
      (canary_id,sample_count,prevented_critical_count,false_conservative_hold_count,
       false_conservative_hold_rate,status,json.dumps(reasons,ensure_ascii=False),now))
    con.commit(); return cur.lastrowid

def preventive_canary_safety_rows(con,canary_id=None):
    if canary_id is None:
        return con.execute("""SELECT * FROM preventive_canary_safety_evaluations
                              ORDER BY evaluation_id""").fetchall()
    return con.execute("""SELECT * FROM preventive_canary_safety_evaluations
                          WHERE canary_id=? ORDER BY evaluation_id""",
                       (canary_id,)).fetchall()

def create_preventive_full_promotion(con, *, source_id,rule_key,canary_id,promoted_by,metadata=None):
    active=con.execute("""SELECT * FROM preventive_full_promotions
      WHERE source_id=? AND rule_key=? AND status='ACTIVE'
      ORDER BY promotion_id DESC LIMIT 1""",(source_id,rule_key)).fetchone()
    if active: return active["promotion_id"],False
    now=datetime.now(timezone.utc).isoformat()
    cur=con.execute("""INSERT INTO preventive_full_promotions(
      source_id,rule_key,canary_id,status,promoted_by,promoted_at,metadata_json)
      VALUES(?,?,?,?,?,?,?)""",(source_id,rule_key,canary_id,"ACTIVE",promoted_by,now,
       json.dumps(metadata or {},ensure_ascii=False)))
    con.commit(); return cur.lastrowid,True

def active_preventive_full_promotion(con,source_id,rule_key):
    return con.execute("""SELECT * FROM preventive_full_promotions
      WHERE source_id=? AND rule_key=? AND status='ACTIVE'
      ORDER BY promotion_id DESC LIMIT 1""",(source_id,rule_key)).fetchone()

def preventive_full_promotion_rows(con):
    return con.execute("SELECT * FROM preventive_full_promotions ORDER BY promotion_id").fetchall()

def rollback_preventive_full_promotion(con,promotion_id,actor,reason):
    now=datetime.now(timezone.utc).isoformat()
    con.execute("""UPDATE preventive_full_promotions SET status='ROLLED_BACK',
      ended_at=?,rollback_reason=? WHERE promotion_id=?""",(now,reason,promotion_id))
    con.commit()

def persist_preventive_final_review(con, *, canary_id,decision,reviewer,reason=None,promotion_id=None):
    now=datetime.now(timezone.utc).isoformat()
    cur=con.execute("""INSERT INTO preventive_final_reviews(
      canary_id,decision,reviewer,reason,promotion_id,reviewed_at)
      VALUES(?,?,?,?,?,?)""",(canary_id,decision,reviewer,reason,promotion_id,now))
    con.commit(); return cur.lastrowid

def preventive_final_review_rows(con,canary_id=None):
    if canary_id is None:
        return con.execute("SELECT * FROM preventive_final_reviews ORDER BY final_review_id").fetchall()
    return con.execute("""SELECT * FROM preventive_final_reviews
                          WHERE canary_id=? ORDER BY final_review_id""",(canary_id,)).fetchall()


def persist_preventive_full_runtime_observation(
    con, *, promotion_id,outcome_id,decision_id,outcome_class,
    missed_critical_failure,false_conservative_hold,critical_prevented):
    now=datetime.now(timezone.utc).isoformat()
    row=con.execute("""SELECT runtime_observation_id FROM preventive_full_runtime_observations
                       WHERE outcome_id=?""",(outcome_id,)).fetchone()
    if row: return row["runtime_observation_id"],False
    cur=con.execute("""INSERT INTO preventive_full_runtime_observations(
      promotion_id,outcome_id,decision_id,outcome_class,missed_critical_failure,
      false_conservative_hold,critical_prevented,observed_at)
      VALUES(?,?,?,?,?,?,?,?)""",
      (promotion_id,outcome_id,decision_id,outcome_class,int(missed_critical_failure),
       int(false_conservative_hold),int(critical_prevented),now))
    con.commit(); return cur.lastrowid,True

def preventive_full_runtime_observation_rows(con,promotion_id=None):
    if promotion_id is None:
        return con.execute("""SELECT * FROM preventive_full_runtime_observations
                              ORDER BY runtime_observation_id""").fetchall()
    return con.execute("""SELECT * FROM preventive_full_runtime_observations
                          WHERE promotion_id=? ORDER BY runtime_observation_id""",
                       (promotion_id,)).fetchall()

def persist_preventive_full_runtime_guard_evaluation(
    con, *, promotion_id,sample_count,recent5_sample_count,recent5_false_hold_rate,
    recent10_sample_count,recent10_false_hold_rate,missed_critical_count,
    prevented_critical_count,status,action,reasons):
    now=datetime.now(timezone.utc).isoformat()
    cur=con.execute("""INSERT INTO preventive_full_runtime_guard_evaluations(
      promotion_id,sample_count,recent5_sample_count,recent5_false_hold_rate,
      recent10_sample_count,recent10_false_hold_rate,missed_critical_count,
      prevented_critical_count,status,action,reasons_json,evaluated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
      (promotion_id,sample_count,recent5_sample_count,recent5_false_hold_rate,
       recent10_sample_count,recent10_false_hold_rate,missed_critical_count,
       prevented_critical_count,status,action,json.dumps(reasons,ensure_ascii=False),now))
    con.commit(); return cur.lastrowid

def preventive_full_runtime_guard_evaluation_rows(con,promotion_id=None):
    if promotion_id is None:
        return con.execute("""SELECT * FROM preventive_full_runtime_guard_evaluations
                              ORDER BY guard_evaluation_id""").fetchall()
    return con.execute("""SELECT * FROM preventive_full_runtime_guard_evaluations
                          WHERE promotion_id=? ORDER BY guard_evaluation_id""",
                       (promotion_id,)).fetchall()

def persist_preventive_full_runtime_guard_event(
    con, *, promotion_id,event_type,actor,detail,outcome_id=None):
    now=datetime.now(timezone.utc).isoformat()
    cur=con.execute("""INSERT INTO preventive_full_runtime_guard_events(
      promotion_id,event_type,outcome_id,actor,detail_json,created_at)
      VALUES(?,?,?,?,?,?)""",
      (promotion_id,event_type,outcome_id,actor,
       json.dumps(detail,ensure_ascii=False),now))
    con.commit(); return cur.lastrowid

def preventive_full_runtime_guard_event_rows(con,promotion_id=None):
    if promotion_id is None:
        return con.execute("""SELECT * FROM preventive_full_runtime_guard_events
                              ORDER BY guard_event_id""").fetchall()
    return con.execute("""SELECT * FROM preventive_full_runtime_guard_events
                          WHERE promotion_id=? ORDER BY guard_event_id""",
                       (promotion_id,)).fetchall()


def create_preventive_recovery_case(
    con, *, source_id,rule_key,failed_promotion_id,rollback_reason,metadata=None):
    row=con.execute("""SELECT recovery_case_id FROM preventive_recovery_cases
                       WHERE failed_promotion_id=?""",(failed_promotion_id,)).fetchone()
    if row: return row["recovery_case_id"],False
    now=datetime.now(timezone.utc).isoformat()
    cur=con.execute("""INSERT INTO preventive_recovery_cases(
      source_id,rule_key,failed_promotion_id,status,rollback_reason,opened_at,metadata_json)
      VALUES(?,?,?,?,?,?,?)""",
      (source_id,rule_key,failed_promotion_id,"OPEN",rollback_reason,now,
       json.dumps(metadata or {},ensure_ascii=False)))
    rid=cur.lastrowid
    con.execute("""INSERT INTO preventive_recovery_events(
      recovery_case_id,event_type,actor,detail_json,created_at)
      VALUES(?,?,?,?,?)""",(rid,"RECOVERY_OPENED","runtime-guard",
       json.dumps({"failed_promotion_id":failed_promotion_id,
                   "rollback_reason":rollback_reason},ensure_ascii=False),now))
    con.commit(); return rid,True

def preventive_recovery_case_row(con,recovery_case_id):
    return con.execute("""SELECT * FROM preventive_recovery_cases
                          WHERE recovery_case_id=?""",(recovery_case_id,)).fetchone()

def latest_preventive_recovery_case(con,source_id,rule_key):
    return con.execute("""SELECT * FROM preventive_recovery_cases
      WHERE source_id=? AND rule_key=? ORDER BY recovery_case_id DESC LIMIT 1""",
      (source_id,rule_key)).fetchone()

def preventive_recovery_case_rows(con,status=None):
    if status is None:
        return con.execute("""SELECT * FROM preventive_recovery_cases
                              ORDER BY recovery_case_id""").fetchall()
    return con.execute("""SELECT * FROM preventive_recovery_cases
                          WHERE status=? ORDER BY recovery_case_id""",(status,)).fetchall()

def update_preventive_recovery_root_cause(con,recovery_case_id,root_cause,actor):
    now=datetime.now(timezone.utc).isoformat()
    con.execute("""UPDATE preventive_recovery_cases
      SET root_cause=?,root_cause_by=?,root_cause_at=?,
          status=CASE WHEN remediation_ref IS NOT NULL THEN 'OBSERVING' ELSE 'ROOT_CAUSE_RECORDED' END
      WHERE recovery_case_id=?""",(root_cause,actor,now,recovery_case_id))
    con.execute("""INSERT INTO preventive_recovery_events(
      recovery_case_id,event_type,actor,detail_json,created_at)
      VALUES(?,?,?,?,?)""",(recovery_case_id,"ROOT_CAUSE_RECORDED",actor,
       json.dumps({"root_cause":root_cause},ensure_ascii=False),now))
    con.commit()

def update_preventive_recovery_remediation(
    con,recovery_case_id,remediation_ref,notes,actor):
    now=datetime.now(timezone.utc).isoformat()
    con.execute("""UPDATE preventive_recovery_cases
      SET remediation_ref=?,remediation_notes=?,remediation_by=?,remediation_at=?,
          status=CASE WHEN root_cause IS NOT NULL THEN 'OBSERVING' ELSE 'REMEDIATION_RECORDED' END
      WHERE recovery_case_id=?""",(remediation_ref,notes,actor,now,recovery_case_id))
    con.execute("""INSERT INTO preventive_recovery_events(
      recovery_case_id,event_type,actor,detail_json,created_at)
      VALUES(?,?,?,?,?)""",(recovery_case_id,"REMEDIATION_RECORDED",actor,
       json.dumps({"remediation_ref":remediation_ref,"notes":notes},ensure_ascii=False),now))
    con.commit()

def persist_preventive_recovery_evaluation(
    con, *, recovery_case_id,shadow_decision_count,confirmed_outcome_count,
    safe_outcome_count,missed_critical_count,false_conservative_hold_count,
    false_conservative_hold_rate,status,reasons):
    now=datetime.now(timezone.utc).isoformat()
    cur=con.execute("""INSERT INTO preventive_recovery_evaluations(
      recovery_case_id,shadow_decision_count,confirmed_outcome_count,safe_outcome_count,
      missed_critical_count,false_conservative_hold_count,false_conservative_hold_rate,
      status,reasons_json,evaluated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?)""",
      (recovery_case_id,shadow_decision_count,confirmed_outcome_count,safe_outcome_count,
       missed_critical_count,false_conservative_hold_count,false_conservative_hold_rate,
       status,json.dumps(reasons,ensure_ascii=False),now))
    if status=="READY_FOR_REQUALIFICATION":
        con.execute("""UPDATE preventive_recovery_cases
          SET status='READY_FOR_REQUALIFICATION',ready_at=COALESCE(ready_at,?)
          WHERE recovery_case_id=?""",(now,recovery_case_id))
    con.commit(); return cur.lastrowid

def preventive_recovery_evaluation_rows(con,recovery_case_id=None):
    if recovery_case_id is None:
        return con.execute("""SELECT * FROM preventive_recovery_evaluations
                              ORDER BY recovery_evaluation_id""").fetchall()
    return con.execute("""SELECT * FROM preventive_recovery_evaluations
                          WHERE recovery_case_id=? ORDER BY recovery_evaluation_id""",
                       (recovery_case_id,)).fetchall()

def mark_preventive_recovery_requalified(con,recovery_case_id,actor):
    now=datetime.now(timezone.utc).isoformat()
    con.execute("""UPDATE preventive_recovery_cases
      SET status='REQUALIFIED',requalified_by=?,requalified_at=?
      WHERE recovery_case_id=?""",(actor,now,recovery_case_id))
    con.execute("""INSERT INTO preventive_recovery_events(
      recovery_case_id,event_type,actor,detail_json,created_at)
      VALUES(?,?,?,?,?)""",(recovery_case_id,"HUMAN_REQUALIFIED",actor,
       json.dumps({},ensure_ascii=False),now))
    con.commit()

def preventive_recovery_event_rows(con,recovery_case_id=None):
    if recovery_case_id is None:
        return con.execute("""SELECT * FROM preventive_recovery_events
                              ORDER BY recovery_event_id""").fetchall()
    return con.execute("""SELECT * FROM preventive_recovery_events
                          WHERE recovery_case_id=? ORDER BY recovery_event_id""",
                       (recovery_case_id,)).fetchall()


def upsert_preventive_recurrence_profile(
    con, *, source_id,rule_key,recurrence_count,requalified_failure_count,
    repeated_root_cause_count,ineffective_remediation_count,risk_band,
    long_term_restricted,reasons):
    now=datetime.now(timezone.utc).isoformat()
    row=con.execute("""SELECT recurrence_profile_id FROM preventive_recurrence_profiles
                       WHERE source_id=? AND rule_key=?""",(source_id,rule_key)).fetchone()
    if row:
        con.execute("""UPDATE preventive_recurrence_profiles SET
          recurrence_count=?,requalified_failure_count=?,repeated_root_cause_count=?,
          ineffective_remediation_count=?,risk_band=?,long_term_restricted=?,
          reasons_json=?,updated_at=? WHERE recurrence_profile_id=?""",
          (recurrence_count,requalified_failure_count,repeated_root_cause_count,
           ineffective_remediation_count,risk_band,int(long_term_restricted),
           json.dumps(reasons,ensure_ascii=False),now,row["recurrence_profile_id"]))
        pid=row["recurrence_profile_id"]
    else:
        cur=con.execute("""INSERT INTO preventive_recurrence_profiles(
          source_id,rule_key,recurrence_count,requalified_failure_count,
          repeated_root_cause_count,ineffective_remediation_count,risk_band,
          long_term_restricted,reasons_json,updated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?)""",
          (source_id,rule_key,recurrence_count,requalified_failure_count,
           repeated_root_cause_count,ineffective_remediation_count,risk_band,
           int(long_term_restricted),json.dumps(reasons,ensure_ascii=False),now))
        pid=cur.lastrowid
    con.commit(); return pid

def preventive_recurrence_profile_row(con,source_id,rule_key):
    return con.execute("""SELECT * FROM preventive_recurrence_profiles
                          WHERE source_id=? AND rule_key=?""",(source_id,rule_key)).fetchone()

def preventive_recurrence_profile_rows(con):
    return con.execute("""SELECT * FROM preventive_recurrence_profiles
                          ORDER BY recurrence_profile_id""").fetchall()

def persist_preventive_recurrence_evaluation(
    con, *, recovery_case_id,source_id,rule_key,recurrence_count,
    repeated_root_cause,previous_remediation_ref,remediation_effective,
    required_shadow_decisions,required_confirmed_outcomes,max_false_hold_rate,
    human_exception_required,risk_band,reasons):
    now=datetime.now(timezone.utc).isoformat()
    cur=con.execute("""INSERT INTO preventive_recurrence_evaluations(
      recovery_case_id,source_id,rule_key,recurrence_count,repeated_root_cause,
      previous_remediation_ref,remediation_effective,required_shadow_decisions,
      required_confirmed_outcomes,max_false_hold_rate,human_exception_required,
      risk_band,reasons_json,evaluated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (recovery_case_id,source_id,rule_key,recurrence_count,int(repeated_root_cause),
       previous_remediation_ref,remediation_effective,required_shadow_decisions,
       required_confirmed_outcomes,max_false_hold_rate,int(human_exception_required),
       risk_band,json.dumps(reasons,ensure_ascii=False),now))
    con.commit(); return cur.lastrowid

def preventive_recurrence_evaluation_rows(con,recovery_case_id=None):
    if recovery_case_id is None:
        return con.execute("""SELECT * FROM preventive_recurrence_evaluations
                              ORDER BY recurrence_evaluation_id""").fetchall()
    return con.execute("""SELECT * FROM preventive_recurrence_evaluations
                          WHERE recovery_case_id=? ORDER BY recurrence_evaluation_id""",
                       (recovery_case_id,)).fetchall()

def persist_preventive_recurrence_exception(
    con, *, recovery_case_id,source_id,rule_key,decision,approved_by,reason):
    now=datetime.now(timezone.utc).isoformat()
    cur=con.execute("""INSERT INTO preventive_recurrence_exceptions(
      recovery_case_id,source_id,rule_key,decision,approved_by,reason,created_at)
      VALUES(?,?,?,?,?,?,?)""",
      (recovery_case_id,source_id,rule_key,decision,approved_by,reason,now))
    con.commit(); return cur.lastrowid

def latest_preventive_recurrence_exception(con,recovery_case_id):
    return con.execute("""SELECT * FROM preventive_recurrence_exceptions
      WHERE recovery_case_id=? ORDER BY exception_id DESC LIMIT 1""",
      (recovery_case_id,)).fetchone()

def preventive_recurrence_exception_rows(con,recovery_case_id=None):
    if recovery_case_id is None:
        return con.execute("""SELECT * FROM preventive_recurrence_exceptions
                              ORDER BY exception_id""").fetchall()
    return con.execute("""SELECT * FROM preventive_recurrence_exceptions
                          WHERE recovery_case_id=? ORDER BY exception_id""",
                       (recovery_case_id,)).fetchall()


def create_preventive_quarantine(
    con, *, source_id,rule_key,trigger_recovery_case_id,trigger_reason,metadata=None):
    active=con.execute("""SELECT quarantine_id FROM preventive_quarantines
      WHERE source_id=? AND rule_key=? AND status='ACTIVE'
      ORDER BY quarantine_id DESC LIMIT 1""",(source_id,rule_key)).fetchone()
    if active: return active["quarantine_id"],False
    now=datetime.now(timezone.utc).isoformat()
    cur=con.execute("""INSERT INTO preventive_quarantines(
      source_id,rule_key,trigger_recovery_case_id,status,trigger_reason,started_at,metadata_json)
      VALUES(?,?,?,?,?,?,?)""",
      (source_id,rule_key,trigger_recovery_case_id,"ACTIVE",trigger_reason,now,
       json.dumps(metadata or {},ensure_ascii=False)))
    qid=cur.lastrowid
    con.execute("""INSERT INTO preventive_quarantine_events(
      quarantine_id,event_type,actor,detail_json,created_at)
      VALUES(?,?,?,?,?)""",(qid,"QUARANTINE_STARTED","recurrence-guard",
       json.dumps({"trigger_recovery_case_id":trigger_recovery_case_id,
                   "trigger_reason":trigger_reason},ensure_ascii=False),now))
    con.commit(); return qid,True

def active_preventive_quarantine(con,source_id,rule_key):
    return con.execute("""SELECT * FROM preventive_quarantines
      WHERE source_id=? AND rule_key=? AND status='ACTIVE'
      ORDER BY quarantine_id DESC LIMIT 1""",(source_id,rule_key)).fetchone()

def latest_preventive_quarantine(con,source_id,rule_key):
    return con.execute("""SELECT * FROM preventive_quarantines
      WHERE source_id=? AND rule_key=? ORDER BY quarantine_id DESC LIMIT 1""",
      (source_id,rule_key)).fetchone()

def preventive_quarantine_rows(con,status=None):
    if status is None:
        return con.execute("""SELECT * FROM preventive_quarantines
                              ORDER BY quarantine_id""").fetchall()
    return con.execute("""SELECT * FROM preventive_quarantines
                          WHERE status=? ORDER BY quarantine_id""",(status,)).fetchall()

def persist_preventive_quarantine_event(
    con, *, quarantine_id,event_type,actor,detail):
    now=datetime.now(timezone.utc).isoformat()
    cur=con.execute("""INSERT INTO preventive_quarantine_events(
      quarantine_id,event_type,actor,detail_json,created_at)
      VALUES(?,?,?,?,?)""",(quarantine_id,event_type,actor,
       json.dumps(detail,ensure_ascii=False),now))
    con.commit(); return cur.lastrowid

def preventive_quarantine_event_rows(con,quarantine_id=None):
    if quarantine_id is None:
        return con.execute("""SELECT * FROM preventive_quarantine_events
                              ORDER BY quarantine_event_id""").fetchall()
    return con.execute("""SELECT * FROM preventive_quarantine_events
                          WHERE quarantine_id=? ORDER BY quarantine_event_id""",
                       (quarantine_id,)).fetchall()

def persist_preventive_reintegration_evaluation(
    con, *, quarantine_id,shadow_decision_count,confirmed_outcome_count,
    safe_outcome_count,missed_critical_count,false_hold_count,false_hold_rate,
    independent_alternative_count,elapsed_hours,recovery_requalified,status,reasons):
    now=datetime.now(timezone.utc).isoformat()
    cur=con.execute("""INSERT INTO preventive_reintegration_evaluations(
      quarantine_id,shadow_decision_count,confirmed_outcome_count,safe_outcome_count,
      missed_critical_count,false_hold_count,false_hold_rate,independent_alternative_count,
      elapsed_hours,recovery_requalified,status,reasons_json,evaluated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (quarantine_id,shadow_decision_count,confirmed_outcome_count,safe_outcome_count,
       missed_critical_count,false_hold_count,false_hold_rate,independent_alternative_count,
       elapsed_hours,int(recovery_requalified),status,
       json.dumps(reasons,ensure_ascii=False),now))
    con.commit(); return cur.lastrowid

def preventive_reintegration_evaluation_rows(con,quarantine_id=None):
    if quarantine_id is None:
        return con.execute("""SELECT * FROM preventive_reintegration_evaluations
                              ORDER BY reintegration_evaluation_id""").fetchall()
    return con.execute("""SELECT * FROM preventive_reintegration_evaluations
                          WHERE quarantine_id=? ORDER BY reintegration_evaluation_id""",
                       (quarantine_id,)).fetchall()

def release_preventive_quarantine(con,quarantine_id,reviewer,reason):
    now=datetime.now(timezone.utc).isoformat()
    con.execute("""UPDATE preventive_quarantines
      SET status='RELEASED',released_at=?,released_by=?,release_reason=?
      WHERE quarantine_id=? AND status='ACTIVE'""",
      (now,reviewer,reason,quarantine_id))
    persist_preventive_quarantine_event(
        con,quarantine_id=quarantine_id,event_type="QUARANTINE_RELEASED",
        actor=reviewer,detail={"reason":reason})
    con.commit()

def persist_preventive_quarantine_release_review(
    con, *, quarantine_id,decision,reviewer,reason,reintegration_evaluation_id):
    now=datetime.now(timezone.utc).isoformat()
    cur=con.execute("""INSERT INTO preventive_quarantine_release_reviews(
      quarantine_id,decision,reviewer,reason,reintegration_evaluation_id,reviewed_at)
      VALUES(?,?,?,?,?,?)""",
      (quarantine_id,decision,reviewer,reason,reintegration_evaluation_id,now))
    con.commit(); return cur.lastrowid

def preventive_quarantine_release_review_rows(con,quarantine_id=None):
    if quarantine_id is None:
        return con.execute("""SELECT * FROM preventive_quarantine_release_reviews
                              ORDER BY release_review_id""").fetchall()
    return con.execute("""SELECT * FROM preventive_quarantine_release_reviews
                          WHERE quarantine_id=? ORDER BY release_review_id""",
                       (quarantine_id,)).fetchall()


def persist_alternative_route_evaluation(
    con, *, trigger_decision_id,event_instance_id,quarantined_source_id,rule_key,
    candidate_decision_ids,selected_decision_ids,independence_groups,
    human_confirmed_route,safe_candidate_count,independent_group_count,
    route_status,production_recommendation,coverage_preserved,reasons):
    now=datetime.now(timezone.utc).isoformat()
    cur=con.execute("""INSERT INTO alternative_route_evaluations(
      trigger_decision_id,event_instance_id,quarantined_source_id,rule_key,
      candidate_decision_ids_json,selected_decision_ids_json,independence_groups_json,
      human_confirmed_route,safe_candidate_count,independent_group_count,
      route_status,production_recommendation,coverage_preserved,reasons_json,evaluated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (trigger_decision_id,event_instance_id,quarantined_source_id,rule_key,
       json.dumps(candidate_decision_ids,ensure_ascii=False),
       json.dumps(selected_decision_ids,ensure_ascii=False),
       json.dumps(independence_groups,ensure_ascii=False),
       int(human_confirmed_route),int(safe_candidate_count),int(independent_group_count),
       route_status,production_recommendation,int(coverage_preserved),
       json.dumps(reasons,ensure_ascii=False),now))
    con.commit(); return cur.lastrowid

def alternative_route_evaluation_rows(con,event_instance_id=None):
    if event_instance_id is None:
        return con.execute("""SELECT * FROM alternative_route_evaluations
                              ORDER BY route_evaluation_id""").fetchall()
    return con.execute("""SELECT * FROM alternative_route_evaluations
                          WHERE event_instance_id=? ORDER BY route_evaluation_id""",
                       (event_instance_id,)).fetchall()

def persist_alternative_route_event(
    con, *, route_evaluation_id,event_type,actor,detail):
    now=datetime.now(timezone.utc).isoformat()
    cur=con.execute("""INSERT INTO alternative_route_events(
      route_evaluation_id,event_type,actor,detail_json,created_at)
      VALUES(?,?,?,?,?)""",(route_evaluation_id,event_type,actor,
       json.dumps(detail,ensure_ascii=False),now))
    con.commit(); return cur.lastrowid

def alternative_route_event_rows(con,route_evaluation_id=None):
    if route_evaluation_id is None:
        return con.execute("""SELECT * FROM alternative_route_events
                              ORDER BY route_event_id""").fetchall()
    return con.execute("""SELECT * FROM alternative_route_events
                          WHERE route_evaluation_id=? ORDER BY route_event_id""",
                       (route_evaluation_id,)).fetchall()

def persist_verification_continuity_snapshot(
    con, *, source_id,rule_key,quarantined_decision_count,routed_verified_count,
    degraded_possible_count,no_safe_route_count,coverage_preservation_rate):
    now=datetime.now(timezone.utc).isoformat()
    cur=con.execute("""INSERT INTO verification_continuity_snapshots(
      source_id,rule_key,quarantined_decision_count,routed_verified_count,
      degraded_possible_count,no_safe_route_count,coverage_preservation_rate,measured_at)
      VALUES(?,?,?,?,?,?,?,?)""",
      (source_id,rule_key,quarantined_decision_count,routed_verified_count,
       degraded_possible_count,no_safe_route_count,coverage_preservation_rate,now))
    con.commit(); return cur.lastrowid

def verification_continuity_snapshot_rows(con,source_id=None):
    if source_id is None:
        return con.execute("""SELECT * FROM verification_continuity_snapshots
                              ORDER BY continuity_snapshot_id""").fetchall()
    return con.execute("""SELECT * FROM verification_continuity_snapshots
                          WHERE source_id=? ORDER BY continuity_snapshot_id""",
                       (source_id,)).fetchall()


def upsert_source_relationship(
    con, *, source_id_a,source_id_b,relationship_type,confidence,
    provenance,reviewed_by=None,reason=None):
    if source_id_a==source_id_b:
        raise ValueError("source relationship requires two distinct sources")
    a,b=sorted((source_id_a,source_id_b))
    now=datetime.now(timezone.utc).isoformat()
    row=con.execute("""SELECT relationship_id FROM source_relationships
                       WHERE source_id_a=? AND source_id_b=?""",(a,b)).fetchone()
    if row:
        con.execute("""UPDATE source_relationships SET relationship_type=?,confidence=?,
          provenance=?,reviewed_by=?,reason=?,updated_at=? WHERE relationship_id=?""",
          (relationship_type,confidence,provenance,reviewed_by,reason,now,row["relationship_id"]))
        rid=row["relationship_id"]
    else:
        cur=con.execute("""INSERT INTO source_relationships(
          source_id_a,source_id_b,relationship_type,confidence,provenance,
          reviewed_by,reason,created_at,updated_at)
          VALUES(?,?,?,?,?,?,?,?,?)""",
          (a,b,relationship_type,confidence,provenance,reviewed_by,reason,now,now))
        rid=cur.lastrowid
    con.commit(); return rid

def source_relationship_row(con,source_id_a,source_id_b):
    if source_id_a==source_id_b:
        return None
    a,b=sorted((source_id_a,source_id_b))
    return con.execute("""SELECT * FROM source_relationships
                          WHERE source_id_a=? AND source_id_b=?""",(a,b)).fetchone()

def source_relationship_rows(con):
    return con.execute("""SELECT * FROM source_relationships ORDER BY relationship_id""").fetchall()

def upsert_evidence_origin_fingerprint(
    con, *, event_instance_id,source_id,content_hash=None,poster_hash=None,
    canonical_url=None,origin_source_id=None,fingerprint_method="MANUAL_OR_DERIVED"):
    now=datetime.now(timezone.utc).isoformat()
    row=con.execute("""SELECT fingerprint_id FROM evidence_origin_fingerprints
                       WHERE event_instance_id=? AND source_id=?""",
                    (event_instance_id,source_id)).fetchone()
    if row:
        con.execute("""UPDATE evidence_origin_fingerprints SET
          content_hash=?,poster_hash=?,canonical_url=?,origin_source_id=?,
          fingerprint_method=?,observed_at=? WHERE fingerprint_id=?""",
          (content_hash,poster_hash,canonical_url,origin_source_id,
           fingerprint_method,now,row["fingerprint_id"]))
        fid=row["fingerprint_id"]
    else:
        cur=con.execute("""INSERT INTO evidence_origin_fingerprints(
          event_instance_id,source_id,content_hash,poster_hash,canonical_url,
          origin_source_id,fingerprint_method,observed_at)
          VALUES(?,?,?,?,?,?,?,?)""",
          (event_instance_id,source_id,content_hash,poster_hash,canonical_url,
           origin_source_id,fingerprint_method,now))
        fid=cur.lastrowid
    con.commit(); return fid

def evidence_origin_fingerprint_row(con,event_instance_id,source_id):
    return con.execute("""SELECT * FROM evidence_origin_fingerprints
      WHERE event_instance_id=? AND source_id=?""",(event_instance_id,source_id)).fetchone()

def evidence_origin_fingerprint_rows(con,event_instance_id=None):
    if event_instance_id is None:
        return con.execute("""SELECT * FROM evidence_origin_fingerprints
                              ORDER BY fingerprint_id""").fetchall()
    return con.execute("""SELECT * FROM evidence_origin_fingerprints
      WHERE event_instance_id=? ORDER BY fingerprint_id""",(event_instance_id,)).fetchall()

def persist_source_independence_evaluation(
    con, *, event_instance_id,source_id_a,source_id_b,relationship_type,
    independence_status,relationship_evidence,syndication_signals,reasons):
    now=datetime.now(timezone.utc).isoformat()
    cur=con.execute("""INSERT INTO source_independence_evaluations(
      event_instance_id,source_id_a,source_id_b,relationship_type,
      independence_status,relationship_evidence_json,syndication_signals_json,
      reasons_json,evaluated_at)
      VALUES(?,?,?,?,?,?,?,?,?)""",
      (event_instance_id,source_id_a,source_id_b,relationship_type,
       independence_status,json.dumps(relationship_evidence,ensure_ascii=False),
       json.dumps(syndication_signals,ensure_ascii=False),
       json.dumps(reasons,ensure_ascii=False),now))
    con.commit(); return cur.lastrowid

def source_independence_evaluation_rows(con,event_instance_id=None):
    if event_instance_id is None:
        return con.execute("""SELECT * FROM source_independence_evaluations
                              ORDER BY independence_evaluation_id""").fetchall()
    return con.execute("""SELECT * FROM source_independence_evaluations
      WHERE event_instance_id=? ORDER BY independence_evaluation_id""",
      (event_instance_id,)).fetchall()

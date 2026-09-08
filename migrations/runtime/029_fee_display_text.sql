-- DanceMate v0.85.9 - Event Time Range + Conditional Fee Display.
--
-- A single post can name more than one real price under one condition
-- ("입장료 : 8천원 (10시 이후 5천원)") or as genuinely separate options
-- ("예매 15,000원 / 현매 20,000원"). `events.fee` stays a plain integer -
-- the one number a search/sort can compare - and this column carries the
-- full meaning alongside it: "8,000원 (22시 이후 5,000원)" for a conditional
-- fee, "예매 15,000원 · 현매 20,000원" (or "가격 옵션 있음") for a genuine
-- multi-option one. NULL for an ordinary single price, where `fee` alone
-- already says everything (Section 11-19 of the v0.85.9 task).
--
-- Mirrors engine/src/database.py's own event_candidates.fee_display_text
-- (added the same release) one column at a time across the hybrid
-- persistence boundary - see runtime/normalization.py's normalize_candidate().

ALTER TABLE events ADD COLUMN IF NOT EXISTS fee_display_text TEXT;

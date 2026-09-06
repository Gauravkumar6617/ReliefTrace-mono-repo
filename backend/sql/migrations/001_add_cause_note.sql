-- Migration 001: split the free-text "cause / note" out of DONOR_ORG.
--
-- Before this, the public form had a single "name or organization" field, so
-- values like "assam flood" or "Nepal relief  you@example.org" ended up in
-- RELIEF_DELIVERIES.DONOR_ORG. The form now has three separate fields
-- (donor_org, cause_note, donor_email); this adds the column they need.
--
-- Run in a Snowsight worksheet against RELIEFTRACE_DB.

USE DATABASE RELIEFTRACE_DB;
USE SCHEMA PUBLIC;

ALTER TABLE RELIEF_DELIVERIES ADD COLUMN IF NOT EXISTS CAUSE_NOTE STRING;

-- ---------------------------------------------------------------------------
-- OPTIONAL historical cleanup. Inspect first - these are heuristics, not safe
-- to run blind. Comment out what you don't want.
-- ---------------------------------------------------------------------------

-- 1. An email address got pasted into the org field: strip it back out.
--    SELECT DELIVERY_ID, DONOR_ORG FROM RELIEF_DELIVERIES WHERE DONOR_ORG RLIKE '.*\\S+@\\S+.*';
-- UPDATE RELIEF_DELIVERIES
--    SET DONOR_ORG = NULLIF(TRIM(REGEXP_REPLACE(DONOR_ORG, '\\S+@\\S+', '')), '')
--  WHERE DONOR_ORG RLIKE '.*\\S+@\\S+.*';

-- 2. DONOR_ORG actually holds a cause/disaster name, not an org. Build the list
--    from a manual review of:
--    SELECT DISTINCT DONOR_ORG FROM RELIEF_DELIVERIES WHERE SOURCE = 'public' ORDER BY 1;
-- UPDATE RELIEF_DELIVERIES
--    SET CAUSE_NOTE = DONOR_ORG,
--        DONOR_ORG  = '(unspecified)'
--  WHERE LOWER(DONOR_ORG) IN ('assam flood', 'assam flood relief', 'kerala relief');

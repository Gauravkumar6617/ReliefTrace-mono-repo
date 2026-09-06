-- Migration 002: units + affected-population on RELIEF_REQUESTS.
--
-- The need side is no longer Faker-random. It is now computed from real
-- affected-population figures for 15 districts hit by the 2024 Assam floods
-- and the 2025 Punjab floods, using Sphere Handbook (2018) minimum standards.
-- Different resources are measured in different units, so each request row
-- now carries its UNIT, and AFFECTED_POPULATION is denormalised on so the
-- dashboard can show a real "people affected" headline.
--
-- Run in a Snowsight worksheet against RELIEFTRACE_DB, then re-run
--   python -m scripts.generate_data && python -m scripts.load_to_snowflake
-- which TRUNCATEs and reloads RELIEF_REQUESTS only (deliveries are untouched -
-- they come from live submissions).

USE DATABASE RELIEFTRACE_DB;
USE SCHEMA PUBLIC;

ALTER TABLE RELIEF_REQUESTS ADD COLUMN IF NOT EXISTS UNIT STRING;                 -- litres | kg | kits | tents | sets
ALTER TABLE RELIEF_REQUESTS ADD COLUMN IF NOT EXISTS AFFECTED_POPULATION NUMBER;  -- people affected in that district

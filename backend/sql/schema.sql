-- Run this in Snowsight (as a role that can create databases/warehouses),
-- against the account that owns warehouse GENEROSITY_WH.

CREATE DATABASE IF NOT EXISTS RELIEFTRACE_DB;
USE DATABASE RELIEFTRACE_DB;
USE SCHEMA PUBLIC;

CREATE TABLE IF NOT EXISTS RELIEF_REQUESTS (
    REQUEST_ID          STRING PRIMARY KEY,
    ZONE_NAME            STRING NOT NULL,
    RESOURCE_TYPE        STRING NOT NULL,
    QUANTITY_NEEDED       NUMBER NOT NULL,
    QUANTITY_FULFILLED     NUMBER NOT NULL DEFAULT 0,
    URGENCY_LEVEL        STRING NOT NULL,  -- low / medium / critical
    REQUEST_DATE         DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS RELIEF_DELIVERIES (
    DELIVERY_ID   STRING PRIMARY KEY,
    -- nullable: synthetic deliveries link to a seeded request; public
    -- contributions submitted through the dashboard have no request row.
    REQUEST_ID    STRING REFERENCES RELIEF_REQUESTS(REQUEST_ID),
    ZONE_NAME      STRING NOT NULL,
    DONOR_ORG      STRING NOT NULL,
    DONOR_EMAIL    STRING,          -- collected from the public form; never sent anywhere
    CAUSE_NOTE     STRING,          -- optional free text, e.g. "assam flood relief drive"
    RESOURCE_TYPE  STRING NOT NULL,
    QUANTITY_SENT  NUMBER NOT NULL,
    DELIVERY_DATE  DATE NOT NULL,
    SOLANA_TX_SIG  STRING,
    -- 'seed' for synthetic rows, 'public' for dashboard submissions
    SOURCE         STRING NOT NULL DEFAULT 'seed'
);

-- Grant the app's connecting role/user access if it isn't already the owner:
-- GRANT USAGE ON DATABASE RELIEFTRACE_DB TO ROLE <role>;
-- GRANT USAGE ON SCHEMA RELIEFTRACE_DB.PUBLIC TO ROLE <role>;
-- GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA RELIEFTRACE_DB.PUBLIC TO ROLE <role>;
-- GRANT USAGE ON WAREHOUSE GENEROSITY_WH TO ROLE <role>;

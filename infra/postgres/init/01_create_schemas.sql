-- Medallion layers as separate schemas in one Postgres instance:
-- raw = append-only ingest landing zone, staging = dbt cleaning views, marts = Kimball star schema.
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS marts;

-- ============================================================
-- Rover Mars — Database Initialization
-- Creates dual-database setup: rover_mars + airflow
-- ============================================================

-- Create Airflow database
SELECT 'CREATE DATABASE airflow'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'airflow')\gexec

-- Switch to rover_mars (default DATABASE set in compose)
\connect rover_mars

-- Enable PostGIS extension for geospatial data
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- For text search on product IDs

-- Verify PostGIS
SELECT PostGIS_Version();

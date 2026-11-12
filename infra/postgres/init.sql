-- MangaPoisk Reborn — bootstrap databases.
-- Runs once, as the postgres superuser, on an empty data directory.

CREATE DATABASE catalog;
CREATE DATABASE library;
CREATE DATABASE control;

\connect catalog
CREATE EXTENSION IF NOT EXISTS pg_trgm;
-- Application-level normalization is accent-insensitive already; unaccent is
-- kept for SQL diagnostics and future direct queries.
CREATE EXTENSION IF NOT EXISTS unaccent;

\connect library
CREATE EXTENSION IF NOT EXISTS pg_trgm;

\connect control
CREATE EXTENSION IF NOT EXISTS pg_trgm;

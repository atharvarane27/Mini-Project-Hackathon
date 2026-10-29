# Supabase infrastructure

Structure only; no project has been provisioned or connected.

FastAPI and the worker will connect through SQLAlchemy and psycopg. Obtain endpoint and SSL settings from the project dashboard and populate environment configuration locally. Alembic owns application schema; bootstrap.sql is reserved for controlled role grants and optional policies. Runtime credentials should be separate from migration ownership. No browser service-role key is required.

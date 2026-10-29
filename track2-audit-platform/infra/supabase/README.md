# Supabase Managed PostgreSQL Provisioning Guide

This guide details configuring and connecting Supabase PostgreSQL for the Track 2 AuditForge Platform.

---

## 1. Project Creation & Connection Strings

1. Create a new PostgreSQL database at [database.new](https://database.new) or via your Supabase organization dashboard.
2. Navigate to **Project Settings** $\to$ **Database** $\to$ **Connection string**.
3. Select **URI** mode with `psycopg` dialect:
   - **Session Pooler (Recommended for containerized API & Worker)**:
     ```text
     postgresql+psycopg://postgres.[PROJECT_REF]:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres?sslmode=require
     ```
   - **Direct Session (For Alembic migrations and direct IPv6 setups)**:
     ```text
     postgresql+psycopg://postgres:[PASSWORD]@db.[PROJECT_REF].supabase.co:5432/postgres?sslmode=require
     ```

> [!IMPORTANT]
> Always verify endpoint, port, and SSL settings from your live dashboard. Never hardcode credentials in code or repository files.

---

## 2. Environment Configuration

Add the connection URI to your local `.env` file (which is git-ignored):

```bash
DB_BACKEND=supabase
DATABASE_URL=postgresql+psycopg://postgres.[PROJECT_REF]:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres?sslmode=require
DATABASE_POOL_SIZE=5
DATABASE_MAX_OVERFLOW=5
DATABASE_POOL_TIMEOUT=30
DATABASE_POOL_RECYCLE=1800
```

---

## 3. Running Migrations & Bootstrap

1. **Apply Application Schema Migrations**:
   Run Alembic from the `backend/` directory:
   ```bash
   cd backend
   alembic upgrade head
   ```

2. **Execute Database Bootstrap (Append-Only & Security Triggers)**:
   In Supabase Dashboard **SQL Editor**, execute [`bootstrap.sql`](file:///Users/shubham/Desktop/Mini-Project-Hackathon/track2-audit-platform/infra/supabase/bootstrap.sql).
   This script:
   - Enables `uuid-ossp` and `pgcrypto` extensions.
   - Attaches `prevent_activity_log_tampering` trigger to `activity_log` to reject `UPDATE`, `DELETE`, and `TRUNCATE` operations at the database level.
   - Revokes mutating permissions on audit history from standard client roles.

---

## 4. Local Offline Fallback

For environments without internet connectivity:
```bash
docker compose --profile local-postgres up -d
```
This spins up a local PostgreSQL 16 Alpine container with identical extensions and runs Alembic migrations automatically.

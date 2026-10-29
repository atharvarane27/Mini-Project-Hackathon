# Architecture

Next.js frontend -> FastAPI -> Supabase PostgreSQL and durable outbox -> one worker process with bounded threads. Engines own business algorithms; services own database transactions; worker owns concurrency.

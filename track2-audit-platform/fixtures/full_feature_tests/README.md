# Four full-feature CSV scenarios

Synthetic data only. Upload these files through Ingestion, using `qa-upload`
as the form source name. Each row supplies its own source system. Each file
works independently; distinct account/reference prefixes also allow all four
to coexist. Use a fresh API runtime for the first-import counts below.

| File | UTC date | Rows | Accepted | Rejected | Replays | Canonical events | Valid cycles | Splitting windows |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `01_baseline.csv` | 2026-10-26 | 22 | 21 | 0 | 1 | 19 | 1 | 1 |
| `02_boundary.csv` | 2026-10-27 | 28 | 27 | 0 | 1 | 25 | 1 | 1 |
| `03_multiple_patterns.csv` | 2026-10-28 | 29 | 28 | 0 | 1 | 26 | 2 | 2 |
| `04_validation.csv` | 2026-10-29 | 33 | 21 | 11 | 1 | 19 | 1 | 1 |

Counts were checked against the current backend ingestion/runtime,
canonicalization, circular validation, splitting window, and reconciliation
implementations using policy version 1. Browser interaction was not tested.

## Scenarios in every file

- Same economic event under different source IDs and across ledgers, exercising
  duplicate evidence and canonical provenance without double counting.
- One identical source row replay, plus a pair of similar references (`NEAR`).
- A matched ledger pair (`MATCH`), amount mismatch (`AMOUNT`), receiver mismatch
  (`FIELD`), internal-only transfer (`LEFT`), and clearing-only transfer (`RIGHT`).
- A three-account circular transfer (`CYCLE`), with amounts 2,000, 1,900, 1,800 INR.
- Three transfers from one sender (`SPLIT`) totaling at least 100,000 INR.
- A below-threshold group (`LOW`) and an ordinary transfer (`NORMAL`).

The boundary file includes a split totaling exactly 100,000 INR with its last
transfer exactly 60 minutes after its first. It also contains a rejected cycle
whose last amount is 1,799.99 INR (outside the 10% tolerance), and a transfer
group spread over 61 minutes that must not produce a splitting window.

The multiple-patterns file adds a four-account cycle and a separate splitting
group. The validation file adds one changed-payload source revision conflict
and ten invalid rows: negative, zero, nonnumeric and overprecision amounts;
timezone-free and malformed timestamps; invalid currency length, revision,
posting direction and missing sender. Expect 11 quarantined rows in total.

## Run through the application

1. Upload a file and compare the ingestion counts with the table. Inspect
   Transactions and Duplicates for canonical links and comparison evidence.
   Replay counts describe ingestion, not the number of duplicate comparisons.
2. Reconcile `qa1-internal` against `qa1-clearing` for file 1; use `qa2`, `qa3`
   or `qa4` for the other files. Select a range covering the file's UTC date.
   All files produce one MATCHED, one AMOUNT_MISMATCH, one FIELD_MISMATCH and
   one COUNTERPART_ONLY result. With a cutoff of 2026-10-31T00:00:00Z, expected
   INTERNAL_ONLY counts are respectively 13, 19, 20 and 13. Earlier cutoffs can
   classify recent unmatched entries as PENDING_LATE.
3. Run circular and splitting detectors with policy version 1 and the file's
   full UTC day. Inspect Findings and their transaction evidence. If entering
   local times, convert from the CSV's UTC timestamps.
4. Use the resulting facts/findings to exercise rule draft, validation,
   activation and evaluation in the Rules interface. Create cases from the
   results, then test prioritization, claiming and lifecycle actions.
5. Create a workflow with a prerequisite and a dependent task. Complete the
   prerequisite and check that the dependent task unlocks. Try a cyclic
   dependency separately and confirm rejection. Inspect Activity/Audit Log
   for the actions that the application records.
6. Upload the same file again using a new request/idempotency key. Previously
   accepted rows should be counted as replays; invalid rows remain rejected.
   Reusing the original idempotency key returns the original completed job.

CSV supplies transaction data; it cannot itself create rule definitions,
case claims, workflow dependencies, authentication sessions or stress tests.
Those features require the actions above or dedicated API/tests. Imported
transfers generate balanced journals automatically, so unbalanced-journal
negative tests also require a separate journal fixture/API test. These small
files do not test production persistence, concurrency or load capacity.

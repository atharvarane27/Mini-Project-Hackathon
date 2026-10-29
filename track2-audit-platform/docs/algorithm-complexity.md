# Algorithm complexity

## P09 circular temporal validation

Each candidate with `L` transfers is validated in `O(L)` time and `O(L)`
evidence space. A run over `C` candidates and `T` total candidate transfers is
`O(T + C log C)` because canonical candidate digests are sorted for stable run
identity. Policy path-length bounds cap per-candidate work.

## P10 transaction splitting

For `N` input canonical transfers, eligibility filtering and exact replay
deduplication take expected `O(N)` time and `O(N)` batch memory using a map keyed
by canonical transaction ID. A conflicting payload under the same canonical ID
is rejected rather than selected by arrival order.

Eligible events are partitioned by a versioned key. Currency is always included;
the remaining grouping can be sender, sender/receiver, or
sender/receiver/transaction-type. Historical partitions are sorted by UTC
timestamp and transaction ID, costing `O(sum(Kp log Kp))`, bounded by
`O(N log N)`. Each sorted partition then uses a deque, two pointers, and a
running integer-minor-unit sum for an `O(Kp)` scan.

For already ordered streaming input, insertion and time eviction are amortized
`O(1)` per event. The inclusive boundary evicts only when `new_time - old_time`
is greater than the configured window. A late event raises `OutOfOrderEvent` so
the caller can recompute that partition from its checkpoint; it is never
silently ignored. Exact replays are counted once, and reversal handling is an
explicit policy.

Active-window memory is `O(W)` per partition, where `W` is the number of events
inside the configured interval. `max_window_events` provides a hard bound and
raises a controlled error rather than discarding financial data. Emitting a
candidate copies its contributing IDs, so output construction costs `O(W)` per
candidate; P11 owns deterministic overlap suppression and finding fingerprints.

Measured benchmarks remain a P20 deliverable.

## P11 splitting findings and orchestration

Let `C` be the number of qualifying P10 candidate windows and `T` the number of
distinct transaction IDs represented by them. Overlap suppression uses a
union-find per partition. Its union/find work is effectively
`O(T α(T))`; ordering the final clusters for deterministic evidence costs
`O(T log T)` in the general case. Fingerprint and evidence construction are
linear in the number of contributing transactions.

Run identity is derived from detector type, algorithm version, policy version,
and snapshot checkpoint. A separate SHA-256 input digest covers the complete
normalized policy and unique canonical transaction payloads. Exact replays and
input ordering therefore do not change a retry, while changed input under an
already-completed run key is rejected as a conflict.

The repository boundary commits a run, fingerprint-deduplicated findings, and
run/finding associations as one operation. The included in-memory adapter uses
one lock to test this contract under concurrent retries; the Supabase adapter
must implement the same boundary with one database transaction and unique
constraints. The stress fixture verifies 2,000 independent partitions and 50
concurrent retries without asserting an unmeasured production latency target.

## P12 rule lexer

The custom lexer examines every input character at most a constant number of
times, so tokenization is `O(L)` for expression length `L`. Token storage is
`O(T)` for `T` emitted tokens. The default 4,096-character input limit and
64-level parenthesis limit bound work before P13 parsing. Numeric conversion
uses arbitrary-size integers or exact `Decimal`; no floating-point conversion,
regular-expression backtracking, or dynamic execution occurs.

## P13 rule parser

Recursive-descent parsing consumes each token once, giving `O(T)` parse time for
`T` tokens. AST storage is `O(T)`. Logical chains are constructed iteratively;
`NOT` and grouped-expression recursion are bounded, and final AST depth is
measured with an iterative traversal. The defaults cap input at 2,048 tokens
and depth 64 before P14 evaluation.

## P14 rule evaluation

Evaluation visits at most every AST node once, so runtime is `O(A)` for `A` AST
nodes and less when Boolean short-circuiting skips a branch. Explanation output
and the relevant-facts snapshot use `O(A + F)` memory for visited nodes and `F`
referenced fields. Priority calculation uses a fixed set of integer/Boolean
inputs and is `O(1)`. The repository port persists activation/version changes
and each evaluation atomically; database index costs belong to the merged P02
adapter rather than the pure evaluator.

## P15 binary heap and synchronized queue

The custom max heap uses an array plus a case-ID-to-index map. Push, pop,
arbitrary removal, and versioned priority update are `O(log N)`; peek, size, and
membership are `O(1)`. Invariant validation is `O(N)` and intended for tests or
controlled diagnostics. Storage is `O(N)`.

The synchronized wrapper adds one mutex acquisition per public operation.
Condition waiting does not poll: consumers sleep until notification, timeout,
or shutdown. Metrics are updated inside the same critical section. The stress
fixture exercises 5,000 unique cases with 25 producer and 25 consumer threads,
plus 1,000 concurrent priority replacements; these are correctness loads, not
claimed production latency benchmarks.

Other engine complexity notes will be added in their respective phases.

## P16 durable case orchestration

Stable case-key construction sorts `F` unique finding IDs and is `O(F log F)`;
hashing the canonical payload is linear in its encoded length. Case claim and
transition are constant-size compare-and-swap operations at the service layer;
production cost depends on the P02 unique/primary-key indexes.

For a poll batch of `B`, projection performs at most one indexed heap mutation
per event, so application work is `O(B log N)` for `N` queued cases. Restart
rebuild over `C` durable queued cases is `O(C log C)` with sequential heap
inserts. The reference adapter scans/sorts in memory for deterministic tests;
the production adapter must use indexed availability/lease columns and bounded
`FOR UPDATE SKIP LOCKED` batches. Retry count and lease durations are bounded;
there is no unbounded retry loop.

## P17 workflow DAG

Adjacency construction and DFS cycle detection are `O(V + E)`. Kahn ordering
is `O((V + E) log V)` because a lexical heap makes equal-choice output
deterministic. Instance storage is `O(V)`; dependency unlock checks are bounded
by the template edge set and run atomically in the repository transaction.

# Algorithm complexity

## Identity index and blocking

The application-owned inverted index and exact blocking logic avoid an all-pairs comparison in the lookup path. For a query record with token set T and posting-list sizes |P(t)|, candidate retrieval is bounded by:

- O(sum_{t in T} |P(t)|)

This is far below the naive all-pairs cost:

- O(N^2) when every record must be compared against every other record

In balanced fixtures, candidate counts remain close to the selective window created by token overlap, not the full population size. The P05 index therefore keeps the comparison workload dominated by the blocking fan-out rather than by full corpus scanning.

## Edit-distance classification

The P06 resolver only compares candidate pairs returned by the blocking layer. If the blocking stage yields C candidate records for one query, the resolver performs:

- O(C * L^2)

where L is the average string length of the compared text field. This is still significantly smaller than O(N^2) when C << N, and it preserves auditability because every comparison remains tied to a concrete candidate pair and evidence record.

## Worst-case skew and bounded fallback

Skew remains possible when a very common token or amount bucket dominates a partition. In that degenerate case, the candidate set can still grow toward O(N), but it does not require an all-pairs scan and remains bounded by the obstructing bucket fan-out. The algorithm is therefore deterministic and auditable, while admitting that adversarial skew can increase the candidate set.

## Evidence and auditability

Each result records:

- the compared attributes,
- the edit distance and similarity score,
- the candidate record IDs,
- the algorithm version,
- the decision reason.

This preserves full traceability without destroying source records or relying on probability-based confidence scores.

## Circular transfer graph and cycle detection

The circular-transfer layer is intentionally separate from the workflow DAG. The graph is a custom directed multigraph over posted transfer edges only, with one adjacency list per sender account and parallel edges preserved by distinct transaction IDs. This avoids conflating transfer-flow analysis with workflow dependency ordering.

For a graph with V nodes and E directed transfer edges, the adjacency-list representation supports:

- adjacency lookup: O(1) average per node
- sequential traversal of outgoing edges: O(out_degree(node))
- total memory: O(V + E)

The DFS cycle detector uses recursion-stack coloring (WHITE/GRAY/BLACK) to detect back-edges and simple cycles. In the normal case, a bounded search explores only the reachable subgraph within the configured depth and time window. The complexity is therefore:

- O(V + E) for the reachable DFS subgraph under the configured bounds
- plus the cost of cycle post-processing and deduplication

This is bounded by the application constraints:

- max_hops limits the path length and prevents unbounded simple-cycle enumeration
- max_window_minutes drops edges whose timestamps fall outside the allowed cycle window
- candidate_cap truncates the number of emitted cycle candidates

The detector also canonicalizes each found cycle by rotating it to its lexicographically smallest node ordering and deduplicates repeated cycle signatures, avoiding duplicate results from multiple traversal entry points or parallel edges.

## Practical upper bound

Even in a dense graph, the cycle detector remains governed by the configured search window rather than unrestricted graph traversal. In the worst case, the algorithm can still encounter an exponential number of simple cycles if the graph is unbounded and the search is unconstrained. The project therefore enforces hard limits to keep the search deterministic, explainable, and operationally safe.

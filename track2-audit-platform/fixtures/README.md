# Frozen synthetic fixtures

These files contain synthetic data only. `circular_transfers.csv` and
`splitting_transfers.csv` have deterministic positive and negative scenarios;
`expected_findings.json` freezes the three currently supported expected
findings. `rule_lexer_cases.json` freezes valid and invalid language examples.

The reconciliation ledger files cover exact matching, a 50,000-minor-unit
variance, left-only, right-only and pending-late examples.

Connected UI test uploads use `test_duplicates.csv`,
`test_reconciliation_internal.csv`, `test_reconciliation_counterpart.csv`,
`test_circular.csv`, `test_splitting.csv`, and `test_malformed.csv`. These files
use the ingestion API's decimal `amount` format and required column names.

For a one-upload demonstration, use `test_all_features.csv` with the form source
name `mixed-demo`. Its optional row-level `source_system` column separates the
internal and clearing ledgers while feeding every other detector from the same
canonical snapshot.

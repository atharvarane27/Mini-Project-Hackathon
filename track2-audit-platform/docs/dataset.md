# Dataset profile and synthetic scenarios

`SFinDSet.csv` contains 1,048,575 original source rows plus 100,037 deterministic synthetic rows (8.71% of the final dataset), for 1,148,612 data rows total. The synthetic rows occur immediately after the header and use transaction IDs beginning with `SYN-`.

The augmentation preserves tThe augmentation preserves tThe augmentation preserves tThe augmentation preserves tThe augmentation preserves tThe augmentation preserves tThe augmentation preserves tThe augmentation preserves tThe augmentation preserves tThe augmentation preserves tThe augmentation preserves tThe augmentation preserves tThe augmentation preserves tThe augmentation preserves tThe augmentation preserves tThe augmentation preserves tThe augmentation preserves tThe augmentation preserves tThe augmentation preserves tThe augmentation preserves tThe augmentation preserves tThe augmentation preserves tThe augmentation preserves tThe augmentation preserves tThe augmentationempotency reference. |
| `Source_Revision` | Revision number for source conflict handling. |
| `Journal_ID` | Groups the explicit balanced and unbalanced journal fixtures. It is intentionally blank for legacy rows. |
| `Entry_Direction` | `DEBIT` or `CREDIT`. |
| `Description` | Text available to blocking and fuzzy comparison. |
| `Scenario_Label` | Fixture grouping or `BASELINE`. Test metadata only. |
| `Expected_Finding` | Expected detector/reconciliation result. Test metadata only. |
| `Is_Synthetic` | Distinguishes injected rows from source rows. |

The initial 37-row acceptance block and 100,000-row load block cover exact replay, fuzzy duplicates, inverted fields, matched and mismatched ledgers, missing and late counterparts, ambiguous matching, a valid time-respecting cycle, an invalid temporal cycle, splitting inside and outside a 60-minute window, balanced and unbalanced journals, and malformed input rejection.

The bulk distribution is intentionally test-heavy: 20,000 duplicate/inversion rows, 32,000 reconciliation rows, 18,000 circular-graph rows, 18,000 splitting rows, 8,000 journal rows, and 4,000 rejected-input rows. These proportions test throughput and detector behavior; they do not represent real-world anomaly rates.

`Scenario_Label`, `Expected_Finding`, and `Is_Synthetic` must never participate in matching, scoring, rule evaluation, or production decisions. They exist only to select fixtures and verify expected results. The injected examples are deliberately obvious acceptance cases; they do not make the legacy records a labelled fraud dataset.

Reproduce the transformation from an unmodified source file with:

```powershell
python backend/scripts/augment_dataset.py SFinDSet.csv
```

The script writes through a temporary file, replaces the dataset only after a complete pass, preserves every source row, and refuses to augment a file that already contains `Scenario_Label`.

After the initial augmentation, add the deterministic 100,000-row load block with:

```powershell
python backend/scripts/scale_synthetic_scenarios.py SFinDSet.csv
```

The scaling script is also atomic and refuses to add the bulk block twice.

The CSV now exceeds both Excel's worksheet row limit and GitHub's normal 100 MiB per-file limit. Use a streaming reader or PostgreSQL import. Store the dataset outside ordinary Git history or configure Git LFS if it must be versioned.

The archive is intentionally kept out of Git history. Download or receive `SFinDSet.zip` from the project-approved data source used by the audit task, store it in a controlled local data directory outside the repository, and keep the project directory clean. The repository ignores `*.zip` files so local copies do not accidentally enter source control.

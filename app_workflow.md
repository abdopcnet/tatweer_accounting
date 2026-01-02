# Workflow

## Depreciation Auto-Approval

```
Scheduler (Hourly)
    ↓
Find Draft Depreciation Journal Entries
    ↓
For each entry:
    ├─ Set workflow_state = "Approved"
    ├─ Save
    ├─ Set workflow_state = "Submitted"
    ├─ Save
    └─ Submit
```

## Root Trial Balance Report

```
User Selects Filters
    ↓
Validate Filters (fiscal year, dates)
    ↓
Get Root-Level Accounts
    ↓
Calculate Opening Balances
    ↓
Get GL Entries
    ↓
Calculate Values (debit/credit)
    ↓
Filter Top-Level Only
    ↓
Display Report
```


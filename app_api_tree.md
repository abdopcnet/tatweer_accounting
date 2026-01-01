# API Tree

## Scheduled Tasks

### tatweer_accounting.tasks

- `approve_depreciation_entry()`
  - Description: Auto-approve and submit depreciation journal entries
  - Schedule: Hourly
  - Logic: Finds draft depreciation entries, moves them through workflow states

## Reports

### Root Trial Balance

- `execute(filters)`
  - Returns: columns, data
  - Filters: company, fiscal_year, from_date, to_date, cost_center, project, etc.


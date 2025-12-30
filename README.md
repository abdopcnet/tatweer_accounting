# Tatweer Accounting

![Version](https://img.shields.io/badge/version-30.12.2025-blue)

Customizations and enhancements for ERPNext accounting module.

## Features Preview

### Automated Depreciation Processing
- **Auto-approve Depreciation Entries**: Hourly scheduled task automatically approves and submits draft depreciation journal entries
- **Workflow Integration**: Seamlessly moves entries from Draft → Approved → Submitted state
- **Remark Preservation**: Maintains original remarks during auto-approval process

### Financial Reports
- **Root Trial Balance**: Custom report showing trial balance for root-level accounts only
- **Fiscal Year Support**: Full fiscal year date range filtering
- **Multi-currency**: Supports presentation currency conversion
- **Accounting Dimensions**: Includes accounting dimension support

## Installation

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench --site [site_name] install-app tatweer_accounting
```

## Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/tatweer_accounting
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

## License

MIT

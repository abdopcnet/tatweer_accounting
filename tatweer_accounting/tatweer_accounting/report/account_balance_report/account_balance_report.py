# Copyright (c) 2026, Hadeel Milad and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import add_days, cstr, flt, formatdate, getdate

import erpnext
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
    get_accounting_dimensions,
    get_dimension_with_children,
)
from erpnext.accounts.report.financial_statements import (
    filter_accounts,
    filter_out_zero_value_rows,
    get_cost_centers_with_children,
    set_gl_entries_by_account,
)
from erpnext.accounts.report.general_ledger.general_ledger import get_accounts_with_children
from erpnext.accounts.report.utils import convert_to_presentation_currency, get_currency
from erpnext.accounts.utils import get_zero_cutoff

value_fields = (
    "opening_debit",
    "opening_credit",
    "debit",
    "credit",
    "closing_debit",
    "closing_credit",
)


def execute(filters=None):
    validate_filters(filters)
    data = get_data(filters)
    columns = get_columns()
    return columns, data


def validate_filters(filters):
    if not filters.company:
        frappe.throw(_("Company is required"))

    if not filters.from_date:
        frappe.throw(_("From Date is required"))

    if not filters.to_date:
        frappe.throw(_("To Date is required"))

    filters.from_date = getdate(filters.from_date)
    filters.to_date = getdate(filters.to_date)

    if filters.from_date > filters.to_date:
        frappe.throw(_("From Date cannot be greater than To Date"))


def get_data(filters):
    """
    Main data retrieval function for Account Balance Report.

    Data Flow:
    1. Filter accounts based on main_account (if provided) using nested set model
    2. Get GL entries filtered by account hierarchy (root_lft, root_rgt)
    3. Get opening balances filtered by account_filter
    4. Calculate values and accumulate into parent accounts
    5. Prepare data for tree display

    Args:
        filters: Dictionary containing:
            - company: Company name
            - from_date: Start date for report
            - to_date: End date for report
            - main_account: Optional group account to filter by

    Returns:
        List of account rows with balances, or None if no accounts found
    """
    # Build account query with filters
    # Select all required fields including lft/rgt for hierarchical processing
    account_query = """
		SELECT
			name,
			account_number,
			parent_account,
			account_name,
			root_type,
			report_type,
			lft,
			rgt,
			is_group
		FROM `tabAccount`
		WHERE company = %s
	"""

    query_params = [filters.company]

    # Apply account filters
    account_filter = None
    root_lft = None
    root_rgt = None

    if filters.get("main_account"):
        # Verify that the account exists and belongs to the company
        account_exists = frappe.db.exists(
            "Account",
            {"name": filters.main_account, "company": filters.company}
        )

        if not account_exists:
            frappe.throw(_("Account {0} not found for company {1}").format(
                filters.main_account, filters.company
            ))

        # Get all accounts under main_account (including main_account itself)
        # Uses nested set model: lft >= account.lft AND rgt <= account.rgt
        account_filter = get_accounts_with_children(filters.main_account)

        # If get_accounts_with_children returns None or empty, use the account itself
        # This handles cases where the account exists but has no children
        if not account_filter:
            account_filter = [filters.main_account]

        # Get lft and rgt of main_account for filtering GL Entries
        # These values are used in get_account_filter_query() to filter GL entries
        # via EXISTS subquery: EXISTS (SELECT name FROM tabAccount WHERE name = gl_entry.account
        # AND lft >= root_lft AND rgt <= root_rgt AND is_group = 0)
        account_data = frappe.db.get_value(
            "Account",
            filters.main_account,
            ["lft", "rgt"],
            as_dict=True
        )
        if account_data:
            root_lft = account_data.lft
            root_rgt = account_data.rgt
        else:
            # If we can't get lft/rgt, we can't filter GL entries properly
            # But we should still show the account itself
            frappe.log_error(
                "[account_balance_report.py] method: get_data",
                "Account Balance Report"
            )

    if account_filter:
        # Use proper parameterized query with tuple for IN clause
        # This ensures SQL injection protection and proper escaping
        account_query += " AND name IN %s"
        query_params.append(tuple(account_filter))

    # Order by lft to maintain hierarchical structure (nested set model)
    account_query += " ORDER BY lft"

    accounts = frappe.db.sql(account_query, tuple(query_params), as_dict=True)

    company_currency = filters.get("presentation_currency") or erpnext.get_company_currency(filters.company)

    ignore_is_opening = frappe.db.get_single_value(
        "Accounts Settings", "ignore_is_opening_check_for_reporting"
    )

    if not accounts:
        return None

    # Build hierarchical structure from flat account list
    # Returns: (filtered_accounts, accounts_by_name, parent_children_map)
    # If main_account is selected, we need to treat it as root for display
    # even if it has a parent_account in the full account tree
    if filters.get("main_account"):
        # Temporarily set parent_account to None for the selected account
        # so filter_accounts() treats it as root
        main_account_parent = None
        for acc in accounts:
            if acc.get("name") == filters.get("main_account"):
                main_account_parent = acc.get("parent_account")
                acc["parent_account"] = None
                break

    accounts, accounts_by_name, parent_children_map = filter_accounts(accounts)

    gl_entries_by_account = {}

    # Get opening balances filtered by account_filter (if provided)
    # This ensures opening balances match the selected account hierarchy
    opening_balances = get_opening_balances(filters, ignore_is_opening, account_filter)

    # Ensure project filter is a list (required by financial_statements.py)
    if filters.get("project"):
        if not isinstance(filters.project, list):
            filters.project = [filters.project]

    # Fetch GL entries filtered by account hierarchy
    # root_lft and root_rgt are used in get_account_filter_query() to create EXISTS subquery
    # This ensures only GL entries for accounts within the selected hierarchy are included
    set_gl_entries_by_account(
        filters.company,
        filters.from_date,
        filters.to_date,
        filters,
        gl_entries_by_account,
        root_lft=root_lft,
        root_rgt=root_rgt,
        ignore_closing_entries=not flt(filters.get("with_period_closing_entry_for_current_period", 1)),
        ignore_opening_entries=True,
        group_by_account=True,
    )

    # Calculate debit/credit values for each account from GL entries
    calculate_values(
        accounts,
        gl_entries_by_account,
        opening_balances,
        filters.get("show_net_values"),
        ignore_is_opening=ignore_is_opening,
    )

    # Roll up values from child accounts to parent accounts
    # This ensures parent accounts show aggregated balances of all children
    accumulate_values_into_parents(accounts, accounts_by_name)

    # Format data for tree display with proper indentation and structure
    data = prepare_data(accounts, filters, parent_children_map, company_currency)

    # If main_account is selected, ensure it and all its children are always shown
    # This is important for group accounts that may not have transactions
    if filters.get("main_account"):
        # Mark the main account and all its children to always show
        # This ensures they appear even if all values are zero
        for row in data:
            if row.get("account") == filters.get("main_account"):
                row["has_value"] = True
            # Also mark all children of main_account
            elif parent_children_map.get(filters.get("main_account")):
                for child in parent_children_map[filters.get("main_account")]:
                    if row.get("account") == child.name:
                        row["has_value"] = True
                        break

    # Remove rows with zero values if show_zero_values is False
    # Note: filter_out_zero_value_rows will keep accounts with has_value=True
    # and also keep parent accounts if any child has has_value=True
    data = filter_out_zero_value_rows(
        data, parent_children_map, show_zero_values=filters.get("show_zero_values")
    )

    return data


def get_opening_balances(filters, ignore_is_opening, account_filter=None):
    """
    Get opening balances for both Balance Sheet and Profit & Loss accounts.

    Args:
        filters: Report filters dictionary
        ignore_is_opening: Whether to ignore is_opening flag
        account_filter: Optional list of account names to filter by

    Returns:
        Dictionary of opening balances: {account_name: {opening_debit, opening_credit}, ...}
    """
    balance_sheet_opening = get_rootwise_opening_balances(
        filters, "Balance Sheet", ignore_is_opening, account_filter
    )
    pl_opening = get_rootwise_opening_balances(
        filters, "Profit and Loss", ignore_is_opening, account_filter
    )

    balance_sheet_opening.update(pl_opening)
    return balance_sheet_opening


def get_rootwise_opening_balances(filters, report_type, ignore_is_opening, account_filter=None):
    gle = []

    last_period_closing_voucher = ""
    ignore_closing_balances = frappe.db.get_single_value(
        "Accounts Settings", "ignore_account_closing_balance"
    )

    if not ignore_closing_balances:
        last_period_closing_voucher = frappe.db.get_all(
            "Period Closing Voucher",
            filters={"docstatus": 1, "company": filters.company, "period_end_date": ("<", filters.from_date)},
            fields=["period_end_date", "name"],
            order_by="period_end_date desc",
            limit=1,
        )

    accounting_dimensions = get_accounting_dimensions(as_list=False)

    if last_period_closing_voucher:
        gle = get_opening_balance(
            "Account Closing Balance",
            filters,
            report_type,
            accounting_dimensions,
            period_closing_voucher=last_period_closing_voucher[0].name,
            ignore_is_opening=ignore_is_opening,
            account_filter=account_filter,
        )

        # Report getting generate from the mid of a fiscal year
        if getdate(last_period_closing_voucher[0].period_end_date) < getdate(add_days(filters.from_date, -1)):
            start_date = add_days(last_period_closing_voucher[0].period_end_date, 1)
            gle += get_opening_balance(
                "GL Entry",
                filters,
                report_type,
                accounting_dimensions,
                start_date=start_date,
                ignore_is_opening=ignore_is_opening,
                account_filter=account_filter,
            )
    else:
        gle = get_opening_balance(
            "GL Entry",
            filters,
            report_type,
            accounting_dimensions,
            ignore_is_opening=ignore_is_opening,
            account_filter=account_filter,
        )

    opening = frappe._dict()
    for d in gle:
        opening.setdefault(
            d.account,
            {
                "account": d.account,
                "opening_debit": 0.0,
                "opening_credit": 0.0,
            },
        )
        opening[d.account]["opening_debit"] += flt(d.debit)
        opening[d.account]["opening_credit"] += flt(d.credit)

    return opening


def get_opening_balance(
        doctype,
        filters,
        report_type,
        accounting_dimensions,
        period_closing_voucher=None,
        start_date=None,
        ignore_is_opening=0,
        account_filter=None,
):
    closing_balance = frappe.qb.DocType(doctype)
    accounts = frappe.db.get_all("Account", filters={"report_type": report_type}, pluck="name")

    opening_balance = (
        frappe.qb.from_(closing_balance)
        .select(
            closing_balance.account,
            closing_balance.account_currency,
            Sum(closing_balance.debit).as_("debit"),
            Sum(closing_balance.credit).as_("credit"),
            Sum(closing_balance.debit_in_account_currency).as_("debit_in_account_currency"),
            Sum(closing_balance.credit_in_account_currency).as_("credit_in_account_currency"),
        )
        .where((closing_balance.company == filters.company) & (closing_balance.account.isin(accounts)))
        .groupby(closing_balance.account)
    )

    # Apply account filter if provided
    # This ensures opening balances are only calculated for accounts in the selected hierarchy
    if account_filter:
        opening_balance = opening_balance.where(closing_balance.account.isin(account_filter))

    if period_closing_voucher:
        opening_balance = opening_balance.where(
            closing_balance.period_closing_voucher == period_closing_voucher
        )
    else:
        if start_date:
            opening_balance = opening_balance.where(
                (closing_balance.posting_date >= start_date)
                & (closing_balance.posting_date < filters.from_date)
            )

            if not ignore_is_opening:
                opening_balance = opening_balance.where(closing_balance.is_opening == "No")
        else:
            if not ignore_is_opening:
                opening_balance = opening_balance.where(
                    (closing_balance.posting_date < filters.from_date) | (closing_balance.is_opening == "Yes")
                )
            else:
                opening_balance = opening_balance.where(closing_balance.posting_date < filters.from_date)

    if doctype == "GL Entry":
        opening_balance = opening_balance.where(closing_balance.is_cancelled == 0)

    if not flt(filters.get("with_period_closing_entry_for_opening", 1)):
        if doctype == "Account Closing Balance":
            opening_balance = opening_balance.where(closing_balance.is_period_closing_voucher_entry == 0)
        else:
            opening_balance = opening_balance.where(closing_balance.voucher_type != "Period Closing Voucher")

    if filters.get("cost_center"):
        opening_balance = opening_balance.where(
            closing_balance.cost_center.isin(get_cost_centers_with_children(filters.get("cost_center")))
        )

    if filters.get("project"):
        project_list = filters.project if isinstance(filters.project, list) else [filters.project]
        opening_balance = opening_balance.where(closing_balance.project.isin(project_list))

    if frappe.db.count("Finance Book"):
        if filters.get("include_default_book_entries"):
            company_fb = frappe.get_cached_value("Company", filters.company, "default_finance_book")

            if filters.get("finance_book") and company_fb and cstr(filters.finance_book) != cstr(company_fb):
                frappe.throw(
                    _("To use a different finance book, please uncheck 'Include Default FB Entries'")
                )

            opening_balance = opening_balance.where(
                (closing_balance.finance_book.isin([cstr(filters.get("finance_book", "")), cstr(company_fb), ""]))
                | (closing_balance.finance_book.isnull())
            )
        else:
            opening_balance = opening_balance.where(
                (closing_balance.finance_book.isin([cstr(filters.get("finance_book", "")), ""]))
                | (closing_balance.finance_book.isnull())
            )

    if accounting_dimensions:
        for dimension in accounting_dimensions:
            if filters.get(dimension.fieldname):
                if frappe.get_cached_value("DocType", dimension.document_type, "is_tree"):
                    filters[dimension.fieldname] = get_dimension_with_children(
                        dimension.document_type, filters.get(dimension.fieldname)
                    )
                    opening_balance = opening_balance.where(
                        closing_balance[dimension.fieldname].isin(filters[dimension.fieldname])
                    )
                else:
                    opening_balance = opening_balance.where(
                        closing_balance[dimension.fieldname].isin(filters[dimension.fieldname])
                    )

    gle = opening_balance.run(as_dict=1)

    if filters and filters.get("presentation_currency"):
        convert_to_presentation_currency(gle, get_currency(filters))

    return gle


def calculate_values(accounts, gl_entries_by_account, opening_balances, show_net_values, ignore_is_opening=0):
    init = {
        "opening_debit": 0.0,
        "opening_credit": 0.0,
        "debit": 0.0,
        "credit": 0.0,
        "closing_debit": 0.0,
        "closing_credit": 0.0,
    }

    for d in accounts:
        d.update(init.copy())

        # add opening
        d["opening_debit"] = opening_balances.get(d.name, {}).get("opening_debit", 0)
        d["opening_credit"] = opening_balances.get(d.name, {}).get("opening_credit", 0)

        for entry in gl_entries_by_account.get(d.name, []):
            if cstr(entry.is_opening) != "Yes" or ignore_is_opening:
                d["debit"] += flt(entry.debit)
                d["credit"] += flt(entry.credit)

        d["closing_debit"] = d["opening_debit"] + d["debit"]
        d["closing_credit"] = d["opening_credit"] + d["credit"]

        if show_net_values:
            prepare_opening_closing(d)


def calculate_total_row(accounts, company_currency):
    total_row = {
        "account": "'" + _("Total") + "'",
        "account_name": "'" + _("Total") + "'",
        "warn_if_negative": True,
        "opening_debit": 0.0,
        "opening_credit": 0.0,
        "debit": 0.0,
        "credit": 0.0,
        "closing_debit": 0.0,
        "closing_credit": 0.0,
        "parent_account": None,
        "indent": 0,
        "has_value": True,
        "currency": company_currency,
    }

    for d in accounts:
        if not d.parent_account:
            for field in value_fields:
                total_row[field] += d[field]

    return total_row


def accumulate_values_into_parents(accounts, accounts_by_name):
    for d in reversed(accounts):
        if d.parent_account:
            for key in value_fields:
                accounts_by_name[d.parent_account][key] += d[key]


def prepare_data(accounts, filters, parent_children_map, company_currency):
    data = []

    for d in accounts:
        # Prepare opening closing for group account
        if parent_children_map.get(d.account) and filters.get("show_net_values"):
            prepare_opening_closing(d)

        has_value = False
        row = {
            "account": d.name,
            "parent_account": d.parent_account,
            "indent": d.indent,
            "from_date": filters.from_date,
            "to_date": filters.to_date,
            "currency": company_currency,
            "account_name": (
                f"{d.account_number} - {d.account_name}" if d.account_number else d.account_name
            ),
        }

        for key in value_fields:
            row[key] = flt(d.get(key, 0.0))

            if abs(row[key]) >= get_zero_cutoff(company_currency):
                # ignore zero values
                has_value = True

        row["has_value"] = has_value
        data.append(row)

    total_row = calculate_total_row(accounts, company_currency)
    data.extend([{}, total_row])

    return data


def get_columns():
    return [
        {
            "fieldname": "account",
            "label": _("Account"),
            "fieldtype": "Link",
            "options": "Account",
            "width": 300,
        },
        {
            "fieldname": "currency",
            "label": _("Currency"),
            "fieldtype": "Link",
            "options": "Currency",
            "hidden": 1,
        },
        {
            "fieldname": "opening_debit",
            "label": _("Opening (Dr)"),
            "fieldtype": "Currency",
            "options": "currency",
        },
        {
            "fieldname": "opening_credit",
            "label": _("Opening (Cr)"),
            "fieldtype": "Currency",
            "options": "currency",
        },
        {
            "fieldname": "debit",
            "label": _("Debit"),
            "fieldtype": "Currency",
            "options": "currency",
        },
        {
            "fieldname": "credit",
            "label": _("Credit"),
            "fieldtype": "Currency",
            "options": "currency",
        },
        {
            "fieldname": "closing_debit",
            "label": _("Closing (Dr)"),
            "fieldtype": "Currency",
            "options": "currency",
        },
        {
            "fieldname": "closing_credit",
            "label": _("Closing (Cr)"),
            "fieldtype": "Currency",
            "options": "currency",
        },
    ]


def prepare_opening_closing(row):
    dr_or_cr = "debit" if row["root_type"] in ["Asset", "Equity", "Expense"] else "credit"
    reverse_dr_or_cr = "credit" if dr_or_cr == "debit" else "debit"

    for col_type in ["opening", "closing"]:
        valid_col = col_type + "_" + dr_or_cr
        reverse_col = col_type + "_" + reverse_dr_or_cr
        row[valid_col] -= row[reverse_col]
        if row[valid_col] < 0:
            row[reverse_col] = abs(row[valid_col])
            row[valid_col] = 0.0
        else:
            row[reverse_col] = 0.0

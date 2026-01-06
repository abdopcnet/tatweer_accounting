// Copyright (c) 2026, Hadeel Milad and contributors
// For license information, please see license.txt

frappe.query_reports['Account Balance Report'] = {
	filters: [
		{
			fieldname: 'company',
			label: __('Company'),
			fieldtype: 'Link',
			options: 'Company',
			default: frappe.defaults.get_user_default('Company'),
			reqd: 1,
		},
		{
			fieldname: 'from_date',
			label: __('From Date'),
			fieldtype: 'Date',
			reqd: 1,
		},
		{
			fieldname: 'to_date',
			label: __('To Date'),
			fieldtype: 'Date',
			reqd: 1,
		},
		{
			fieldname: 'main_account',
			label: __('Group Account'),
			fieldtype: 'Link',
			options: 'Account',
			get_query: function () {
				var company = frappe.query_report.get_filter_value('company');
				return {
					doctype: 'Account',
					filters: {
						company: company,
						is_group: 1,
					},
				};
			},
		},
	],
	formatter: erpnext.financial_statements.formatter,
	tree: true,
	name_field: 'account',
	parent_field: 'parent_account',
	initial_depth: 3,
};

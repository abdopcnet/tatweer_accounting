# Copyright (c) 2025, Hadeel Milad and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import today
from frappe.model.document import Document
from frappe import get_meta
from frappe import _, msgprint, throw

from frappe.utils import (
	add_days,
	ceil,
	cint,
	cstr,
	date_diff,
	floor,
	flt,
	formatdate,
	get_first_day,
	get_last_day,
	get_link_to_form,
	getdate,
	money_in_words,
	rounded,
)


@frappe.whitelist()
def approve_depreciation_entry():
    je = frappe.db.get_all("Journal Entry" , filters={"voucher_type":"Depreciation Entry" , "workflow_state":"Draft"})
    for j in je :
        jj = frappe.get_doc("Journal Entry" , j.name)
        jj.user_remark = jj.remark
        jj.workflow_state = "Approved"
        jj.save()
        frappe.db.commit()
        jj.workflow_state = "Submitted"
        jj.save()
        frappe.db.commit()
        jj.submit()
        frappe.db.commit()

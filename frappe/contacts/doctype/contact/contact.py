# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE
import frappe
from frappe import _
from frappe.contacts.address_and_contact import set_link_title
from frappe.core.doctype.dynamic_link.dynamic_link import deduplicate_dynamic_links
from frappe.model.document import Document
from frappe.utils import cstr, has_gravatar, cint, clean_whitespace


class Contact(Document):
	def validate(self):
		self.clean_contact_name()
		self.clean_numbers_and_emails()
		self.remove_duplicates()
		self.set_primary_email()
		self.set_primary_phone()
		self.validate_phone_nos()
		self.validate_regional()

		self.set_user()

		set_link_title(self)

		if self.email_id and not self.image:
			self.image = has_gravatar(self.email_id)

		if self.get("sync_with_google_contacts") and not self.get("google_contacts"):
			frappe.throw(_("Select Google Contacts to which contact should be synced."))

		deduplicate_dynamic_links(self)

	def on_update(self):
		self.update_primary_address_in_linked_docs()

	def update_primary_address_in_linked_docs(self):
		from frappe.model.base_document import get_controller

		for d in self.links:
			if d.link_doctype and self.flags.from_linked_document != (d.link_doctype, d.link_name):
				try:
					if hasattr(get_controller(d.link_doctype), "update_primary_contact"):
						doc = frappe.get_doc(d.link_doctype, d.link_name)
						doc.flags.pull_contact = True
						doc.update_primary_contact()
						doc.notify_update()
				except ImportError:
					pass

	def clean_contact_name(self):
		self.first_name = clean_whitespace(self.first_name)
		self.middle_name = clean_whitespace(self.middle_name)
		self.last_name = clean_whitespace(self.last_name)

		if not self.last_name and self.middle_name:
			self.last_name = self.middle_name
			self.middle_name = ""

		self.full_name = " ".join(filter(lambda x: x, [self.first_name, self.middle_name, self.last_name]))

	def clean_numbers_and_emails(self):
		self.mobile_no = cstr(self.mobile_no).strip()
		self.mobile_no_2 = cstr(self.mobile_no_2).strip()
		self.phone = cstr(self.phone).strip()
		self.email_id = cstr(self.email_id).strip()

		for d in self.email_ids:
			d.email_id = cstr(d.email_id).strip()
		for d in self.phone_nos:
			d.phone = cstr(d.phone).strip()

	def remove_duplicates(self):
		email_ids_visited = []
		phone_nos_visited = []
		to_remove = []

		for d in self.email_ids:
			if d.email_id in email_ids_visited:
				to_remove.append(d)
			else:
				email_ids_visited.append(d.email_id)

		for d in self.phone_nos:
			if d.phone in phone_nos_visited:
				to_remove.append(d)
			else:
				phone_nos_visited.append(d.phone)

		for d in to_remove:
			self.remove(d)

		for i, d in enumerate(self.email_ids):
			d.idx = i + 1
		for i, d in enumerate(self.phone_nos):
			d.idx = i + 1

	def validate_phone_nos(self):
		pass
		# for d in self.phone_nos:
		# 	if not d.get('is_primary_phone') and not d.get('is_primary_mobile_no'):
		# 		frappe.throw(_("Row #{0}: Please mark contact number {1} as either a Mobile Number or a Phone Number")
		# 			.format(d.idx, frappe.bold(d.phone)))

	def validate_regional(self):
		from frappe.regional.pakistan import validate_ntn_cnic_strn, validate_mobile_pakistan

		if self.get('tax_cnic'):
			validate_ntn_cnic_strn(cnic=self.tax_cnic)

		if self.get('mobile_no'):
			validate_mobile_pakistan(self.mobile_no)
		if self.get('mobile_no_2'):
			validate_mobile_pakistan(self.mobile_no_2)

		for d in self.phone_nos:
			if d.is_primary_mobile_no:
				if not validate_mobile_pakistan(d.phone, throw=False):
					d.is_primary_mobile_no = 0

	def set_primary_email(self):
		if self.email_id:
			if self.email_id not in [d.email_id for d in self.email_ids]:
				self.append('email_ids', {'email_id': self.email_id})
		else:
			if self.email_ids:
				self.email_id = self.email_ids[0].email_id

		for d in self.email_ids:
			d.is_primary = 1 if d.email_id == self.email_id else 0

	def set_primary_phone(self):
		# secondary without primary
		if not self.mobile_no and self.mobile_no_2:
			self.mobile_no = self.mobile_no_2
			self.mobile_no_2 = ""

		# no duplicate
		if self.mobile_no == self.mobile_no_2:
			self.mobile_no_2 = ""

		all_nos = [d.phone for d in self.phone_nos]
		mobile_nos = [d.phone for d in self.phone_nos if d.is_primary_mobile_no]
		phone_nos = [d.phone for d in self.phone_nos if d.is_primary_phone]

		if self.mobile_no:
			if self.mobile_no not in all_nos:
				self.append('phone_nos', {'phone': self.mobile_no, 'is_primary_mobile_no': 1})
		else:
			if mobile_nos:
				self.mobile_no = mobile_nos[0]

		non_primary_mobile_nos = [d.phone for d in self.phone_nos if d.is_primary_mobile_no and d.phone != self.mobile_no]
		if self.mobile_no_2:
			if self.mobile_no_2 not in all_nos:
				self.append('phone_nos', {'phone': self.mobile_no_2, 'is_primary_mobile_no': 1})
		else:
			if non_primary_mobile_nos:
				self.mobile_no_2 = non_primary_mobile_nos[0]

		if self.phone:
			if self.phone not in all_nos:
				self.append('phone_nos', {'phone': self.phone, 'is_primary_phone': 1})
		else:
			if phone_nos:
				self.phone = phone_nos[0]

		for d in self.phone_nos:
			if d.phone in (self.mobile_no, self.mobile_no_2):
				d.is_primary_mobile_no = 1
			if d.phone == self.phone:
				d.is_primary_phone = 1

	def add_email(self, email_id, is_primary=0, autosave=False):
		email_id = cstr(email_id).strip()
		if not email_id:
			return

		if is_primary:
			self.email_id = email_id

		if email_id not in [d.email_id for d in self.email_ids]:
			self.append("email_ids", {
				"email_id": email_id,
				"is_primary": is_primary
			})

		if autosave:
			self.save(ignore_permissions=True)

	def add_phone(self, phone, is_primary_phone=0, is_primary_mobile_no=0, autosave=False):
		phone = cstr(phone).strip()

		if phone and phone not in [d.phone for d in self.phone_nos]:
			self.append(
				"phone_nos",
				{
					"phone": phone,
					"is_primary_phone": is_primary_phone,
					"is_primary_mobile_no": is_primary_mobile_no,
				},
			)

			if autosave:
				self.save(ignore_permissions=True)

	def set_user(self):
		if not self.user and self.email_id:
			self.user = frappe.db.get_value("User", {"email": self.email_id})

	def get_link_for(self, link_doctype):
		'''Return the link name, if exists for the given link DocType'''
		for link in self.links:
			if link.link_doctype==link_doctype:
				return link.link_name

		return None

	def has_link(self, doctype, name):
		for link in self.links:
			if link.link_doctype==doctype and link.link_name== name:
				return True

	def has_common_link(self, doc):
		reference_links = [(link.link_doctype, link.link_name) for link in doc.links]
		for link in self.links:
			if (link.link_doctype, link.link_name) in reference_links:
				return True


def get_default_contact(doctype, name):
	"""Returns default contact for the given doctype, name"""
	out = frappe.db.sql(
		"""select parent,
			IFNULL((select is_primary_contact from tabContact c where c.name = dl.parent), 0)
				as is_primary_contact
		from
			`tabDynamic Link` dl
		where
			dl.link_doctype=%s and
			dl.link_name=%s and
			dl.parenttype = 'Contact'""",
		(doctype, name),
		as_dict=True,
	)

	if out:
		for contact in out:
			if contact.is_primary_contact:
				return contact.parent
		return out[0].parent
	else:
		return None


@frappe.whitelist()
def invite_user(contact):
	contact = frappe.get_doc("Contact", contact)

	if not contact.email_id:
		frappe.throw(_("Please set Email Address"))

	if contact.has_permission("write"):
		user = frappe.get_doc(
			{
				"doctype": "User",
				"first_name": contact.first_name,
				"last_name": contact.last_name,
				"email": contact.email_id,
				"user_type": "Website User",
				"send_welcome_email": 1,
			}
		).insert(ignore_permissions=True)

		return user.name


@frappe.whitelist()
def get_contact_details(contact, get_contact_no_list=False, link_doctype=None, link_name=None):
	contact = frappe.get_doc("Contact", contact) if contact else frappe._dict()
	out = frappe._dict({
		"contact_person": contact.get("name"),
		"contact_display": " ".join(
			filter(None, [contact.get("salutation"), contact.get("first_name"), contact.get("last_name")])
		),
		"contact_email": contact.get("email_id"),
		"contact_mobile": contact.get("mobile_no"),
		"contact_mobile_2": contact.get("mobile_no_2"),
		"contact_phone": contact.get("phone"),
		"contact_designation": contact.get("designation"),
		"contact_department": contact.get("department"),
		"contact_cnic": contact.get("tax_cnic")
	})

	if cint(get_contact_no_list) and link_doctype and link_name:
		out.contact_nos = get_all_contact_nos(link_doctype, link_name)

	return out


def update_contact(doc, method):
	"""Update contact when user is updated, if contact is found. Called via hooks"""
	contact_name = frappe.db.get_value("Contact", {"email_id": doc.name})
	if contact_name:
		contact = frappe.get_doc("Contact", contact_name)
		for key in ("first_name", "last_name", "phone"):
			if doc.get(key):
				contact.set(key, doc.get(key))
		contact.flags.ignore_mandatory = True
		contact.save(ignore_permissions=True)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def contact_query(doctype, txt, searchfield, start, page_len, filters):
	from frappe.desk.reportview import get_match_cond, get_filters_cond

	doctype = "Contact"
	link_doctype = filters.pop("link_doctype")
	link_name = filters.pop("link_name")

	meta = frappe.get_meta(doctype)
	searchfields = meta.get_search_fields()
	if searchfield and searchfield not in searchfields and \
			(meta.get_field(searchfield) or searchfield in frappe.db.DEFAULT_COLUMNS):
		searchfields.append(searchfield)

	fields = ["name"] + searchfields
	fields = frappe.utils.unique(fields)
	fields = ", ".join(["`tabContact`.{0}".format(f) for f in fields])

	search_condition = " or ".join(["`tabContact`.{0}".format(field) + " like %(txt)s" for field in searchfields])

	return frappe.db.sql("""
		select {fields}
		from `tabContact`, `tabDynamic Link`
		where `tabDynamic Link`.parent = `tabContact`.name
			and `tabDynamic Link`.parenttype = 'Contact'
			and `tabDynamic Link`.link_doctype = %(link_doctype)s
			and `tabDynamic Link`.link_name = %(link_name)s
			and ({scond})
			{fcond} {mcond}
		order by
			if(locate(%(_txt)s, `tabContact`.name), locate(%(_txt)s, `tabContact`.name), 99999),
			if(locate(%(_txt)s, `tabContact`.full_name), locate(%(_txt)s, `tabContact`.full_name), 99999),
			`tabContact`.is_primary_contact desc,
			`tabContact`.idx desc,
			`tabContact`.name
		limit %(start)s, %(page_len)s
	""".format(
		fields=fields,
		scond=search_condition,
		mcond=get_match_cond(doctype),
		fcond=get_filters_cond(doctype, filters, []),
		key=searchfield
	), {
		'txt': '%' + txt + '%',
		'_txt': txt.replace("%", ""),
		'start': start,
		'page_len': page_len,
		'link_name': link_name,
		'link_doctype': link_doctype
	})


@frappe.whitelist()
def address_query(links):
	import json

	links = [
		{"link_doctype": d.get("link_doctype"), "link_name": d.get("link_name")}
		for d in json.loads(links)
	]
	result = []

	for link in links:
		if not frappe.has_permission(
			doctype=link.get("link_doctype"), ptype="read", doc=link.get("link_name")
		):
			continue

		res = frappe.db.sql(
			"""
			SELECT `tabAddress`.name
			FROM `tabAddress`, `tabDynamic Link`
			WHERE `tabDynamic Link`.parenttype='Address'
				AND `tabDynamic Link`.parent=`tabAddress`.name
				AND `tabDynamic Link`.link_doctype = %(link_doctype)s
				AND `tabDynamic Link`.link_name = %(link_name)s
		""",
			{
				"link_doctype": link.get("link_doctype"),
				"link_name": link.get("link_name"),
			},
			as_dict=True,
		)

		result.extend([l.name for l in res])

	return result


def get_contact_with_phone_number(number):
	if not number:
		return

	contacts = frappe.get_all(
		"Contact Phone", filters=[["phone", "like", f"%{number}"]], fields=["parent"], limit=1
	)

	return contacts[0].parent if contacts else None


def get_contact_name(email_id):
	contact = frappe.get_all(
		"Contact Email", filters={"email_id": email_id}, fields=["parent"], limit=1
	)
	return contact[0].parent if contact else None


@frappe.whitelist()
def get_all_contact_nos(link_doctype, link_name):
	if not link_doctype or not link_name:
		return []

	numbers = frappe.db.sql("""
		select p.phone, p.is_primary_mobile_no, p.is_primary_phone, c.name as contact
		from `tabContact Phone` p
		inner join `tabContact` c on c.name = p.parent
		where exists(select dl.name from `tabDynamic Link` dl
			where dl.parenttype = 'Contact' and dl.parent = c.name and dl.link_doctype = %s and dl.link_name = %s)
		order by c.is_primary_contact desc, c.creation, p.idx
	""", (link_doctype, link_name), as_dict=1)

	return numbers


@frappe.whitelist()
def add_phone_no_to_contact(contact, phone, is_primary_mobile_no=0, is_primary_phone=0):
	doc = frappe.get_doc("Contact", contact)
	doc.add_phone(phone, is_primary_mobile_no=cint(is_primary_mobile_no), is_primary_phone=cint(is_primary_phone))
	doc.save()


def get_contacts_linking_to(doctype, docname, fields=None):
	"""Return a list of contacts containing a link to the given document."""
	return frappe.get_list(
		"Contact",
		fields=fields,
		filters=[
			["Dynamic Link", "link_doctype", "=", doctype],
			["Dynamic Link", "link_name", "=", docname],
		],
	)


def get_contacts_linked_from(doctype, docname, fields=None):
	"""Return a list of contacts that are contained in (linked from) the given document."""
	link_fields = frappe.get_meta(doctype).get("fields", {"fieldtype": "Link", "options": "Contact"})
	if not link_fields:
		return []

	contact_names = frappe.get_value(doctype, docname, fieldname=[f.fieldname for f in link_fields])
	if not contact_names:
		return []

	return frappe.get_list("Contact", fields=fields, filters={"name": ("in", contact_names)})

__author__ = 'J. Michael Caine'
__copyright__ = '2020'
__version__ = '0.1'
__license__ = 'MIT'

import functools
import random
import re

from datetime import datetime
from os.path import exists as path_exists

import logging
l = logging.getLogger(__name__)

from dominate import document
from dominate import tags as t
from dominate.util import raw

from yarl import URL

from . import valid
from . import settings
from . import text
from . import util as U

k_cache_version = '?v=j5'

# Classes ---------------------------------------------------------------------

class Form:
	def __init__(self, action, values = None, invalids = None):
		'''
		`values` is a dict of (field-name, value) pairs.
		`invalids` is a list/tuple of field names that did not pass a validity test (server side).
		'''
		self.action = action
		self.values = values
		self.invalids = set(invalids) if invalids else set()
		
	def nv(self, name):
		# returns a (name, value) pair for `name`, or else None if there are no values set at all (in __init__)
		return (name, self.values.get(name) if self.values else None)

	def is_invalid(self, name):
		# returns True if `name` is in the list of invalids set (in __init__)
		return name in self.invalids

# Handlers --------------------------------------------------------------------

def login(action, flash = None, hide_username = False):
	d = _doc(text.doc_prefix + 'Login')
	with d:
		with t.form(action = action, method = 'post'):
			with t.fieldset(cls = 'small_fieldset'):
				t.legend('Log in...')
				_flash(flash)
				pw_attrs = ['required',]
				if not hide_username:
					t.div(_text_input('username', None, ('required', 'autofocus'), {'pattern': valid.re_username}, None, _invalid_div(text.inv_username, False)), cls = 'login_field')
				else:
					pw_attrs.append('autofocus')
				t.div(_text_input('password', None, pw_attrs, type_ = 'password'), cls = 'login_field')
				t.div(t.a('Forgot password? Click here...', href = _gurl('/forgot_password')))
				t.div(t.button("Log in!", type = "submit"), cls = 'login_field')
		t.script(_js_basic())
		t.script(_js_validate_event())
		t.script(_js_validate_username_fields())
	return d.render()

def forgot_password(form, flash = None):
	d = _doc(text.doc_prefix + 'Forgot Password')
	with d:
		with t.form(action = form.action, method = 'post'):
			with t.fieldset(cls = 'small_fieldset'):
				t.legend('Request password reset...')
				_flash(flash)
				t.div('What is your email address on account?')
				t.div(_text_input('email', None, ('required', 'autofocus'), {'pattern': valid.re_email}, 'Type your email address here',
					_invalid_div(text.inv_email, form.is_invalid('email'))))
				t.div(t.button("Send!", type = "submit"))
				t.hr()
				t.div('Then check your email for a link to reset your password.')
		t.script(_js_basic())
		t.script(_js_validate_event())
		t.script(_js_validate_email_field())
	return d.render()

def forgot_password_enter_code(form, flash = None):
	d = _doc(text.doc_prefix + 'Forgot Password')
	with d:
		with t.form(action = form.action, method = 'post'):
			with t.fieldset(cls = 'small_fieldset'):
				t.legend('Password reset code...')
				_flash(flash)
				t.div('Type or paste your password-reset code:')
				t.div(_text_input('code', None, ('required', 'autofocus'), None, 'Type or paste your code here'))
				t.div(t.button("Go!", type = "submit"))
		t.script(_js_basic())
	return d.render()

def reset_password(form, error = None):
	title = 'Reset Password'
	d = _doc(text.doc_prefix + title)
	with d:
		with t.form(action = form.action, method = 'post'):
			with t.fieldset(cls = 'small_fieldset'):
				t.legend(title + '...')
				_error(error)
				t.div(_text_input('password', None, ('required', 'autofocus'), {'pattern': valid.re_password}, None,
					_invalid_div(text.inv_password, form.is_invalid('password')), type_ = 'password'), cls = 'field')
				t.div(_text_input('password_confirmation', None, ('required',), None, 'Again, for confirmation',
					_invalid_div(text.inv_password_confirmation, form.is_invalid('password_confirmation'), 'password_match_message'), type_ = 'password'), cls = 'field')
				t.div(t.button("Done", type = "submit"), cls = 'field')
		t.script(_js_basic())
		t.script(_js_validate_event())
		t.script(_js_validate_password_fields())
		t.script(_js_validate_password_confirmation_fields())

	return d.render()


def reset_password_success(nexts):
	title = 'Reset Password'
	d = _doc(text.doc_prefix + title)
	with d:
		with t.fieldset(cls = 'small_fieldset'):
			t.legend('Password reset...')
			t.div(text.reset_password_success)
			_nexts(nexts)
	return d.render()


def _nexts(nexts):
	for name, url in nexts:
		t.div(t.button(name, type = 'button', title = name, onclick = f'window.open("{url}", "_self");'))
		#t.div(t.a(name, href = url))


def new_user_success(id): # TODO: this is just a lame placeholder
	d = _doc(text.doc_prefix + 'New User')
	with d:
		t.p('New user (%s) successfully created! ....' % id)
	return d.render()

def new_person(form, errors = None):
	title = 'New Person'
	#TODO

def _format_phone(number):
	sn = str(number)
	return '(%s) %s-%s' % (sn[0:3], sn[3:6], sn[6:10])

def _format_person(person, bd = True):
	result = '%s %s' % (person['first_name'], person['last_name'])
	if bd:
		result += ' (%s)' % person['birthdate'].strftime('%b %-d, %Y')
	return result

def _format_money(amount_cents):
	if amount_cents % 100 == 0:
		dollars = '$%d' % (amount_cents // 100)
	else:
		dollars = '$%.2f' % (amount_cents / 100)
	return t.b(dollars)

def _format_cost(cost):
	return (cost['name'] + ': ', _format_money(cost['amount']))


def invitation_DEPRECATED(form, invitation, person, family, contact, costs, cost_offsets, leader, payments, flash = None):
	#TODO: this is ugly long!  dice it up!!
	
	cl = lambda content: t.div(content, cls = 'contact_line')
	cli = lambda content: t.div(content, cls = 'contact_line_inset')
	
	d = _doc(text.doc_prefix + 'Invitation')
	with d:
		if not flash: # if there are errors, then we are re-presentingt his page; no need to say hello again
			t.p('Hello %s %s!  Please confirm that all of the following is correct...' % (person['first_name'], person['last_name']))
		else:
			_flash(flash)
			
		with t.div(cls = 'flex-wrap'):
			t.div('Contact', cls = 'title')
			with t.div(cls = 'main'):
				with t.div(cls = 'resource_record'):
					for address in contact.addresses:
						if address['note']:
							cl(t.b(address['note']))
						if address['po_box']:
							cl(address['po_box'])
						else:
							cl(address['street_1'])
							if address['street_2']:
								cl(address['street_2'])
						cl('%s, %s  %s' % (address['city'], address['state'], address['postal_code']))
						if address['unlisted']:
							cl(t.b('(unlisted)'))
					t.hr()
				with t.div(cls = 'resource_record'):
					for email in contact.emails:
						result = email['address']
						if email['unlisted']:
							result += ' (unlisted)'
						if email['note']:
							result += ' %s' % email['note']
						cl(result)
				with t.div(cls = 'resource_record'):
					for phone in contact.phones:
						result = _format_phone(phone['number'])
						if phone['unlisted']:
							result += ' (unlisted)'
						if phone['note']:
							result += ' %s' % phone['note']
						cl(result)
					
		with t.div(cls = 'flex-wrap'):
			t.div('Family', cls = 'title')
			with t.div(cls = 'main'):
				with t.div(cls = 'resource_record'):
					fg = family.guardians
					if len(fg) == 2 and fg[0]['last_name'] == fg[1]['last_name']: # most common "spouse" scenario
						hoh = 0 if fg[0]['head_of_household'] else 1
						other = 1 if hoh == 0 else 0
						cl(fg[hoh]['first_name'] + ' & ' + fg[other]['first_name'] + ' ' + fg[hoh]['last_name'])
					else:
						cl(', '.join(['%s %s' % (g['first_name'], g['last_name']) for g in fg]))
					t.hr()
				with t.div(cls = 'resource_record'):
					program_grouped = {}
					for child in family.children:
						program_name = '%s (%s)' % (child['program_name'], child['program_schedule'])
						if program_name not in program_grouped.keys():
							program_grouped[program_name] = [child,]
						else:
							program_grouped[program_name].append(child)
					for program_name, children in program_grouped.items():
						cl(t.b(program_name))
						for child in children:
							cli(_format_person(child))
		
		leadership_credit = 0
		if leader:
			with t.div(cls = 'flex-wrap'):
				t.div('Leadership', cls = 'title')
				with t.div(cls = 'main'):
					for role in leader:
						with t.div(cls = 'resource_record'):
							role_line = 'Role: ' + role['program_name'] + ' ' + role['role']
							if role['subject_name']:
								role_line += ' - ' + role['subject_name'] + ' (%d weeks)' % role['weeks']
							if role['sections'] > 1:
								role_line += ' (%s sections)' % role['sections']
							cl(t.span(role_line))
							offset = role['annual_offset']
							if offset:
								cl(t.span('Annual offset: ', _format_money(offset)))
								leadership_credit += offset
			
			
		with t.div(cls = 'flex-wrap'):
			t.div('Costs', cls = 'title')
			with t.div(cls = 'main'):
				total = 0
				total_payments = 0
				with t.div(cls = 'resource_record'):
					for cost in [c for c in costs if not c['per_student']]:
						cl(t.span(*_format_cost(cost)))
						total += cost['amount']
					covered = set() # duplicate-coverage tracker -- eek, this is a bit too much "logic" for the interface ("view") layer!
					for cost_offset in cost_offsets:
						cl(t.span(*_format_cost_offset(cost_offset)))
						total += cost_offset['amount']
						
					for child in family.children:
						fn = child['first_name']
						ln = child['last_name']
						cl(t.span(t.b(fn + ' ' + ln), ' (', child['program_name'], ')'))
						child_total = 0
						for cost in [c for c in costs if c['per_student'] and not c['program']]:
							tag = '%s %s %s' % (fn, ln, cost['name']) # Eek, this is a bit too much "logic" for the interface ("view") layer!
							if tag not in covered: # don't duplicate "non-program-centric costs" (e.g., facility-cost, which is per-student; but a student may be in multiple programs, and thus may have multiple "child" records here, the only difference being the cost (name))
								covered.add(tag)
								cli(t.span(*_format_cost(cost)))
								child_total += cost['amount']
						for cost in [c for c in costs if c['program'] == child['program_id']]:
							cli(t.span(*_format_cost(cost)))
							child_total += cost['amount']
						cli(t.span(*('Total: ', _format_money(child_total))))
						total += child_total
					cl(t.span('TOTAL: ', _format_money(total)))
					t.hr()
				with t.div(cls = 'resource_record'):
					cl('Payments:')
					for payment in payments:
						cli(t.span('Check #%s (%s): ' % (payment['check_number'], payment['date'].strftime('%x')), _format_money(payment['amount'])))
						total_payments += payment['amount']
					t.hr()
				if leadership_credit:
					with t.div(cls = 'resource_record'):
						cl('Offsets:')
						cli(_format_money(leadership_credit))
						t.hr()
				with t.div(cls = 'resource_record'):
					cl('Balance Due:')
					cli(_format_money(total - total_payments - leadership_credit))

		t.p('If you see any mistakes, please just contact me directly.  Thanks!')
		
	return d.render()

def _format_enrollment_programs(enrollments):
	lines = []
	for enrollment in enrollments:
		lines.append(enrollment['program_name'] + '(Grade %s)' % enrollment['grade'])
	return ', '.join(lines)

def invalid_invitation():
	d = _doc(text.doc_prefix + 'Family Invitation')
	with d:
		# TODO: improve!!!
		t.body("That is not a valid invitation ID")
	return d.render()


def financial_persons(links, _, login, user_settings, financial_persons, link_base):
	d = _financial_head_doc(links, login, user_settings)
	with d:
		with t.table():
			for fp in financial_persons:
				t.tr((t.td(t.a(f"{fp['first_name']} {fp['last_name']}", href = f"{link_base}/{fp['id']}"))))
	return d.render()

def _financial_head_doc(links, login, user_settings):
	d = _doc(text.doc_prefix + 'Financial')
	with d:
		# TODO: this is copy-pasted from resources(), for now -- CONSOLIDATE/refactor!
		with t.div(cls = 'flex-wrap'): # TODO: make a 'header_block' or something; different border color, perhaps
			t.div(t.b('Go'), cls = 'title')
			with t.div(cls = 'main'):
				with t.div(id = 'go'):
					with t.div(cls = 'ib-left'):
						for name, hint, content, url in links:
							onclick = f'window.open("{content}", "_self");' # assuming url=True
							if not url: # then assume script, or other 'raw':
								onclick = f'{content};'
							t.button(name, type = 'button', title = hint, onclick = onclick)
				with t.div(id = 'login'):
					with t.div(cls = 'ib-right'):
						if login['type'] == 'button':
							t.button(text.login_button_title, type = 'button', title = text.login_button_title, onclick = 'load_page("%s")' % _gurl('/login'))
						else:
							t.button('₪', title = 'Messages', type = 'button', onclick = 'void()') #TODO: 'load_page("%s")' % _gurl('/messages'))
							assert(login['type'] == 'menu')
							_login_dropdown(login['username'], login['switch_users'], hint = 'Switch person')
	return d


def financial(links, years_filter, login, user_settings, person, data):
	d = _financial_head_doc(links, login, user_settings)
	with d:

		with t.div(cls = 'flex-wrap'): # TODO: make a 'header_block' or something; different border color, perhaps
			t.div(t.b('Filter'), cls = 'title')
			with t.div(cls = 'main'):
				key, options, hint, selected = years_filter
				title = selected if selected else 'Select a year...'
				with t.div(id = '%s-container' % key):
					_url_dropdown(t.div(cls = 'dropdown'), key, [(year_name, _gurl(f'?academic_year={year_id}')) for (year_name, year_id) in options], title, 'Select an accademic year to view...')

		cl = lambda content: t.div(content, cls = 'contact_line')
		cli = lambda content: t.div(content, cls = 'contact_line_inset')

		with t.div(cls = 'flex-wrap'):
			t.div(t.b('Contact'), cls = 'title')
			with t.div(cls = 'main'):
				with t.div(cls = 'resource_record'):
					for address in data.contact.addresses:
						if address['note']:
							cl(t.b(address['note']))
						if address['po_box']:
							cl(address['po_box'])
						else:
							cl(address['street_1'])
							if address['street_2']:
								cl(address['street_2'])
						cl('%s, %s  %s' % (address['city'], address['state'], address['postal_code']))
						if address['unlisted']:
							cl(t.b('(unlisted)'))
					t.hr()
				with t.div(cls = 'resource_record'):
					for email in data.contact.emails:
						result = email['address']
						if email['unlisted']:
							result += ' (unlisted)'
						if email['note']:
							result += ' %s' % email['note']
						cl(result)
				with t.div(cls = 'resource_record'):
					for phone in data.contact.phones:
						result = _format_phone(phone['number'])
						if phone['unlisted']:
							result += ' (unlisted)'
						if phone['note']:
							result += ' %s' % phone['note']
						cl(result)
					
		with t.div(cls = 'flex-wrap'):
			t.div('Family', cls = 'title')
			with t.div(cls = 'main'):
				with t.div(cls = 'resource_record'):
					fg = data.family.guardians
					if len(fg) == 2 and fg[0]['last_name'] == fg[1]['last_name']: # most common "spouse" scenario
						hoh = 0 if fg[0]['head_of_household'] else 1
						other = 1 if hoh == 0 else 0
						cl(fg[hoh]['first_name'] + ' & ' + fg[other]['first_name'] + ' ' + fg[hoh]['last_name'])
					else:
						cl(', '.join(['%s %s' % (g['first_name'], g['last_name']) for g in fg]))
					t.hr()
				with t.div(cls = 'resource_record'):
					program_grouped = {}
					current_child = None
					for child in data.family.children:
						if child['program_show_top_level']:
							formatted = _format_person(child)
							if current_child != formatted:
								current_child = formatted
								cl(t.b(formatted))
							cli('%s (%s)' % (child['program_name'], child['program_schedule']))

		leadership_credit = 0
		if data.leaders:
			with t.div(cls = 'flex-wrap'):
				t.div('Leadership', cls = 'title')
				with t.div(cls = 'main'):
					for role in data.leaders:
						with t.div(cls = 'resource_record'):
							role_line = 'Role: ' + role['program_name'] + ' ' + role['role']
							if role['subject_name']:
								role_line += ' - ' + role['subject_name'] + ' (%d weeks)' % role['weeks']
							if role['sections'] > 1:
								role_line += ' (%s sections)' % role['sections']
							if role['note']:
								role_line += f" -- {role['note']}"
							cl(t.span(role_line))
							offset = role['annual_offset']
							if offset:
								cl(t.span('Annual offset: ', _format_money(offset)))
								leadership_credit += offset
					t.hr()
					with t.div(cls = 'resource_record'):
						cli(t.span(*('Total: ', _format_money(leadership_credit))))

		with t.div(cls = 'flex-wrap'):
			t.div('Costs', cls = 'title')
			with t.div(cls = 'main'):
				total = 0
				total_payments = 0
				with t.div(cls = 'resource_record'):


					if data.costs: # don't do any family_costs if there are no enrollments at all!
						for cost in data.family_costs:
							total += cost['amount']
							cl(t.span(*_format_cost(cost)))

					for offset in data.cost_offsets:
						total += offset['amount']
						cl(t.span(*(offset['note'], ': ', _format_money(offset['amount']))))

					fn = ln = ''
					for cost in data.costs:
						if cost['amount'] != 0 and cost['enrollment_exception'] != 1:
							total += cost['amount']
							if fn != cost['first_name'] or ln != cost['last_name']:
								fn = cost['first_name']
								ln = cost['last_name']
								cl(t.span(t.b(fn + ' ' + ln + ' --')))
							cli(t.span(*(cost['program_name'], ' - ', cost['name'], ' : ', _format_money(cost['amount']))))

					cl(t.span('TOTAL: ', _format_money(total)))
					t.hr()

				with t.div(cls = 'resource_record'):
					cl('Payments:')
					if not data.payments:
						cli(t.span('<None>'))
					#else:
					for payment in data.payments:
						cli(t.span('Check #%s (%s): ' % (payment['check_number'], payment['date'].strftime('%x')), _format_money(payment['amount'])))
						total_payments += payment['amount']
					t.hr()

				if leadership_credit or data.carryover:
					with t.div(cls = 'resource_record'):
						cl('Adjustments:')
						if leadership_credit:
							cli(t.span(*'Leadership Credit (see detail above): ', _format_money(-leadership_credit)))
						if data.carryover:
							cli(t.span(*'Carryover from previous years: ', _format_money(data.carryover)))
							total += data.carryover
						t.hr()
				with t.div(cls = 'resource_record'):
					total = total - total_payments - leadership_credit
					if total > 0:
						cl('Balance Due (make checks payable to CCLSC):')
						cli(_format_money(total))
					else:
						cl('Balance CCLSC owes YOU:')
						cli(_format_money(-total))
						cli('(your check will be delivered soon!)')

		t.p('If you see any mistakes, please just contact me directly.  Thanks!')

		t.script(_js_basic())
		t.script(_js_go_to())
		t.script(_js_dropdown())
		t.script(_js_load_bg(user_settings))

	return d.render()


def _family_user_setup(action, rows, invalids, ws_url, passwords, used_passwords, all_exist_already, flash = None):
	cl = lambda content: t.div(content, cls = 'contact_line') # TODO: DEPORT

	username_fields = []
	password_fields = []
	d = _doc(text.doc_prefix + 'Family Invitation')
	with d:
		with t.div(cls = 'flex-wrap'):
			t.div('Logins', cls = 'title')
			with t.div(cls = 'main'):
				with t.form(action = action, method = 'post', id = 'save_users'):
					with t.div(cls = 'clear_right'):
						if flash:
							_flash(flash)
							t.hr()

						with t.table():
							password_th = 'password' if all_exist_already else 'password (or type or try "◄ Another")'
							t.tr((t.th('name: username', cls = 'ca-cell'), t.th(password_th, colspan = '2', cls = 'ca-cell')))
							for (pid, name, exists, username, password) in rows:
								if all_exist_already:
									exists.value = True # flip this here; if it used to be False, thus incuring an INSERT during POST processing, then it's True now (user now exists in database), but we couldn't alter the .exists value because it was a part of a read-only MultiDictProxy; so, we "flag" with all_exist_already upon successful INSERTs in db, and just interpret this sloppy-seeming way here
								if exists.value: # == True, though it may be 'True' after POST, and it's either False or '', so just this "if" test works....
									with t.tr():
										t.td((
											t.b(f'{name.value}: {username.value}'),
											_text_input(pid.key, pid.value, type_ = 'hidden'),
											_text_input(name.key, name.value, type_ = 'hidden'),
											_text_input(exists.key, exists.value, type_ = 'hidden'),
											_text_input(username.key, username.value, type_ = 'hidden'),
											_text_input(password.key, '', type_ = 'hidden'),
										))
										t.td(t.button('edit existing account...', type = 'button', onclick = 'load_page("%s")' % _gurl(f'/go_edit_user/{username.value}')))
										
								else:
									username_fields.append(username.key)
									password_fields.append(password.key)
									with t.tr():
										t.td((
											t.b(name.value + ':'),
											_text_input(pid.key, pid.value, type_ = 'hidden'),
											_text_input(name.key, name.value, type_ = 'hidden'),
											_text_input(exists.key, exists.value, type_ = 'hidden'),
										))
									with t.tr():
										with t.td():
											invalid_username_div = U.tag_it('username_exists_message', pid.value)
											t.div(
												_text_input(username.key, username.value,
												('required',), {'size': 12, 'style': 'text-align:left; padding: 4px;', 'pattern': valid.re_username, 'oninput': 'check_username_request("%s", this.value)' % invalid_username_div},
												'Type username here', _invalid_div(text.inv_username, username.key in invalids)),
												cls = 'field')
											_invalid_div(text.inv_username_exists, False, invalid_username_div)
										with t.td():
											t.div(_text_input(password.key, password.value,
												('required',), {'size': 12, 'style': 'text-align:left; padding: 4px;', 'pattern': valid.re_password},
												'Type password here', _invalid_div(text.inv_password, password.key in invalids)),
												cls = 'field')
										t.td(t.button('◄ Another', type = 'button', onclick = 'another_password(%s)' % password.key))

						if not all_exist_already:
							t.button("Save!", type = "button", onclick = f'print_then_submit()')
						else:
							t.p(text.what_next)
							t.div(_what_next(text.go_home, text.go_to_grammar, text.go_to_practice))

		t.script(_js_basic())
		t.script(_js_go_to())
		t.script(_js_ws(ws_url))
		t.script(_js_check_username())
		t.script(_js_validate_event())
		t.script(_js_validate_username_fields(username_fields))
		t.script(_js_validate_password_fields(password_fields))
		t.script(_js_another_password(passwords, used_passwords))
		t.script(_js_print_then_submit())
		t.script(_js_go_to())
	return d.render()

def family_user_setup(action, users, passwords, ws_url, all_exist_already, flash = None):
	used_passwords = []
	rows = []
	for u in users:
		pid = u['id']
		password = random.choice(passwords)
		passwords.remove(password)
		used_passwords.append(password)
		rows.append([
			U.KVPair(U.tag_it('pid', pid), u['id']), # yes, we'll be dealing with a MultiDict, but we still need uniquely identifiable fields for each row/record/user, so tagging them is the best way
			U.KVPair(U.tag_it('name', pid), u['first_name']),
			U.KVPair(U.tag_it('exists', pid), u['exists']),
			U.KVPair(U.tag_it('username', pid), u['username']),
			U.KVPair(U.tag_it('password', pid), password if not u['exists'] else ''),
		])
	return _family_user_setup(action, rows, [], ws_url, passwords, used_passwords, all_exist_already, flash)


def family_user_setup_retry(action, data, passwords, ws_url, invalids, all_exist_already, flash = None):
	rows = []
	row = [] # contains [(pid_fn, pid_fv), (name_fn, name_fv), (exists_fn, exists_fv), (username_fn, username_fv), (password_fn, password_fv)] (see family_user_setup())
	for key, value in data.items():
		if key.startswith('pid'):
			if row: # previously built row
				rows.append(row)
			row = [U.KVPair(key, value),]
		else:
			row.append(U.KVPair(key, value))
	if row:
		rows.append(row)

	return _family_user_setup(action, rows, invalids, ws_url, passwords, [], all_exist_already, flash)


def student_invitation(form, invitation, person, enrollments, flash = None):

	# TODO: deport these!
	cl = lambda content: t.div(content, cls = 'contact_line')
	cli = lambda content: t.div(content, cls = 'contact_line_inset')
	
	d = _doc(text.doc_prefix + 'Invitation')
	with d:
		if not flash: # if there are errors, then we are re-presenting this page; no need to say hello again
			t.p('Hello %s %s!  Please confirm that all of the following is correct...' % (person['first_name'], person['last_name']))
		else:
			_flash(flash)

		with t.div(cls = 'flex-wrap'):
			t.div('Enrollment', cls = 'title')
			with t.div(cls = 'main'):
				with t.div(cls = 'resource_record'):
					cl('Programs: ' + _format_enrollment_programs(enrollments))


		t.p('If you see any mistakes, please just contact me directly.  Thanks!')
		
	return d.render()


def appointments(links, login, settings, appointments):
	d = _doc(text.doc_prefix + 'Calendar')
	with d:
		# TODO: this is copy-pasted from resources(), for now -- CONSOLIDATE/refactor!
		with t.div(cls = 'flex-wrap'): # TODO: make a 'header_block' or something; different border color, perhaps
			t.div(t.b('Go'), cls = 'title')
			with t.div(cls = 'main'):
				with t.div(id = 'go'):
					with t.div(cls = 'ib-left'):
						for name, hint, content, url in links:
							onclick = f'window.open("{content}", "_self");' # assuming url=True
							if not url: # then assume script, or other 'raw':
								onclick = f'{content};'
							t.button(name, type = 'button', title = hint, onclick = onclick)
				with t.div(id = 'login'):
					with t.div(cls = 'ib-right'):
						if login['type'] == 'button':
							t.button(text.login_button_title, type = 'button', title = text.login_button_title, onclick = 'load_page("%s")' % _gurl('/login'))
						else:
							t.button('₪', title = 'Messages', type = 'button', onclick = 'void()') #TODO: 'load_page("%s")' % _gurl('/messages'))
							assert(login['type'] == 'menu')
							_login_dropdown(login['username'], login['switch_users'], hint = 'Switch person')

		with t.div(cls = 'flex-wrap'):
			t.div('Calendar', cls = 'title')
			with t.div(cls = 'main'):
				all_ics = '/ical_all/all.ics'
				t.a('Import ALL events', href = all_ics)
				with t.table():
					_dt = lambda d: (datetime.fromisoformat(d).strftime('%m/%d (%a)'), datetime.fromisoformat(d).strftime('%I:%M %p'))
					for appointment in appointments:
						sd, st = _dt(appointment['start'])
						ed, et = _dt(appointment['end'])
						dt2 = f'{st} - {et}' if sd == ed else '- {ed}'
						link = f"/ical/{appointment['id']}.ics"
						t.tr((t.td(sd), t.td(t.a(appointment['name'], href = _gurl(link)))))
						t.tr((t.td(f"@{appointment['location']}", cls = 'ra-cell'), t.td(dt2)))

		t.script(_js_basic())
		t.script(_js_go_to())
		t.script(_js_dropdown())
		t.script(_js_load_bg(settings))

	return d.render()


def new_user(form, host, error = None):
	title = 'New User'
	d = _doc(text.doc_prefix + title)
	with d:
		with t.form(action = form.action, method = 'post'):
			with t.fieldset():
				t.legend(title)
				_error(error)
				with t.ol(cls = 'step_numbers'):
					with t.li():
						t.p('First, create a one-word username for yourself (lowercase, no spaces)...')
						_text_input(*form.nv('new_username'), ('required', 'autofocus'), {'pattern': valid.re_username, 'oninput': 'check_username_request("username_exists_message", this.value)'}, 'Type new username here',
							_invalid_div(text.inv_username, form.is_invalid('new_username')))
						_invalid_div(text.inv_username_exists, False, 'username_exists_message')
					with t.li():
						t.p("Next, invent a password; type it in twice to make sure you've got it...")
						_text_input('password', None, ('required',), {'pattern': valid.re_password}, 'Type new password here',
							_invalid_div(text.inv_password, form.is_invalid('password')), type_ = 'password')
						_text_input('password_confirmation', None, ('required',), None, 'Type password again for confirmation',
							_invalid_div(text.inv_password_confirmation, form.is_invalid('password_confirmation'), 'password_match_message'), type_ = 'password')
					with t.li():
						t.p("Finally, type in an email address that can be used if you ever need a password reset (optional, but this may be very useful someday!)...")
						_text_input(*form.nv('email'), None, {'pattern': valid.re_email}, 'Type email address here', 
							_invalid_div(text.inv_email, form.is_invalid('email')))
				t.input_(type = "submit", value = "Done!")
		t.script(_js_basic())
		t.script(_js_ws(host = host))
		t.script(_js_validate_event())
		t.script(_js_validate_username_fields())
		t.script(_js_validate_password_fields())
		t.script(_js_validate_password_confirmation_fields())
		t.script(_js_check_username())
	return d.render()

def select_user(url, host):
	d = _doc(text.doc_prefix + 'Select User')
	with d:
		_text_input('search', None, ('autofocus',), {'autocomplete': 'off', 'oninput': 'search(this.value)', 'size': 12}, 'Search', type_ = 'search')
		t.div(id = 'content') # filtered results themselves are added here, in this `content` div, via websocket, as search text is typed (see javascript)
		# JS (intentionally at bottom of file; see https://faqs.skillcrush.com/article/176-where-should-js-script-tags-be-linked-in-html-documents and many stackexchange answers):
		t.script(_js_basic())
		t.script(_js_ws(host = host))
		t.script(_js_filter_list(url))
	return d.render()


def filter_user_list(results, url): # TODO: GENERALIZE for other lists!
	table = t.table()
	with table:
		for result in results:
			with t.tr():
				t.td(t.a(result['username'], href = '%s/%d' % (url, result['id'])))
		if len(results) >= 9:
			t.tr(t.td('... (type in search bar to narrow list)'))
	return table.render()


def arithmetic_practice(key, options, hint, selected_id):
	container = t.div()
	with container:
		_dropdown((key, options, selected_id), 'ib-left', hint = hint, task = 'arithmetic_filter')
		t.div(cls = 'clear')

		with t.div(id = 'calcs'):
			with t.table():
				with t.tr():
					t.td('Calculating...', id = 'problem', cls = 'problem') # should be immediately injected with real problem (see javascript update_arithmetic(payload))
					t.td(id = 'correct_answer', cls = 'correct_answer')
					t.td(id = 'answer', tabindex = '-1', cls = 'problem', onkeydown = 'answer_key_down(event);') # instead of t.td(t.input_(id = 'answer', type = 'text', size = 3, maxlength = 4, autofocus = 'true'), cls = 'problem_response')

			_ninepin_button = lambda value: t.button(value, type = 'button', value = str(value), cls = 'ninepin_button', onclick = 'add_ninepin(this)')
			with t.div(cls = 'ninepin'):
				for row in (2, 1, 0):
					with t.div():
						for col in (1, 2, 3):
							_ninepin_button(row * 3 + col)
				_ninepin_button(0)
				t.button('Go!', id = 'go_button', type = 'button', title = 'Push this (or hit "Enter") to check your answer', disabled = 'true', onclick = 'go();')
				t.button('←', id = 'backspace_button', type = 'button', title = 'Push this to erase/backspace/delete the last number you entered', onclick = 'backspace();')
				t.hr()
				t.div(t.button('Done!', onclick = 'done();'), '(for now)')

		with t.div(id = 'all_stats_content', style = 'display:none;'): # shown later...
			with t.table():
				with t.tr():
					t.th('All Time', colspan = 2)
				with t.tr():
					t.td('Elapsed Time:')
					t.td(id = 'stat_all_time')
				with t.tr():
					t.td('Count:')
					t.td(id = 'stat_all_count')
				with t.tr():
					t.td('Accuracy:')
					t.td(id = 'stat_all_accuracy')
				with t.tr():
					t.td('Sazzle Score:')
					t.td(id = 'stat_all_sizzle_score')
				with t.tr():
					t.td('"Sazzle Score" is a cumulative', colspan = 2)
				with t.tr():
					t.td('combo of accuracy and practice time', colspan = 2)
			t.div(t.button('Restart', onclick = 'reset();'))

		t.hr()
		with t.div(t.b('Stats')):
			t.button("Hide ▲", id = 'show_hide_stats_button', type = 'button', title = 'Show / Hide this "Stats" panel', onclick = 'show_hide_stats()') # show: "Show ▼"
			with t.div(id = 'stats_content'):
				with t.table():
					#with t.tr():
					#	t.th('This Session', colspan = 2)
					with t.tr():
						t.td('Elapsed Time:')
						t.td(id = 'stat_session_time')
					with t.tr():
						t.td('Count:')
						t.td(id = 'stat_session_count')
					with t.tr():
						t.td('Accuracy:')
						t.td(id = 'stat_session_accuracy')
					with t.tr():
						t.td('Sizzle Score:')
						t.td(id = 'stat_session_sizzle_score')
					with t.tr():
						t.td('"Sizzle Score" is a combo', colspan = 2)
					with t.tr():
						t.td('of speed and accuracy', colspan = 2)

	return container.render()


def practice(links, filters, login, user_settings, host):
	d = _doc(text.doc_prefix + 'Practice')
	with d:
		
		# TODO: this is copy-pasted from resources(), for now -- CONSOLIDATE/refactor!
		with t.div(cls = 'flex-wrap'): # TODO: make a 'header_block' or something; different border color, perhaps
			t.div(t.b('Go'), cls = 'title')
			with t.div(cls = 'main'):
				with t.div(id = 'go'):
					with t.div(cls = 'ib-left'):
						for name, hint, content, url in links:
							onclick = f'window.open("{content}", "_self");' # assuming url=True
							if not url: # then assume script, or other 'raw':
								onclick = f'{content};'
							t.button(name, type = 'button', title = hint, onclick = onclick)
				with t.div(id = 'login'):
					with t.div(cls = 'ib-right'):
						if login['type'] == 'button':
							t.button(text.login_button_title, type = 'button', title = text.login_button_title, onclick = 'load_page("%s")' % _gurl('/login'))
						else:
							t.button('₪', title = 'Messages', type = 'button', onclick = 'void()') #TODO: 'load_page("%s")' % _gurl('/messages'))
							assert(login['type'] == 'menu')
							_login_dropdown(login['username'], login['switch_users'], hint = 'Switch person')

		with t.div(cls = 'flex-wrap'): # TODO: make a 'header_block' or something; different border color, perhaps
			t.div(t.b('Do'), cls = 'title')
			with t.div(cls = 'main'):
				for key, options, hint, selected_id in filters:
					with t.div(id = '%s-container' % key):
						_dropdown((key, options, selected_id), 'ib-left', hint = hint, task = 'practice_filter')

		with t.div(cls = 'flex-wrap'):
			t.div(t.b('Practice'), cls = 'title')
			with t.div(cls = 'main', id = 'main_content'):
				t.div('Fetching practice...')
				# This div gets populated after initial ws-fetch (and in response to a filter change, etc.)...

		t.script(_js_basic())
		t.script(_js_go_to())
		t.script(_js_ws(host = host))
		t.script(_js_arithmetic())
		t.script(_js_practice())
		t.script(_js_dropdown())
		t.script(_js_load_bg(user_settings))

	return d.render()

def _go_bar(links, login):
	result = t.div(cls = 'flex-wrap') # TODO: make a 'header_block' or something; different border color, perhaps
	with result:
		t.div(t.b('Go'), cls = 'title')
		with t.div(cls = 'main'):
			with t.div(id = 'go'):
				with t.div(cls = 'ib-left'):
					for name, hint, content, url in links:
						onclick = f'window.open("{content}", "_self");' # assuming url=True
						if not url: # then assume script, or other 'raw':
							onclick = f'{content};'
						t.button(name, type = 'button', title = hint, onclick = onclick)
			with t.div(id = 'login'):
				with t.div(cls = 'ib-right'):
					if login['type'] == 'button':
						t.button(text.login_button_title, type = 'button', title = text.login_button_title, onclick = 'load_page("%s")' % _gurl('/login'))
					else:
						t.button('₪', title = 'Messages', type = 'button', onclick = 'void()') #TODO: 'load_page("%s")' % _gurl('/messages'))
						assert(login['type'] == 'menu')
						_login_dropdown(login['username'], login['switch_users'], hint = 'Switch person')
	return result

def practice_stats(links, login, user_settings, results):
	d = _doc(text.doc_prefix + 'Sazzle Scores')
	with d:
		_go_bar(links, login)
		
		with t.div(cls = 'flex-wrap'):
			t.div(t.b('Results'), cls = 'title')
			with t.div(cls = 'main', id = 'main_content'):
				with t.table():
					t.tr((t.th('username', cls = 'ca-cell'), t.th('total time',cls = 'ca-cell'), t.th('total count'), t.th('total correct count'), t.th('total accuracy'), t.th('sazzle')))
					for result in results:
						with t.tr():
							t.td(str(result['username']))
							t.td(str(result['total_time']))
							t.td(str(result['total_count']))
							t.td(str(result['total_correct_count']))
							t.td(str(result['total_accuracy']))
							t.td(str(result['sazzle']))

		t.script(_js_basic())
		t.script(_js_go_to())
		t.script(_js_dropdown())
		t.script(_js_load_bg(user_settings))
		
	return d.render()

def quiz(ws_url, db_handler, html_function, host):
	d = _doc(text.doc_prefix + 'Quiz')
	with d:
		with t.fieldset(cls = 'small_fieldset'):
			# Content container - filtered results themselves will be fed into here, via websocket (see _js_socket_quiz_manager):
			t.div(id = 'content', cls = 'quiz_content') # Note: this container will contain another div of the same class, in which everything "real" will go; see _multi_choice_question
			t.button('Go', id = "go", cls = 'quiz_button')

		with t.fieldset(cls = 'small_fieldset'):
			_url_dropdown(t.div(cls = 'dropdown'), 'subject', (
				('Timeline (sequence)', _gurl(settings.k_history_sequence)),
				('Science grammar', _gurl(settings.k_science_grammar)),
				('English vocabulary', _gurl(settings.k_english_vocabulary)),
				('English grammar', _gurl(settings.k_english_grammar)),
				('Latin vocabulary', _gurl(settings.k_latin_vocabulary))), 'Subjects...')
			_url_dropdown(t.div(cls = 'dropdown'), 'cycle_dropdown', (
				('Cycle 1', 'bogus'),
				('Cycle 2', 'bogus'),
				('Cycle 3', 'bogus'),
				('All Cycles', 'bogus'),
				('My Cycle', 'bogus')), 'Cycles...')
			_url_dropdown(t.div(cls = 'dropdown'), 'weeks_dropdown', (
				('...', 'bogus'),
				('All Weeks', 'bogus')), 'Weeks...')
			_url_dropdown(t.div(cls = 'dropdown'), 'difficulty_dropdown', (
				('Easy', 'bogus'),
				('Medium', 'bogus'),
				('Difficult', 'bogus')), 'Difficulty...')

		# JS (intentionally at bottom of file; see https://faqs.skillcrush.com/article/176-where-should-js-script-tags-be-linked-in-html-documents and many stackexchange answers):
		t.script(_js_basic())
		t.script(_js_ws(host = host))
		t.script(_js_socket_quiz_manager(ws_url, db_handler, html_function))
		t.script(_js_dropdown())
	return d.render()








def grades_filter_button(key, options, selected_id, show_grammar_option):
	r = [_dropdown((key, options, selected_id), 'ib-left'), ]
	#if show_grammar_option:
	#	r.append(t.div(t.input_(type = 'checkbox', id = 'show_grammar'), t.label('Show Grammar', for_ = 'show_grammar'), cls = 'ib-left'))
	return t.div(r).render()

def filter_button(key, options, selected_id):
	r = [_dropdown((key, options, selected_id), 'ib-left'), ]
	return t.div(r).render()
	

def resources(ws_url, filters, cycles, weeks, qargs, links, login, user_settings, main_content): # TODO: this is basically identical to select_user (and presumably other search-driven pages whose content comes via websocket); consolidate!
	d = _doc(text.doc_prefix + 'Resources')
	for_print = int(qargs.get('for_print', 0)) # 1 = no buttons, no header
	show_search = int(qargs.get('show_search', 1)) # 1 = show, 0 = don't
	show_go = int(qargs.get('show_go', 1)) # 1 = show, 0 = don't

	with d:
		if show_go and not for_print:
			with t.div(cls = 'flex-wrap'): # TODO: make a 'header_block' or something; different border color, perhaps
				t.div(t.b('Go'), cls = 'title')
				with t.div(cls = 'main'):
					with t.div(id = 'go'):
						with t.div(cls = 'ib-left'):
							for name, hint, content, url in links:
								onclick = f'window.open("{content}", "_self");' # assuming url=True
								if not url: # then assume script, or other 'raw':
									onclick = f'{content};'
								t.button(name, type = 'button', title = hint, onclick = onclick)
					with t.div(id = 'login'):
						with t.div(cls = 'ib-right'):
							if login['type'] == 'button':
								t.button(text.login_button_title, title = text.login_button_title, onclick = 'load_page("%s")' % _gurl('/login'))
							else:
								t.button('₪', title = 'Messages', onclick = 'void()') #TODO: 'load_page("%s")' % _gurl('/messages'))
								assert(login['type'] == 'menu')
								_login_dropdown(login['username'], login['switch_users'], hint = 'Switch person')

		if show_search and not for_print:
			with t.div(cls = 'flex-wrap'): # TODO: make a 'header_block' or something; different border color, perhaps
				t.div(t.b('Filter'), cls = 'title')
				with t.div(cls = 'main'):
					for title, key in filters:
						with t.div(id = '%s-container' % key):
							_dropdown_shell(key, 'ib-left', title, title)
					_dropdown(weeks[0], 'ib-right', button_class = 'cw-button', hint = 'Select START week')
					#TODO: bring!search!back!(it works, but isn't very useful in its current form; ist's more of a filter, and doesn't reset when blanked) --- t.div(_text_input('search', None, ('autofocus',), {'autocomplete': 'off', 'oninput': 'search(this.value)', 'class': 'search'}, 'Search', type_ = 'search'), cls = 'clear') # TODO: replace with a magnifying-glass gif!
					t.div(cls = 'clear') # NOTE: this is just a stand-in for the above-line: "Search" field, which we're temporarily removing; this allows the next dropdown to be "below" the top one, rather than beside it
					_dropdown(weeks[1], 'ib-right', button_class = 'cw-button', hint = 'Select END week')
					#TODO: BRING BACK! -- _dropdown(cycles, 'ib-right', button_class = 'cw-button')

		if not main_content:
			main_content = 'Loading... please refresh your browser if this message does not disappear shortly....'
		t.div(raw(main_content), id = 'content') # filtered results themselves are added here, in this `result` div, via websocket, as search text is typed (see javascript)

		# JS (intentionally at bottom of file; see https://faqs.skillcrush.com/article/176-where-should-js-script-tags-be-linked-in-html-documents and many stackexchange answers):
		t.script(_js_basic())
		t.script(_js_go_to())
		t.script(_js_ws(ws_url))
		t.script(_js_load_bg(user_settings))
		t.script(_js_filter_list())
		t.script(_js_dropdown())
		t.script(_js_calendar_widget())
		t.script(_js_show_hide_shopping())
		t.script(_js_play_pause())
		t.script(_js_play_random())
		t.script(_js_mark_assignment())
			
	return d.render()


def test_twixt(url):
	d = _doc('Test TWIXT Page')
	with d:
		t.p('This is the "TWIXT" Test page... result of main.foobar() coming soon...')
		t.div(id = 'foobar')
		
		t.script(_js_basic())
		t.script(_js_ws(host = host))
		t.script(_js_test1(url))
		
	return d.render()



g_subject_resource_handlers = dict()
def subject_resources(handler):
	def decorator(func):
		g_subject_resource_handlers[handler] = func
		return func
	return decorator


def _grammar_resources(container, spec, records, show_cw, subject_directory, render, audio_widgets, record_container_class = None, main_audio_base = None, main_audio_suffix_field = None):
	cycle_week = None
	first = True
	with container:
		for record in records:
			if cycle_week != (record['cycle'], record['week']):
				if not first:
					resource_div += t.hr()
				else:
					first = False
				# For each new week encountered, add the cycle and week numbers on rhs... # TODO: use show_cw?!
				cycle_week = (record['cycle'], record['week'])
				resource_div = t.div(cls = 'resource_record')
				buttonstrip = t.div(cls = 'buttonstrip')

				if audio_widgets and (not spec or not spec.for_print):
					filename_base = subject_directory + '/c%sw%s' % (record['cycle'], record['week'])
					filename_solo_base = filename_base + '-solo'
					if main_audio_base and main_audio_suffix_field:
						filename_base = subject_directory + '/%s%s' % (main_audio_base, record[main_audio_suffix_field])
					filename_accompanied_base = subject_directory + '/c%sw%s-chant' % (record['cycle'], record['week'])
					with buttonstrip:
						if path_exists('static/audio/' + filename_solo_base + '.pdf'): # TODO: improve! use pathstuffs!
							t.button('♬', title = 'Musical score', onclick = 'window.open("%s","_blank");' % _aurl(filename_base + '.pdf' + k_cache_version))
						#t.button('»', title = 'Accompanied song', onclick = 'play_pause("%s", this, "»");' % filename_accompanied_base)
						if path_exists('static/audio/' + filename_solo_base + '.mp3'): # TODO: improve! use pathstuffs!
							t.button('►', title = 'Audio song', onclick = 'play_pause("%s", this, "►");' % filename_solo_base)
						if path_exists('static/audio/' + filename_base + '.mp3'): # TODO: improve! use pathstuffs!
							t.button('►►', title = 'Audio song with repeat phrases', onclick = 'play_pause("%s", this, "►►");' % filename_base)
						#t.button('ℓ', title = 'Copywork')
						#t.button('Ξ', title = 'Details')
					buttonstrip_detail_solo = t.div(cls = 'buttonstrip_detail', id = filename_solo_base + '_container') # invisible at first
					with buttonstrip_detail_solo:
						t.audio(t.source(src = _aurl(filename_solo_base + '.mp3' + k_cache_version), type = 'audio/mpeg'), controls = True, preload='none', id = filename_solo_base)
					buttonstrip_detail = t.div(cls = 'buttonstrip_detail', id = filename_base + '_container') # invisible at first
					with buttonstrip_detail:
						t.audio(t.source(src = _aurl(filename_base + '.mp3' + k_cache_version), type = 'audio/mpeg'), controls = True, preload='none', id = filename_base)
						#t.button('-', title = 'Lower pitch', onclick = 'lower_pitch("%s");' % filename_base)
					buttonstrip_accompanied_detail = t.div(cls = 'buttonstrip_detail', id = filename_accompanied_base + '_container') # invisible at first
					with buttonstrip_accompanied_detail:
						t.audio(t.source(src = _aurl(filename_accompanied_base + '.mp3' + k_cache_version), type = 'audio/mpeg'), controls = True, preload = 'none', id = filename_accompanied_base)

				_add_cw(record, buttonstrip, spec)
				resource_div += buttonstrip
				if audio_widgets and (not spec or not spec.for_print):
					resource_div += buttonstrip_detail
					resource_div += buttonstrip_accompanied_detail
				if record_container_class:
					record_container = record_container_class()
					resource_div += record_container
				else:
					record_container = resource_div

			render(record, record_container)


# TODO: DEPRECATE - we no longer use this... only _assignments is used now, even for shopping
def _external_resources_DEPRECATED(container, spec, records, show_cw):
	raise Exception('DEPRECATED')
	first = True
	week = None
	for record in records:
		if first:
			first = False
			_add_cw(record, container, spec)
		elif record['week'] != week:
			container += t.hr(cls = 'clear')
			_add_cw(record, container, spec)
		week = record['week']

		resource_title = t.div(cls = 'resource_name')
		if not record['required'] > 0:
			resource_title += '[optional] '
		resource_title += t.b(record['resource_name'])
		container += resource_title
		
		if spec.shop:
			div_id = '%s%s' % (valid.k_res_prefix, record['resource_id'])
			resource_title += t.button('$', onclick = 'show_hide_shopping("%s");' % div_id)
			container += t.div(cls = 'shopping_links', id = div_id) # contents filled in via websocket upon '$' click to show_hide_shopping()
		else:
			details = ''
			if record['instructions']:
				details = record['instructions']
			if record['chapters']:
				if details:
					details += ' - '
				ch = record['chapters']
				details += 'Chapter%s: %s' % ('s' if ('-' in ch or ',' in ch) else '', ch)
			if record['pages']:
				if details:
					details += ' - '
				details += 'Pages: %s' % record['pages']
			if details:
				resource_title += ' - ' + details
		
		#TODO: ADD "more..." button/link to unfold drop-content loaded via ws  (no, just make the main text itself clickable to drop down more!)


def _show_shopping(records):
	result = t.div()
	if not records:
		result += 'Sorry, there are no shopping links for this resource at present... try back again soon?'
	else:
		with result:
			resource_note = records[0]['resource_note'] # records[0] because they're all the same; all shopping link records provided reference this same resource
			if resource_note:
				t.div('Note: %s' % resource_note, cls = 'shopping_note')
			#t.div('Click to shop...')
			for record in records:
				title = '%s (%s)' % (record['source_name'], record['type_name'])
				if record['note']: # resource_acquisition.note (in addition to the resource.note, already gleaned, above
					title += ' -- ' + record['note']
				t.div(t.a(t.img(src = _lurl(record['source_logo'])), title, href = record['url'], target = '_blank'), cls = 'shopping_link')

	return result

def show_shopping(records):
	return _show_shopping(records).render()


@subject_resources('general')
def general(container, spec, records, show_cw):
	def render(record, container): # callback function, see _grammar_resources()
		with container:
			path = _geurl('%s/%s%s' % (record['download_path'], record['filename_crux'], record['filename_suffix']))
			t.div(t.a('%s - %s' % (record['real_title'], record['description']), href = path + k_cache_version, cls = 'hover_link', target = "_blank"))

	_grammar_resources(container, spec, records, show_cw, 'general', render, False)


@subject_resources('geography')
def geography(container, spec, records, show_cw):
	cw = None

	def render(record, container): # callback function, see _grammar_resources()
		nonlocal cw
		new_cw = record['cycle'], record['week'] if record['week'] > spec.first_week else spec.first_week # that is, if the actual first week on record predates the first week that we're looking at, just show the first week we're looking at
		name = record['name']
		if new_cw != cw:
			cw = new_cw
			if not spec.no_maps:
				path = 'c%dw%02d_geography.png' % (record['cycle'], record['week'])
				container += t.div(t.img(src = _murl(path)))
		else:
			name = ' | ' + name
		container += t.span(_youglishify(str(name))) # TODO: youglishifying the "|" in the name, here! kludgy; fix!

	_grammar_resources(container, spec, records, show_cw, 'geography', render, False, t.div)

@subject_resources('multiplication_facts')
def multiplication_facts(container, spec, records, show_cw):
	def render(record, container): # callback function, see _grammar_resources()
		with container:
			t.div(t.b('%ss:' % record['operand1']))
			products = record['products'].split(',')
			with t.table(cls = 'celled'):
				with t.tbody(cls = 'celled'):
					with t.tr(cls = 'celled'):
						for operand2 in range(len(products)):
							t.td(operand2 + 1, cls = 'celled')
					with t.tr(cls = 'celled'):
						for product in products:
							t.td(product, cls = 'celled')

	_grammar_resources(container, spec, records, show_cw, 'multiplication_facts', render, True)


def _add_eqality_record(table, record, left_field_name, right_field_name, youglishit = False, audio_base = None, line2 = None):
	youglishify = _youglishify if youglishit else str

	tr = t.tr(
		t.td(t.b(youglishify(str(record[left_field_name]))), cls = 'left-equality-cell'),
	)
	right_text = record[right_field_name].replace('\\', '') # NOTE: NO LONGER youglishifying this!
	if audio_base:
		tr += t.td(
			t.button('▸', title = 'audio', onclick = '$("%s").play();' % audio_base, cls = 'mini_button'),
			t.audio(t.source(src = _aurl(audio_base + '.mp3' + k_cache_version), type = 'audio/mpeg'), controls = False, preload='none', id = audio_base),
			right_text,
			cls = 'right-equality-cell')
	else:
		tr += t.td(right_text)
	table += tr
	if line2 and record[line2]:
		table += t.tr(t.td(), t.td(str(record[line2])))

def _prefix_answer(record, youglishit = False):
	answer_prompt = record['answer_prefix'].capitalize() + ' ' + record['prompt'] if record['answer_prefix'] else record['prompt'][0].upper() + record['prompt'][1:]
	answer = '%s %s %s.' % (answer_prompt, record['answer_verb'], record['answer'])
	if youglishit:
		answer = _youglishify('%s %s %s.' % (answer_prompt, record['answer_verb'], record['answer']))
	return answer

@subject_resources('math_vocabulary')
def math_vocabulary(container, spec, records, show_cw):
	def render(record, container): # callback function, see _grammar_resources()
		_add_eqality_record(container, record, 'word', 'equivalent', False, line2 = 'line2')

	_grammar_resources(container, spec, records, show_cw, 'math', render, False, t.table)

def _format_answer(answer, youglishit = False):
	if youglishit:
		answer = _youglishify(answer, False)
	first_star_pos = answer.find('*')
	if first_star_pos >= 0 and len(answer) > first_star_pos + 1:
		prelude = answer[:first_star_pos]
		answer = prelude + '<ul><li>' + answer[first_star_pos + 1:].replace('*', '</li><li>') + '</li></ul>'
	return raw(answer)

def _format_answer2(record, youglishit = False): # stolen from _format_answer(), to try something new....
	answer = f"{record['prompt'].capitalize()} {record['answer_verb']} {record['answer']}."
	if youglishit:
		answer = _youglishify(answer, False)
	first_star_pos = answer.find('*')
	if first_star_pos >= 0 and len(answer) > first_star_pos + 1:
		prelude = answer[:first_star_pos]
		answer = prelude + '<ul><li>' + answer[first_star_pos + 1:].replace('*', '</li><li>') + '</li></ul>'
	
	return raw(answer)

def _format_answer3(record, youglishit = False): # stolen from _format_answer2(), to try something new....
	#OLD: answer = f"{record['prompt'].capitalize()} {record['answer_verb']} {record['answer']}."
	answer = _prefix_answer(record, False)
	first_star_pos = answer.find('*')
	if first_star_pos >= 0 and len(answer) > first_star_pos + 1:
		prelude = answer[:first_star_pos]
		answer = prelude + '<ul><li>' + answer[first_star_pos + 1:].replace('*', '</li><li>') + '</li></ul>'
	if youglishit:
		answer = _youglishify(answer, False)
	
	return raw(answer)

@subject_resources('science_grammar')
def science_grammar(container, spec, records, show_cw):
	def render(record, container): # callback function, see _grammar_resources()
		with container:
			if not record['continuer']:
				#OLD: t.div(t.b())
				prompt = f"{record['answer_prefix']} {record['prompt']}" if record['answer_prefix'] else record['prompt']
				if not record['addendum']:
					prompt_verb = record['prompt_verb'] if record['prompt_verb'] else record['answer_verb'] # default to the answer_verb if there is no prompt_verb
					prompt = f"What {prompt_verb} {prompt}?"
				t.div(t.b(t.a(prompt, href = _gurl('/detail/science/%d' % record['id']), target = "_blank", cls = 'hover_link')))
			t.div(_format_answer3(record, False))

	_grammar_resources(container, spec, records, show_cw, 'science', render, True)

@subject_resources('science_resources')
def science_resources(container, spec, records, show_cw):
	_external_resources(container, spec, records, show_cw)

@subject_resources('english_vocabulary')
def english_vocabulary(container, spec, records, show_cw):
	def render(record, container): # callback function, see _grammar_resources()
		if record['level'] == 1: # screen out secondary/harder/supplemental vocab words for now
			audio_base = 'english/ev%s' % record['id'] if not spec.for_print else None # "turn off" audio if spec.for_print
			_add_eqality_record(container, record, 'word', 'definition', True, audio_base)

	_grammar_resources(container, spec, records, show_cw, 'english', render, True, t.table)

@subject_resources('english_grammar')
def english_grammar(container, spec, records, show_cw):
	def render(record, container): # callback function, see _grammar_resources()
		with container:
			t.div(t.b('What %s %s?' % (record['prompt_prefix'], record['prompt'])))
			#answer = _prefix_answer(record) # TODO!
			t.div(record['answer'])
			if record['example']:
				t.div('Example: ' + record['example'])

	_grammar_resources(container, spec, records, show_cw, 'english', render, True, main_audio_base = 'eg', main_audio_suffix_field = 'english_grammar_reference')
	
@subject_resources('literature_resources')
def literature_resources(container, spec, records, show_cw):
	_external_resources(container, spec, records, show_cw)

@subject_resources('economics_resources')
def economics_resources(container, spec, records, show_cw):
	_external_resources(container, spec, records, show_cw)


@subject_resources('poetry_resources')
def poetry_resources(container, spec, records, show_cw):
	_external_resources(container, spec, records, show_cw)

@subject_resources('oration_resources')
def oration_resources(container, spec, records, show_cw):
	_external_resources(container, spec, records, show_cw)

@subject_resources('computer_resources')
def computer_resources(container, spec, records, show_cw):
	_external_resources(container, spec, records, show_cw)

@subject_resources('spanish_resources')
def spanish_resources(container, spec, records, show_cw):
	_external_resources(container, spec, records, show_cw)

@subject_resources('logic_resources')
def logic_resources(container, spec, records, show_cw):
	_external_resources(container, spec, records, show_cw)

@subject_resources('shakespeare_resources')
def shakespeare_resources(container, spec, records, show_cw):
	_external_resources(container, spec, records, show_cw)

@subject_resources('christ_resources')
def christ_resources(container, spec, records, show_cw):
	_external_resources(container, spec, records, show_cw)

@subject_resources('math_resources')
def math_resources(container, spec, records, show_cw):
	_external_resources(container, spec, records, show_cw)


@subject_resources('latin_vocabulary')
def latin_vocabulary(container, spec, records, show_cw):
	def render(record, container): # callback function, see _grammar_resources()
		audio_base = 'latin/lv%s' % record['id'] if not spec.for_print else None # "turn off" audio if spec.for_print
		_add_eqality_record(container, record, 'word', 'translation', False, audio_base)

	_grammar_resources(container, spec, records, show_cw, 'latin', render, True, t.table)

@subject_resources('latin_grammar')
def latin_grammar(container, spec, records, show_cw):
	def render(record, container): # callback function, see _grammar_resources()
		with container:
			t.div(t.b(record['name']))
			t.div(record['pattern'])
			if record['worked']: # TODO: PUT this into "more details" drop?
				t.div('Example: %s - %s' % (record['worked'], record['translated']))

	_grammar_resources(container, spec, records, show_cw, 'latin', render, True, main_audio_base = 'lg', main_audio_suffix_field = 'latin_grammar_reference')

@subject_resources('latin_resources')
def latin_resources(container, spec, records, show_cw):
	_external_resources(container, spec, records, show_cw)

@subject_resources('history_grammar')
def history_grammar(container, spec, records, show_cw):
	def render(record, container): # callback function, see _grammar_resources()
		with container:
			t.div(t.b(t.a('%s - tell me more' % record['name'], href = _gurl('/detail/event/%d' % record['event']), target = "_blank", cls = 'hover_link')))
			text = str(record['primary_sentence'] + _format_dates(record))
			if spec.secondaries and record['secondary_sentence']:
				text += ' [' + record['secondary_sentence'] + ']'
			t.div(text)

	_grammar_resources(container, spec, records, show_cw, 'history', render, True)

@subject_resources('history_resources')
def history_resources(container, spec, records, show_cw):
	_external_resources(container, spec, records, show_cw)

@subject_resources('timeline')
def timeline(container, spec, records, show_cw):
	def render(record, container): # callback function, see _grammar_resources()
		if not record['subseq'] or spec.secondaries:
			container += t.div(_event_formatted(record, spec.for_print, spec.timeline_sentences))

	_grammar_resources(container, spec, records, show_cw, 'timeline', render, True)


@subject_resources('history_assignments')
def history_assignments(container, spec, records, show_cw):
	_assignments(container, spec, records, show_cw)

@subject_resources('geography_assignments')
def geography_assignments(container, spec, records, show_cw):
	_assignments(container, spec, records, show_cw)

@subject_resources('computer_assignments')
def computer_assignments(container, spec, records, show_cw):
	_assignments(container, spec, records, show_cw)

@subject_resources('spanish_assignments')
def spanish_assignments(container, spec, records, show_cw):
	_assignments(container, spec, records, show_cw)

@subject_resources('logic_assignments')
def logic_assignments(container, spec, records, show_cw):
	_assignments(container, spec, records, show_cw)

@subject_resources('shakespeare_assignments')
def shakespeare_assignments(container, spec, records, show_cw):
	_assignments(container, spec, records, show_cw)

@subject_resources('christ_assignments')
def christ_assignments(container, spec, records, show_cw):
	_assignments(container, spec, records, show_cw)

@subject_resources('latin_assignments')
def latin_assignments(container, spec, records, show_cw):
	_assignments(container, spec, records, show_cw)

@subject_resources('math_assignments')
def math_assignments(container, spec, records, show_cw):
	_assignments(container, spec, records, show_cw)

@subject_resources('literature_assignments')
def literature_assignments(container, spec, records, show_cw):
	_assignments(container, spec, records, show_cw)

@subject_resources('economics_assignments')
def economics_assignments(container, spec, records, show_cw):
	_assignments(container, spec, records, show_cw)

@subject_resources('english_assignments')
def english_assignments(container, spec, records, show_cw):
	_assignments(container, spec, records, show_cw)

@subject_resources('science_assignments')
def science_assignments(container, spec, records, show_cw):
	_assignments(container, spec, records, show_cw)

@subject_resources('poetry_assignments')
def poetry_assignments(container, spec, records, show_cw):
	_assignments(container, spec, records, show_cw)

@subject_resources('oration_assignments')
def oration_assignments(container, spec, records, show_cw):
	_assignments(container, spec, records, show_cw)


def _assignments(container, spec, records, show_cw):
	cw = None
	resource_name = None
	name_container = None
	hr = False
	new_list = True
	ul = None

	for record in records:
		new_cw = record['cycle'], record['week'] if record['week'] > spec.first_week else spec.first_week # that is, if the actual first week on record predates the first week that we're looking at, just show the first week we're looking at
		new_resource_name = record['resource_name']
		if new_cw != cw:
			new_list = True
			cw = new_cw
			if hr:
				container += t.hr(cls = 'clear')
			hr = cw[1] >= spec.first_week # don't draw a line next time 'round if our current record's week number preceeds what we're spec'd to look at (this can happen for records that whose first_week is earlier than spec.first_week because the record's last_week may be well within spec's range).  For instance, in Literature, a prefix assignment item might apply to two weeks; if the user is looking at the latter, they want to see the prefix, but don't want a line separating it from the rest of the assignment, which would seem like a meaningless line
			_add_cw(record, container, spec)
		shopping = ''
		if resource_name != new_resource_name:
			new_list = True
			resource_name = new_resource_name
			res_id = record['resource_id']
			div_id = '%s%s' % (valid.k_res_prefix, res_id)
			title = t.div(resource_name, cls = 'resource_name')
			container += title

			# Set up "shopping" div -- visible and filled if spec.shop; invisible but poised for ws-fetch, to fill, on resource-by-resource basis, if not spec.shop
			if not spec.for_print:
				#TODO: hook up the "details" to work! --  title += t.button('...', onclick = 'show_hide_details("%s");' % div_id, cls = 'chaser'),
				title += t.button('$', onclick = 'show_hide_shopping("%s");' % div_id, cls = 'chaser'),
				if spec.shop and (not spec.logged_in or (spec.logged_in and not record.get('complete'))):
					shopping = _show_shopping(record['shop'])


		if new_list:
			new_list = False
			ul = t.ul()
			if spec.logged_in:
				ul = t.ul(cls = 'bulletless') # because we'll be using checkboxes
			container += ul

		# Assignments:
		instruction = record['instruction']
		instruction = instruction.replace('{chapters}', str(record['chapters']))
		instruction = instruction.replace('{pages}', str(record['pages']))
		instruction = instruction.replace('{items}', str(record['items']))
		instruction = instruction.replace('{skips}', str(record['skips']) if record['skips'] else '')
		if record['optional']:
			instruction = '<b>[optional]</b> ' + instruction
		grade_first = record['grade_first']
		grade_last = record['grade_last']
		#TEMP COMMENT-OUT!!!!!!!! --- too many students now are in different grades for different subjects, and this needlessly (and constantly) "shows" that when they're logged in and looking at their personal syllabus (or looking at their printed syllabus)... consider just adding a qarg/spec item called show_grades which could be checked here, and grades shown only if that flag is true AND the following conditions are met (note: don't just replace!  b/c then e.g., for IEW, e.g., you'll get grade prefixes on all lines, even those that apply to the full span - it'll just be really ugly)
		#if not ((not grade_first and not grade_last) or (record['program_grade_first'] == grade_first and record['program_grade_last'] == grade_last)) and spec.grade == 0: # i.e., if this record does **not** apply to everybody AND the spec isn't set to show only one grade anyway, then...
		#	if grade_first != grade_last:
		#		instruction = f'[Grades {grade_first}-{grade_last}] ' + instruction
		#	else:
		#		instruction = f'[Grade {grade_first}] ' + instruction
		more_attrs = {}
		if spec.logged_in and record['complete']:
			more_attrs['checked'] = 'true' # 'true' can be anything at all; with 'checked' attr present at all, we're checked
		if spec.logged_in:
			ul += t.li(t.input_(type = 'checkbox', onclick = f"mark_assignment({record['assignment_id']}, this);", **more_attrs), raw(instruction))
		else:
			ul += t.li(raw(instruction))

		if shopping:
			container += t.div(shopping, cls = 'shopping_links', style = 'display:block;' if shopping else 'display:none;', id = div_id) # if no 'shopping', then contents will be filled in, as needed, via websocket upon '$' click to (any given) show_hide_shopping()


def _new_subject_section(container, subject_title):
	result = t.div(cls = 'main')
	container += t.div(t.div(subject_title, cls = 'title'), result, cls = 'flex-wrap')
	return result


def resource_list(spec, results, show_cw = True):
	# Cycle, Week, Subject, Content (subject-specific presentation, option of "more details"), "essential" resources (e.g., song audio)
	container = t.div(cls = 'resource_list')
	for result in results:
		# See if we need to display this subject container at all:
		moot = True
		for subresult in result.subresults:
			if subresult.records:
				moot = False
				break
		if not moot: # only build the subject container and fill it if any actual results were found in the above little test
			subject_container = _new_subject_section(container, result.subject_title)
			first = True
			for subresult in result.subresults:
				if not first:
					subject_container += t.hr(cls = 'bighr')
				else:
					first = False
				handler = g_subject_resource_handlers.get(subresult.handler)
				if handler:
					handler(subject_container, spec, subresult.records, show_cw)
	return container.render()


def _youglishify(text, rawify = True):
	result = re.sub(r'(\w+)', r'<a href="https://youglish.com/pronounce/\1/english?" class="hover_link" target="_blank">\1</a>', text)
	if rawify:
		return raw(result)
	#else:
	return result

def _detail_doc(title, subject_section_title, table, record, renderer, host):
	d = _doc(text.doc_prefix + title)
	section = _new_subject_section(d, subject_section_title)
	_grammar_resources(section, None, (record,), True, table, renderer, True)

	with d:
		# JS (intentionally at bottom of file; see https://faqs.skillcrush.com/article/176-where-should-js-script-tags-be-linked-in-html-documents and many stackexchange answers):
		t.script(_js_basic())
		t.script(_js_ws(host = host))
		t.script(_js_play_pause())
	return d.render()

def _add_signs(signs, container):
	if signs:
		ull = t.ul(cls = 'signs')
		container += t.div((t.b('Signs: '), t.span(('(provided by ', t.a('signingsavvy.com', href = 'https://www.signingsavvy.com/', target = "_blank"), ')')), ull))
		for sign in signs:
			#ull += t.li(t.a(sign['word'], href = sign['url'], target = "_blank", cls = 'hover_link'))
			#ull += t.li((sign['word'], t.br(), t.iframe(width='280', height='157', src = sign['url'], title = sign['word'], frameborder = "0", allow = "accelerometer;", allowfullscreen = '1')))
			title = [sign['word']]
			if sign['real_word']:
				title += ' (%s)' % sign['real_word']
			ull += t.li((
				t.a(title, href = sign['reference_url'], target = "_blank", cls = 'hover_link'), t.br(), 
				t.video(t.source(src = sign['url']), width = '280', height = '157', controls = '1', loop = '1')
			))

def science_detail(record, details, signs, host):
	def render(record, container):
		with container:
			t.div(_format_answer(record['answer'], True))
			if record['note']:
				t.hr(cls = 'smallhr')
				t.div(_youglishify(record['note']))
		container += t.hr(cls = 'bighr')
		_add_signs(signs, container)

	return _detail_doc('Science Detail - ' + record['prompt'], 'Science', 'science', record, render, host)


def timeline_event_detail(record, details, signs, host):
	
	def render(record, container): # callback function, see _grammar_resources()
		with container:
			t.div(t.b(_event_formatted(record, False, False, False))) # false on the timeline_sentence because we're including it explicitly below, youglishified
			t.div((_youglishify(str(record['primary_sentence'])), _format_dates(record)))
			if record['secondary_sentence']:
				t.hr(cls = 'smallhr')
				t.div(_youglishify(record['secondary_sentence']))
			t.hr(cls = 'bighr')
			t.div((t.b('Region: '), record['location']))
			t.hr(cls = 'bighr')
			
		ul = None
		title = None
		if details:
			for detail in details:
				detail_detail = detail['detail'] if not detail['url'] else t.a(detail['detail'], href = detail['url'], target = "_blank")
				if title != detail['detail_title']:
					title = detail['detail_title']
					ul = None # reset
					if not detail['sequence']: # singleton
						container += t.div((t.b(title), ': ', detail_detail))
						title = None # reset
					else:
						container += t.div((t.b(title)))
						ul = t.ul(cls = 'timeline')
						container += ul
						ul += t.li(detail_detail)
				else: # assert(ul != None)
					ul += t.li(detail_detail)
			container += t.hr(cls = 'bighr')
		_add_signs(signs, container)

	return _detail_doc('Timeline Event Detail - ' + record['name'], 'Timeline', 'timeline', record, render, host) # TODO: change 'Timeline' to 'History?!'
	

# -----------------------------------------------------------------------------
# Question handlers:

exposed = dict()
def expose(func):
	exposed[func.__name__] = func
	return func

@expose
def multi_choice_english_grammar_question(question, options):
	return _multi_choice_question(question, options, 'Define or identify', question['prompt'], 'answer')

@expose
def multi_choice_english_vocabulary_question(question, options):
	return _multi_choice_question(question, options, 'What is the definition of', question['word'], 'definition')

@expose
def multi_choice_latin_vocabulary_question(question, options):
	return _multi_choice_question(question, options, 'What is the translation for', question['word'], 'translation')

@expose
def multi_choice_science_question(question, options):
	return _multi_choice_question(question, options, 'Define', question['prompt'], 'answer')

@expose
def multi_choice_history_sequence_question(question, options):
	d = _start_question('Where does', question['name'], 'belong in this sequence of events?')
	with d:
		_add_option(d, '0', 'First')
		for record in options:
			_add_option(d, record['id'], 'After "%s"' % record['name'])
	return d.render()


# -----------------------------------------------------------------------------
# Utils:

#TODO: deport some of these?

_dress_bool_attrs = lambda attrs: dict([(f, True) for f in attrs])
_gurl = lambda url: settings.k_url_prefix + url # 
_surl = lambda url: settings.k_static_url + url # static
_geurl = lambda url: settings.k_static_url + 'general/' + url # "general" (e.g., copywork; will fix better later
_scurl = lambda url: settings.k_static_url + 'science/' + url 
_murl = lambda url: settings.k_static_url + 'maps/' + url
_aurl = lambda url: settings.k_static_url + 'audio/' + url # audio
_iurl = lambda url: settings.k_static_url + 'images/' + url # images
_lurl = lambda url: settings.k_static_url + 'images/logos/' + url # logos
_ws_url = lambda host: URL.build(scheme = settings.k_ws, host = host, path = settings.k_ws_url_prefix + '/ws_messages')


def _doc(title, css = None, scripts = None):
	d = document(title = title)
	with d.head:
		t.meta(name = 'viewport', content = 'width=device-width, initial-scale=1')
		t.link(href = settings.k_static_url + 'css/main.css' + k_cache_version, rel = 'stylesheet')
	return d

def _flash(flash):
	if flash:
		errors, messages = flash
		if errors or messages:
			with t.div(cls = 'flash'):
				for error in errors:
					t.div(error, cls = 'error')
				for message in messages:
					t.div(message, cls = 'message')

def _error(error):
	if error:
		_flash(((error,), ()))

def _invalid_div(message, visible, id = None):
	'''
	`message` is the message to display when the input is reckoned invalid.
	This may be specified right up front, by setting `visible` to True (e.g., if a POST
	processed the data and found it to be invalid), but it's also common to set `attrs`
	(e.g., in _text_input()) to include something like:
		{'pattern': valid.re_username}
	In this case, with the _text_input() setup, when the pattern-match fails, the invalid
	(`message`) is set to "visible" in real-time, for the user to see, while typing.
	NOTE that BOTH of these may be vital - they are intentionally redundant.  For instance,
	If a user (setting up a new_user, e.g.) uses invalid symbols in his username, it's nice to
	let that user know about the invalidity in real time, before he pushes "go".  But, if
	a user figures out how to POST data with invalid characters anyway (e.g., attempting
	a hack), we still must, of course, check (re-validate) server-side, to detect this, and
	then, with this div (returned below), with the `visible` set to True right off the bat,
	we can tell the user that the input (attempted in the POST) was invalid (if, indeed,
	the user was trying to hack, he/she already knows this, but, nevertheless...).
	'''
	return t.div(message, cls = 'invalid', style = 'display:block;' if visible else 'display:none;', id = id if id else '')

def _combine_attrs(attrs, bool_attrs):
	if attrs == None:
		attrs = {}
	if bool_attrs:
		attrs.update(_dress_bool_attrs(bool_attrs))
	return attrs

def _text_input(name, value, bool_attrs = None, attrs = None, label = None, invalid_div = None, type_ = 'text', internal_label = True):
	'''
	The 'name' string is expected to be a lowercase alphanumeric "variable name" without spaces.
	Use underscores ('_') to separate words for a mult-word name.
	`label` will be calculated as name.replace('_', ' ').title() unless `label` is provided.
	Set `type_` to 'password' for a password input field.
	`invalid_div` is usually fabricated by a call to _invalid_div() - see that note for special details.
	'''
	if not label:
		label = name.replace('_', ' ').title()
	attrs = _combine_attrs(attrs, bool_attrs)
	
	i = t.input_(name = name, id = name, type = type_, **attrs)
	if value:
		i['value'] = value
	if internal_label:
		i['placeholder'] = label
		result = t.label(i)
	else:
		result = t.label(label + ':', i)
	if invalid_div:
		result += invalid_div
	return result

def _url_dropdown(container, id, options, title = None, hint = ''):
	# TODO: new style has options[0] IS id! (i.e., we can get rid of the extra "id" arg, above
	if not title:
		title = options[0][1]
	title += ' ▾'
	with container:
		t.button(title, cls = 'dropdown-button', title = hint, onclick = 'choose_dropdown_item(%s)' % id)
		with t.div(id = id, cls = 'dropdown-content'):
			for option_title, option in options:
				t.div(option_title, onclick = 'load_page("%s")' % option)

def _login_dropdown(username, switch_users, hint = ''):
	options = []
	if switch_users:
		options.extend([(user['username'], _gurl('/switch_user/' + user['username'])) for user in switch_users])
	options.append(('Log out', _gurl('/logout')))
	#TODO: add "settings" (?)
	_url_dropdown(t.div(cls = 'dropdown'), 'login_dropdown', options, username, hint = hint)

def _dropdown_DEPRECATE(filt, qargs, cls, title = None, button_class = None, hint = '', task = 'filter'):
	key, options = filt
	if not options:
		return t.div() # empty div means there's nothing there - no options from which user might choose

	start_option_id = qargs.get(key)

	content_id = key
	button_id = '%s-button' % key
	drop_content = t.div(id = content_id, cls = 'dropdown-content')
	with drop_content:
		for option_title, option_id in options:
			t.div(option_title, onclick = 'choose_dropdown_option("%s", "%s", "%s", "%s", "%s")' % (key, option_id, option_title, button_id, task))
			if start_option_id and str(start_option_id) == str(option_id):
				title = option_title # override title with selected option
	if not title:
		title = options[0][0]

	button_classes = 'dropdown-button'
	if button_class:
		button_classes += ' ' + button_class
	return t.div(
		t.button(title + ' ▾', cls = button_classes, type = 'button', id = button_id, title = hint, onclick = 'choose_dropdown_item(%s)' % content_id),
		drop_content,
		cls = cls,
	)

def _dropdown_base(key):
	button_id = '%s-button' % key
	drop_content = t.div(id = key, cls = 'dropdown-content')
	return button_id, drop_content

def _dropdown_result(title, button_classes, button_id, hint, key, drop_content, cls):
	return t.div(
		t.button(title + ' ▾', cls = button_classes, type = 'button', id = button_id, title = hint, onclick = 'choose_dropdown_item(%s)' % key),
		drop_content,
		cls = cls,
	)

def _dropdown(data, cls, title = None, button_class = None, hint = '', task = 'filter'):
	key, options, selected_id = data # 'options' is a tuple of two-tuples, like: (('option 1', 'op1_id'), ('option 2', 'op2_id')); selected_id should be None or set like 'op2_id'
	if not options:
		return t.div() # empty div means there's nothing there - no options from which user might choose

	button_id, drop_content = _dropdown_base(key)
	with drop_content:
		for option_title, option_id in options:
			t.div(option_title, onclick = 'choose_dropdown_option("%s", "%s", "%s", "%s", "%s")' % (key, option_id, option_title, button_id, task))
			if selected_id and str(selected_id) == str(option_id):
				title = option_title # override title with selected option
	if not title:
		title = options[0][0]

	button_classes = 'dropdown-button'
	if button_class:
		button_classes += ' ' + button_class
	return _dropdown_result(title, button_classes, button_id, hint, key, drop_content, cls)

def _dropdown_shell(key, cls, title, hint = ''):
	button_id, drop_content = _dropdown_base(key)
	return _dropdown_result(title, 'dropdown_button', button_id, hint, key, drop_content, cls)


def _add_cw(record, div, spec = None):
	# For now: not showing the "cycle" - it just takes up screen real estate
	'''
	cycle = record['cycle']
	if cycle == 0: # TODO: hardcode for id 0, "All Cycles"
		cycle = 'All'
	else:
		cycle = 'C-%s' % cycle
	'''
	with div:
		#temporarily, not showing cycle: t.div(cycle, cls = 'cw')
		week = record['week']
		if spec and record['week'] < spec.first_week: # that is, if the actual first week on record predates the first week that we're looking at, just show the first week we're looking at:
			week = spec.first_week
		t.div('W-', week, cls = 'cw')

def _add_cw_spacer(div):
	with div:
		t.div('. ', cls = 'cw-spacer')

def _format_dates(record):
	result = ' '
	if not record['fake_start_date']:
		result += '('
		# Start date:
		if record['start_circa']:
			result += 'c.'
		start = record['start']
		if start < 0:
			start = str(-start) + ' BC'
		else:
			start = str(start)
		result += start
		# End date:
		end = record['end']
		if end:
			result += ' - '
			if record['end_circa']:
				result += 'c.'
			if end < 0:
				end = str(-end) + ' BC'
			elif record['start'] < 0:
				end = str(end) + ' AD'
			else:
				end = str(end)
			result += end
		result += ')'
	return result

def _event_formatted(record, for_print, timeline_sentences, detail_link = True):
	result = record['name'] if detail_link else _youglishify(record['name'])
	result += _format_dates(record)
	if record['subseq']: # "extra" event
		result = '[' + result + ']'

	if timeline_sentences:
		result = t.b(result)
	else:
		result = t.span(result)

	final = t.div()
	if for_print:
		final += result
		if timeline_sentences:
			final += t.span(' ' + record['primary_sentence'])
	else:
		filename_base = 'timeline/e%s' % record['id']
		final += t.button('▸', title = 'audio', onclick = '$("%s").play();' % filename_base, cls = 'mini_button')
		final += t.audio(t.source(src = _aurl(filename_base + '.mp3' + k_cache_version), type = 'audio/mpeg'), controls = False, preload='none', id = filename_base)
		if detail_link:
			final += t.a(result, href = _gurl('/detail/event/%d' % record['id']), target = "_blank", cls = 'hover_link')
		else:
			final += result
		if timeline_sentences:
			final += t.span(' ' + record['primary_sentence'])

	return final

def _what_next(*args):
	result = []
	for title, link in args:
		result.append(t.div(t.button(title, type = "button", onclick = f'go_to("{link}")')))
	return result


# -----------------------------------------------------------------------------
# Question-handler helpers:

def _start_question(prompt_prefix, prompt_text, prompt_postfix = None):
	d = t.div(cls = 'quiz_content')
	with d:
		with t.div(cls = 'quiz_question_content'):
			t.div(prompt_prefix, cls = 'quiz_question_prompt')
			t.div(prompt_text, cls = 'quiz_question')
			if prompt_postfix:
				t.div(prompt_postfix, cls = 'quiz_question_prompt_postfix')
	return d

def _add_option(d, id, label):
	with d:
		with t.div(cls = 'quiz_answer_option'):
			t.input(type = 'radio', id = id, name = 'choice', value = id)
			t.label(label, fr = id, cls = 'answer_option_label')

def _multi_choice_question(question, options, prompt_prefix, prompt_text, option_field_name, prompt_postfix = None):
	d = _start_question(prompt_prefix, prompt_text, prompt_postfix)
	with d:
		for record in options:
			_add_option(d, record['id'], record[option_field_name])
	return d.render()

# -----------------------------------------------------------------------------
# Javascript:

def _js_basic():
	return raw('''
	
	function $(id) {
		return document.getElementById(id);
	};
	
	''')

def _js_load_bg(settings):
	return raw('''
		const element = document.querySelector('.main');
		if (element != null) {
			element.style.backgroundColor = "%(bg_color)s";
			//document.getElementsByClassName("main").style.backgroundColor = "#eff7f6";
		}
	''' % settings)

def _js_ws(url = None, host = None):
	if not url:
		url = _ws_url(host) # backup plan (Future: ONLY plan!)
	return raw('''
	var ws = new WebSocket("%(url)s");

	ws.onmessage = function(event) {
		var payload = JSON.parse(event.data);
		switch(payload.task) {
			case "check_username":
				check_username_reply(payload.div, payload.reply);
				break;
			case "show_resources":
				show_resources(payload);
				break;
			case "show_shopping":
				show_shopping(payload);
				break;
			case "set_random_url_playlist":
				set_random_url_playlist(payload.playlist);
				break;
			case "show_arithmetic":
				show_arithmetic(payload);
				update_arithmetic(payload);
				break;
			case "arithmetic_problem":
				update_arithmetic(payload);
				break;
			case "arithmetic_totals":
				arithmetic_totals(payload);
				break;
			case "pong":
				// good! TODO: do something about this(?), even though there's nothing more to do to complete the loop (we'll send the next ping according to a timer (below); no need to "send" anything now, in reply)
				break;
		}
	};
	
	function ws_send(message) {
		if (!ws || ws.readyState == WebSocket.CLOSING || ws.readyState == WebSocket.CLOSED) {
			alert("Lost connection... going to reload page....");
			location.reload();
		} else {
			//console.log("SENDING ws message: " + JSON.stringify(message));
			ws.send(JSON.stringify(message));
		}
	};
	
	function pingpong() {
		if (!ws) return;
		if (ws.readyState !== WebSocket.OPEN) return;
		// else:
		ws_send({task: "ping"});
	};
	setInterval(pingpong, 5000); // 5-second heartbeat; default timeouts (like nginx) are usually set to 60-seconds

	''' % {'url': url})

def _js_socket_quiz_manager(url, db_handler, html_function):
	# This js not served as a static file for two reasons: 1) it's tiny and single-purpose, and 2) its code is tightly connected to this server code; it's not a candidate for another team to maintain, in other words; it also relies on our URL (for the websocket), whereas true static files might be served by a reverse-proxy server from anywhere, and won't tend to contain any references to the wsgi urls
	return raw('''
		
	var ws = new WebSocket("%(url)s");
	var check = 0;
	var go_button = $("go");

	ws.onmessage = function(event) {
		var payload = JSON.parse(event.data);
		switch(payload.call) {
			case "start":
				send_answer(-1); // kick-start
				break;
			case "content":
				$("content").innerHTML = payload.content;
				check = payload.check;
				go_button.disabled = false;
				break;
		}
	};
	function send_answer(answer_id) {
		ws_send({call: "answer", db_handler: "%(db_handler)s", html_function: "%(html_function)s", answer_id: parseInt(answer_id, 10)});
	};
	
	go_button.onclick = function() {
		submit();
	};
	function submit() {
		//choice.disabled = true;
		go_button.disabled = true; // until we get the next question
		const rbs = document.querySelectorAll('input[name = "choice"]');
		let selected = null;
		for (const rb of rbs) {
			if (rb.checked) {
				selected = rb;
				break;
			}
		}
		var show_answer_delay = 2000; // assume failure (parameterize?!)
		var chosen_answer = -1; // nothing chosen
		if (selected != null) {
			chosen_answer = selected.value
			if (selected.value == check) { // correct answer chosen!
				show_answer_delay = 500; // don't show as long
			}
		}
		else { } // TODO: handle no selection! Allow user to skip?!

		check_element = $(check);
		check_element.parentElement.classList.remove("quiz_answer_option");
		check_element.parentElement.classList.add("quiz_right_answer_option");
		setTimeout(function() { send_answer(selected.value); }, show_answer_delay);

	};
	''' % {'url': url, 'db_handler': db_handler, 'html_function': html_function})


def _js_test1(url):
	r = raw('''
	var ws = new WebSocket("%(url)s");
	ws.onmessage = function(event) {
		var payload = JSON.parse(event.data);
		switch(payload.call) {
			case "content":
				$("foobar").innerHTML = payload.data;
				break;
		}
	};
	''' % {'url': url})

	return r
	
	
def _js_filter_list():
	# This js not served as a static file for two reasons: 1) it's tiny and single-purpose, and 2) its code is tightly connected to this server code; it's not a candidate for another team to maintain, in other words; it also relies on our URL (for the websocket), whereas true static files might be served by a reverse-proxy server from anywhere, and won't tend to contain any references to the wsgi urls

	# This is the websocket code for filtering, and a search() (filter) function, which is the "standard"
	r = raw('''

	function show_resources(payload) {
		$("content").innerHTML = payload.content;
		spec = JSON.parse(payload.spec);
		fw_button = $("first_week-button");
		if (fw_button) { // this basically means that we're printing only
			fw_button.innerHTML = "W-" + spec.first_week + " ▾";
			$("last_week-button").innerHTML = "W-" + spec.last_week + " ▾";
			if (payload.programs != null)
				$("program-container").innerHTML = payload.programs;
			if (payload.grades == -1) // -1 is signal for "don't show"
				$("grade-container").innerHTML = '';
			else if (payload.grades != null)
				$("grade-container").innerHTML = payload.grades;
			if (payload.subjects != null)
				$("subject-container").innerHTML = payload.subjects;
		}
		// Call for string of random-audio-urls... but NOTE: this doesn't seem to be the best place for this, as this _js_filter_list() may be part of a page that does not avail the random-audio urls...  but moving it down to there ran us into trouble with the variable ws being available; not sure why, yet!
		request_new_random_url_playlist();
	};

	function show_shopping(payload) {
		$(payload.div_id).innerHTML = payload.result;
	};

	// "search" is the standard filter:
	function search(str) {
		ws_send({task: "filter", filter: "search", data: str});
	};
	''')

	return r


def _js_check_username():
	# This js not served as a static file for two reasons: 1) it's tiny and single-purpose, and 2) its code is tightly connected to this server code; it's not a candidate for another team to maintain, in other words; it also relies on our URL (for the websocket), whereas true static files might be served by a reverse-proxy server from anywhere, and won't tend to contain any references to the wsgi urls
	return raw('''
	function check_username_reply(div, reply) {
		$(div).style.display = ((reply == 'exists') ? 'block' : 'none');
	};
	function check_username_request(div, username) {
		ws_send({task: "check_username", div: div, string: username});
	};
	''')

def _js_another_password(passwords, used_passwords):
	make_array = lambda lst: ', '.join(['"%s"' % each for each in lst])
	return raw('''
	passwords = [%(passwords)s];
	used_passwords = [%(used_passwords)s];
	function another_password(field_id) {
		const r = Math.floor(Math.random() * passwords.length);
		password = passwords[r];
		passwords.splice(r, 1); // pop the new password from the set
		passwords.push(field_id.value); // and return the current password to the 'available' list
		var i = used_passwords.indexOf(field_id.value);
		if (i > -1) { used_passwords.splice(i, 1); }
		used_passwords.push(password);
		field_id.value = password;
		validate_target(field_id);
	};
	''' % {'passwords': make_array(passwords), 'used_passwords': make_array(used_passwords)})

def _js_print_then_submit():
	return raw('''
	var print_warning_shown = false;
	function print_then_submit() {
		if (print_warning_shown) {
			print_warning_shown = false; // reset for a future encounter
			$("save_users").submit();
		} else {
			alert("%s");
			print_warning_shown = true;
		}
	};
	''' % text.print_account_info_first)

def _js_go_to():
	return raw('''
		function load_page(url) {
			window.location.href = url;
		};

		function go_to(url) {
			window.location.href = "%s" + url;
		};
	''' % settings.k_url_prefix)

def _js_validate_event():
	return raw('''
	function validate(evt) {
		var e = evt.currentTarget;
		validate_target(e);
	};
	function validate_target(target) {
		target.nextElementSibling.style.display = target.checkValidity() ? "none" : "block";
	};
	''')

def _js_validate_username_fields(fields = ('username',)):
	return raw(' '.join(["$('%s').addEventListener('input', validate);" % field for field in fields]))

def _js_validate_password_fields(fields = ('password',)):
	return raw(' '.join(["$('%s').addEventListener('blur', validate);" % field for field in fields]))

def _js_validate_email_field():
	return raw('''
	$('email').addEventListener('blur', validate);
	''')

def _js_validate_password_confirmation_fields():
	return raw('''
	$('password_confirmation').addEventListener('blur', validate_passwords);
	function validate_passwords(evt) {
		$('password_match_message').style.display = $('password_confirmation').value == "" || $('password').value == $('password_confirmation').value ? "none" : "block";
	};
	''')

def _js_dropdown():
	return raw('''
	/* When the user clicks on the button,
	toggle between hiding and showing the dropdown content */
	function choose_dropdown_item(element) {
		element.classList.toggle("show");
	};

	function choose_dropdown_option(key, option_id, option_title, button_id, task) {
		stop_random_play();
		ws_send({task: task, filter: key, data: option_id});
		$(button_id).innerHTML = option_title;
	};

	// Close the dropdown menu if the user clicks outside of it
	window.onclick = function(event) {
	if (!event.target.matches('.dropdown-button')) {
		var dropdowns = document.getElementsByClassName("dropdown-content");
		var i;
		for (i = 0; i < dropdowns.length; i++) {
			var openDropdown = dropdowns[i];
			if (openDropdown.classList.contains('show')) {
			openDropdown.classList.remove('show');
			}
		}
	} };
	''')

def _js_calendar_widget():
	return raw('''
		/* javascript here... */
	''')

def _js_show_hide_shopping():
	return raw('''
		function show_hide_shopping(div_id) {
			// TODO: put a spinner in the button!
			var div = $(div_id);
			if (div.style.display === "block") {
				div.style.display = "none";
			} else {
				div.style.display = "block";
				if (div.innerHTML == "") {
					ws_send({task: "show_shopping", resource_id: div_id});
				}
			}
		};
	''')

def _js_play_pause():
	return raw('''
		function play_pause(audio_id, button, play_character) {
			var audio = $(audio_id);
			var container = $(audio_id + '_container');
			if (!audio.paused || container.style.display === "block") {
				button.innerHTML = play_character;
				container.style.display = "none";
				audio.pause();
				audio.currentTime = 0;
			} else {
				audio.onended = function() {
					button.innerHTML = play_character;
					container.style.display = "none";
				};
				button.innerHTML = '■';
				container.style.display = "block";
				audio.play();
			}
		};
		function lower_pitch(audio_id) {
			
		};
	''')

def _js_play_random():
	return raw('''
		var random_audio = new Audio();
		var random_playlist = [];
		var random_playlist_index = 0;

		random_audio.onended = function() {
			random_playlist_index += 1; // increment for next iteration
			if (random_playlist_index >= random_playlist.length) {
				random_playlist_index = 0;
			}
			random_audio.src = random_playlist[random_playlist_index]; // TODO: validate url/path!!! (against attack)
			setTimeout(() => random_audio.play(), 1500); // TODO: use user-specified timeout between prompt and answer! (also, this should give plenty of time for HAVE_ENOUGH_DATA readyState, so we won't listen for that as we did before starting the prompt, above
		};

		function stop_random_play() {
			random_audio.pause(); // we only pause, until you request_new_random_url_playlist()
		};
		function toggle_random_play(button) {
			if (random_audio.paused) {
				button.innerHTML = '■ Random';
				random_audio.play();
			} else {
				button.innerHTML = '► Random';
				random_audio.pause();
			}
		};

		function set_random_url_playlist(playlist) { // callback (from server)
			random_audio.pause();
			random_playlist = playlist;
			random_playlist_index = 0;
			random_audio.src = random_playlist[random_playlist_index]; // TODO: validate url/path!!! (against attack)
			random_audio.load(); // reset to start
		};
		function request_new_random_url_playlist() {
			ws_send({task: "get_random_url_playlist"});
		};
		
	''')

def _js_arithmetic():
	return raw('''
		var id = 0;
		var next_id = 0;
		var problem = "";
		var next_problem = "";
		var answer = 0;
		var next_answer = 0;
		var next_ready = true; // prime this, artificially, for first time through
		var initialized = false;
		var session_count = 0;
		var session_correct = 0;
		var running_sizzle = 0;
		var start_time;
		var timer_paused = true;
		var problem_start_time;
		var interval;

		function answer_key_down(event) {
			if (event.key == 'Enter' && !($('go_button').disabled)) {
				go();
			} else if (event.key == 'Backspace') {
				$('answer').innerHTML = $('answer').innerHTML.slice(0, -1);
			} else if (event.key >= '0' && event.key <= '9' && !($('go_button').disabled)) {
				$('answer').innerHTML = $('answer').innerHTML + (event.key - '0').toString();
			}
		};

		function update_arithmetic(payload) {
			next_id = payload['assessment_id'];
			next_problem = payload['op1'] + ' ' + payload['operator'] + ' ' + payload['op2'] + ' =';
			next_answer = payload['answer'];
			if (initialized) {
				next_ready = true;
			} else {
				advance(); // next_ready already primed to 'true' for first time through
				clear();
				$('problem').innerHTML = problem;
				initialized = true;
				next_ready = false;
				interval = setInterval(update_timer, 500);
				start_time = Date.now();
			}
		};

		function arithmetic_totals(payload) {
			$('stat_all_time').innerHTML = ms_to_time(payload['total_time']);
			$('stat_all_count').innerHTML = payload['total_count'];
			$('stat_all_accuracy').innerHTML = payload['total_accuracy'] + '%';
			$('stat_all_sizzle_score').innerHTML = Math.floor(payload['sazzle']);
			// the following should already be done, but just in case....
			$('all_stats_content').style.display = 'block';
			$('calcs').style.display = 'none';
		};

		function show_hide_stats() {
			if ($('show_hide_stats_button').innerHTML == "Show ▼") {
				$('show_hide_stats_button').innerHTML = "Hide ▲";
				$('stats_content').style.display = 'block';
			} else {
				$('show_hide_stats_button').innerHTML = "Show ▼";
				$('stats_content').style.display = 'none';
			}
		};

		function ms_to_time(milliseconds) {
			var ms = milliseconds % 1000;
			var s = (milliseconds - ms) / 1000;
			var secs = s % 60;
			s = (s - secs) / 60;
			var mins = s % 60;
			var hrs = (s - mins) / 60;

			function pad(n) {
				return ('00' + n).slice(-2);
			};
			return hrs + ':' + pad(mins) + ':' + pad(secs);
		}

		function update_timer() {
			if (!timer_paused) {
				var now = Date.now();
				$('stat_session_time').innerHTML = ms_to_time(now - start_time);
			}
		};

		function add_ninepin(button) {
			$('answer').innerHTML = $('answer').innerHTML + button.value;
			$('answer').focus();
		};

		function advance() {
			// must wait for next_ready to be true; async/await and js callbacks do not seem well suited to do this conveniently on an ongoing basis,
			// and 99% of the time, by the time advance() gets called, next_ready will, indeed, be true already, so... just going for the poor ole' timeout-check method
			if (next_ready == false) {
				window.setTimeout(advance, 200); // check again in 200ms
			} else {
				id = next_id;
				problem = next_problem;
				answer = next_answer;
				next_ready = false; // stays false until update_arithmetic next called, which will happen as soon as the send_message() is received by server and the server responds
			}
		};

		function clear() {
			$('problem').innerHTML = "";
			$('answer').focus();
			$('answer').innerHTML = "";
			$('answer').style.textDecoration = "none";
			$('answer').style.fontWeight = "normal";
			$('correct_answer').innerHTML = "";
			$('go_button').disabled = false;
			problem_start_time = Date.now();
		};

		function backspace() {
			$('answer').innerHTML = $('answer').innerHTML.slice(0, -1);
		};

		function go() {
			// timer started out paused; setting timer_paused=false here will normally be a no-op, but on occasion, if it's paused, this will start it.
			timer_paused = false;

			// disable input until we get the next problem shown:
			$('go_button').disabled = true;
			//TODO: all 9-pin buttons, too?
			//var ninepin_buttons = document.getElementsByClassName('ninepin_button');
			//for (var i = 0, ii = myElements.length; i < ii; i++) {
 			//	ninepin_buttons[i].disabled = true;
			//};

			// update counts and times:
			session_count += 1;
			$('stat_session_count').innerHTML = session_count;
			problem_end_time = Date.now();
			const max_time_ms = 7000; // consider 7-second delays "outliers" - student walked away or something; top its speed_ms at max_time_ms in this case
			var speed_ms = problem_end_time - problem_start_time;
			if (speed_ms > max_time_ms) {
				speed_ms = max_time_ms;
			}
			var correct = (answer == parseInt($('answer').innerHTML, 10))
			if (correct) {
				session_correct += 1;
			}
			var accuracy = Math.floor(100 * session_correct / session_count);
			$('stat_session_accuracy').innerHTML = accuracy.toString() + "%";
			if (correct) {
				running_sizzle += (accuracy * 10 / speed_ms);
				$('stat_session_sizzle_score').innerHTML = Math.floor(running_sizzle);
				// start the advance; load new problem:
				advance(); // Note: this should be done BEFORE the ws_send(), below, to make it impossible for a subsequent update_arithmetic() to preceed this call to advance()
				$('answer').style.fontWeight = "bold";
			} else { // if !correct, we never call advance(), so never advance to 'next' problem; so, user is re-presented with current problem, to try again
				$('correct_answer').innerHTML = answer;
				$('answer').style.textDecoration = "line-through";
			}

			// now send the message (which might very shortly result in an update_arithmetic which will overwrite next_problem, next_answer, and next_id
			var message = {task: "arithmetic_answer", assessment_id: id, speed_ms: speed_ms, correct: correct}
			ws_send(message);

			// pause, longer or shorter depending on whether 'correct':
			var pause = correct ? 200 : 1500;
			setTimeout(() => {
					clear(); // finally, clear the space and paint the next problem:
					$('problem').innerHTML = problem;
				}, pause);
		};

		function done() {
			// the following should already be done, but just in case....
			$('calcs').style.display = 'none';
			$('all_stats_content').style.display = 'block';

			$('stat_all_time').innerHTML = "Calculating...";
			$('stat_all_count').innerHTML = "Calculating...";
			$('stat_all_accuracy').innerHTML = "Calculating...";
			$('stat_all_sizzle_score').innerHTML = "Calculating...";

			timer_paused = true;
			ws_send({task: "arithmetic_totals"});
		};

		function reset() {
			$('all_stats_content').style.display = 'none';
			$('calcs').style.display = 'block';
			session_count = 0;
			session_correct = 0;
			running_sizzle = 0;
			initialized = false;
			clear();
			timer_paused = false;
			ws_send({task: "arithmetic_start"});
		};

		function stop_random_play() {
			// bogus - just a filler b/c choose_dropdown_option calls this (we hijacked it from resources()
		};

		function rest_of_go_MOVING() {
			which = Math.floor(Math.random() * audio_count);
			if (data.answer == answer.value) {
				ws.send('{"message": "result", "result": "correct", "delay": "0"}');
				audio_yeses[which].play();
				if (counter > 0)
					update_counter(--counter);
			}
			else {
				/* Here we need to FIRST show the correct answer for fail_delay amount of time, THEN
				send the result over the cet, along with the delay (for the server, which is
				responsible for timing, to subtract off.  If we just send our result message on the
				socket and then sleep, the server will push the next problem to us immediately, but
				will unknowingly be timing this fail_delay correct-answer-display time and counting it
				against the user's next answer time. */
				correct_answer.innerHTML = data.answer;
				audio_nos[which].play(); // this appears to be a non-blocking call, so even if it's very long, the user will still see the next problem and his answer will be timed accurately
				setTimeout(finish_correct_answer_flash, fail_delay); // only clear the flash and send the correct answer to the server after fail_delay!
			}
		};


	''')

def _js_practice():
	return raw('''
		function show_arithmetic(payload) {
			$("main_content").innerHTML = payload.content;
			initialized = false;
		}
	''')

def _js_mark_assignment():
	return raw('''
		function mark_assignment(assignment_id, checkbox) {
			ws_send({task: "mark_assignment", assignment_id: assignment_id, checked: (checkbox.checked == true)});
		};
	''')

__author__ = 'J. Michael Caine'
__copyright__ = '2020'
__version__ = '0.1'
__license__ = 'MIT'

import functools
import logging
l = logging.getLogger(__name__)

from dominate import document
from dominate import tags as t
from dominate.util import raw

from . import valid
from . import settings

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

	def invalid(self, name):
		# returns True if `name` is in the list of invalids set (in __init__)
		return name in self.invalids

# Handlers --------------------------------------------------------------------

def home():
	d = _doc('OHS-Test Home Page')
	with d:
		t.p('This is the stub home-page for ohs-test.')
	return d.render()

def login(action, error = None):
	d = _doc('OHS-Test Login')
	with d:
		with t.form(action = action, method = 'post'):
			with t.fieldset(cls = 'small_fieldset'):
				t.legend('Log in...')
				_error(error)
				t.div(_text_input('username', None, ('required', 'autofocus'), {'pattern': valid.re_username}, invalid_div = _invalid(valid.inv_username, False)), cls = 'field')
				t.div(_text_input('password', None, ('required',), type_ = 'password'), cls = 'field')
				t.div(t.input_(type = "submit", value = "Log in!"), cls = 'field')
		t.script(_js_util())
		t.script(_js_validate_login_fields())
	return d.render()

	
def new_user_success(id): # TODO: this is just a lame placeholder
	d = _doc('New User!')
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
	dollars = amount_cents / 100
	cents = amount_cents % 100
	if cents == 0:
		return t.b('$%d' % dollars) # keep it simple - no need to show ".00"
	#else:
	return t.b('$%d.%d' % (dollars, cents))

def _format_cost(cost):
	return ('%s: ' % cost['name'], _format_money(cost['amount']))

def invitation(form, invitation, person, family, contact, costs, leader, payments, errors = None):
	#TODO: this is ugly long!  dice it up!!
	
	cl = lambda content: t.div(content, cls = 'contact_line')
	cli = lambda content: t.div(content, cls = 'contact_line_inset')
	
	d = _doc('Invitation')
	with d:
		if not errors: # if there are errors, then we are re-presentingt his page; no need to say hello again
			t.p('Hello %s %s!  Please confirm that all of the following is correct...' % (person['first_name'], person['last_name']))
			
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
					program = None
					for child in family.children:
						if child['program_name'] != program:
							program = child['program_name']
							cl(t.b('%s (%s)' % (program, child['program_schedule'])))
						cli(_format_person(child))
		
		leadership_offset = 0
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
								leadership_offset += offset
			
			
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
				if leadership_offset:
					with t.div(cls = 'resource_record'):
						cl('Offsets:')
						cli(_format_money(leadership_offset))
						t.hr()
				with t.div(cls = 'resource_record'):
					cl('Balance Due:')
					cli(_format_money(total - total_payments - leadership_offset))

		t.p('If you see any mistakes, please just contact me directly.  Thanks!')
		
	return d.render()

def new_user(form, ws_url, errors = None):
	title = 'New User'
	d = _doc(title)
	with d:
		with t.form(action = form.action, method = 'post'):
			with t.fieldset():
				t.legend(title)
				_errors(errors)
				with t.ol(cls = 'step_numbers'):
					with t.li():
						t.p('First, create a one-word username for yourself (lowercase, no spaces)...')
						_text_input(*form.nv('new_username'), ('required', 'autofocus'), {'pattern': valid.re_username, 'oninput': 'check_username(this.value)'}, 'Type new username here',
							_invalid(valid.inv_username, form.invalid('new_username')))
						_invalid(valid.inv_username_exists, False, 'username_exists_message')
					with t.li():
						t.p("Next, invent a password; type it in twice to make sure you've got it...")
						_text_input('password', None, ('required',), {'pattern': valid.re_password}, 'Type new password here',
							_invalid(valid.inv_password, form.invalid('password')), type_ = 'password')
						_text_input('password_confirmation', None, ('required',), None, 'Type password again for confirmation',
							_invalid(valid.inv_password_confirmation, form.invalid('password_confirmation'), 'password_match_message'), type_ = 'password')
					with t.li():
						t.p("Finally, type in an email address that can be used if you ever need a password reset (optional, but this may be very useful someday!)...")
						_text_input(*form.nv('email'), None, {'pattern': valid.re_email}, 'Type email address here', 
							_invalid(valid.inv_email, form.invalid('email')))
				t.input_(type = "submit", value = "Done!")
		t.script(_js_util())
		t.script(_js_validate_new_user_fields())
		t.script(_js_check_username(ws_url))
	return d.render()

def select_user(url):
	d = _doc('Select User')
	with d:
		_text_input('search', None, ('autofocus',), {'autocomplete': 'off', 'oninput': 'search(this.value)'}, 'Search', type_ = 'search')
		t.div(id = 'content') # filtered results themselves are added here, in this `content` div, via websocket, as search text is typed (see javascript)
		# JS (intentionally at bottom of file; see https://faqs.skillcrush.com/article/176-where-should-js-script-tags-be-linked-in-html-documents and many stackexchange answers):
		t.script(_js_util())
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


def quiz(ws_url, db_handler, html_function):
	d = _doc('Quiz')
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
		t.script(_js_util())
		t.script(_js_socket_quiz_manager(ws_url, db_handler, html_function))
		t.script(_js_dropdown())
	return d.render()








def grades_filter_button(key, options):
	return _dropdown((key, options), {}, 'ib-left').render()


def resources(ws_url, filters, cycles, weeks, qargs, links): # TODO: this is basically identical to select_user (and presumably other search-driven pages whose content comes via websocket); consolidate!
	d = _doc('Resources')
	for_print = int(qargs.get('for_print', 0)) # 1 = no buttons, no header
	with d:
		if not for_print:
			with t.div(cls = 'flex-wrap'): # TODO: make a 'header_block' or something; different border color, perhaps
				t.div(t.b('Go'), cls = 'title') # TODO: replace with a magnifying-glass gif!
				with t.div(cls = 'main'):
					for name, url in links:
						t.button(name, title = name, onclick = f'window.open("{url}", "_self");')
					

			with t.div(cls = 'flex-wrap'): # TODO: make a 'header_block' or something; different border color, perhaps
				t.div(t.b('Search'), cls = 'title') # TODO: replace with a magnifying-glass gif!
				with t.div(cls = 'main'):
					for key, options in filters:
						with t.div(id = '%s-container' % key):
							_dropdown((key, options), qargs, 'ib-left')
					_dropdown(weeks[0], qargs, 'ib-right', button_class = 'cw-button')
					t.div(cls = 'clear') # next row...
					t.div(_text_input('search', None, ('autofocus',), {'autocomplete': 'off', 'oninput': 'search(this.value)'}, 'Search', type_ = 'search'), cls = 'search')
					_dropdown(weeks[1], qargs, 'ib-right', button_class = 'cw-button')
					_dropdown(cycles, qargs, 'ib-right', button_class = 'cw-button')

		t.div(id = 'content') # filtered results themselves are added here, in this `result` div, via websocket, as search text is typed (see javascript)

		# JS (intentionally at bottom of file; see https://faqs.skillcrush.com/article/176-where-should-js-script-tags-be-linked-in-html-documents and many stackexchange answers):
		t.script(_js_util())
		t.script(_js_filter_list(ws_url))
		t.script(_js_dropdown())
		t.script(_js_calendar_widget())
		t.script(_js_show_hide_shopping())
		t.script(_js_play_pause())
	return d.render()


def test_twixt(url):
	d = _doc('Test TWIXT Page')
	with d:
		t.p('This is the "TWIXT" Test page... result of main.foobar() coming soon...')
		t.div(id = 'foobar')
		
		t.script(_js_util())
		t.script(_js_test1(url))
		
	return d.render()



g_subject_resource_handlers = dict()
def subject_resources(handler):
	def decorator(func):
		g_subject_resource_handlers[handler] = func
		return func
	return decorator


def _grammar_resources(container, spec, records, show_cw, subject_directory, render, audio_widgets, record_container_class = None):
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

				if audio_widgets and not spec.for_print:
					filename_base = subject_directory + '/c%sw%s' % (record['cycle'], record['week'])
					with buttonstrip:
						t.audio(t.source(src = _aurl(filename_base + '.mp3?v=13'), type = 'audio/mpeg'), controls = True, id = filename_base, style = 'display:none;') # invisible
						t.button('►', title = 'Audio song', onclick = 'play_pause("%s", this);' % filename_base)
						t.button('♬', title = 'Musical score', onclick = 'window.open("%s","_blank");' % _aurl(filename_base + '.pdf'))
						#t.button(t.img(src = _iurl('eighth-note.png')), title = 'Musical score', onclick = 'window.open("%s","_blank");' % _aurl(filename_base + '.pdf'))
						t.button('ℓ', title = 'Copywork')
						#t.button(t.img(src = _iurl('cursive-c.png')), title = 'Copywork')
						t.button('Ξ', title = 'Details')

				_add_cw(record, buttonstrip, spec)
				resource_div += buttonstrip
				if record_container_class:
					record_container = record_container_class()
					resource_div += record_container
				else:
					record_container = resource_div

			render(record, record_container)


# TODO: DEPRECATE - we no longer use this... only _assignments is used now, even for shopping
def _external_resources(container, spec, records, show_cw):
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


def show_shopping(records):
	result = t.div()
	if not records:
		result += 'Sorry, there are no shopping links for this resource at present... try back again soon?'
	else:
		with result:
			resource_note = records[0]['resource_note'] # records[0] because they're all the same; all shopping link records provided reference this same resource
			if resource_note:
				t.div('Note: %s' % resource_note)
			t.div('Click to shop...')
			for record in records:
				title = '%s (%s)' % (record['source_name'], record['type_name'])
				if record['note']:
					title += ' -- ' + record['note']
				t.div(t.a(t.img(src = _lurl(record['source_logo'])), title, href = record['url'], target = '_blank'), cls = 'shopping_link')

	return result.render()

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

@subject_resources('science_grammar')
def science_grammar(container, spec, records, show_cw):
	def render(record, container): # callback function, see _grammar_resources()
		with container:
			t.div(t.b('What %s %s?' % (record['prompt_prefix'], record['prompt'])))
			answer_prompt = record['answer_prefix'].capitalize() + ' ' + record['prompt'] if record['answer_prefix'] else record['prompt'].capitalize()
			t.div('%s %s %s' % (answer_prompt, record['answer_verb'], record['answer']))

	_grammar_resources(container, spec, records, show_cw, 'science', render, True)

@subject_resources('science_resources')
def science_resources(container, spec, records, show_cw):
	_external_resources(container, spec, records, show_cw)

@subject_resources('english_vocabulary')
def english_vocabulary(container, spec, records, show_cw):
	def render(record, container): # callback function, see _grammar_resources()
		_add_eqality_record(container, record, 'word', 'definition')

	_grammar_resources(container, spec, records, show_cw, 'english', render, True, t.table)

def _add_eqality_record(table, record, left_field_name, right_field_name):
	table += t.tr(
		t.td(t.b(record[left_field_name]), cls = 'left-equality-cell'),
		t.td(' = ', record[right_field_name], cls = 'right-equality-cell')
	)

@subject_resources('english_grammar')
def english_grammar(container, spec, records, show_cw):
	def render(record, container): # callback function, see _grammar_resources()
		with container:
			t.div(t.b(record['prompt']))
			answer = record['answer']
			if record['example']:
				answer += ' (' + record['example'] + ')'
			t.div(answer)

	_grammar_resources(container, spec, records, show_cw, 'english', render, True)
	
@subject_resources('literature_resources')
def literature_resources(container, spec, records, show_cw):
	_external_resources(container, spec, records, show_cw)


@subject_resources('poetry_resources')
def poetry_resources(container, spec, records, show_cw):
	_external_resources(container, spec, records, show_cw)

@subject_resources('math_resources')
def math_resources(container, spec, records, show_cw):
	_external_resources(container, spec, records, show_cw)


@subject_resources('latin_vocabulary')
def latin_vocabulary(container, spec, records, show_cw):
	def render(record, container): # callback function, see _grammar_resources()
		_add_eqality_record(container, record, 'word', 'translation')

	_grammar_resources(container, spec, records, show_cw, 'latin', render, True, t.table)

@subject_resources('latin_grammar')
def latin_grammar(container, spec, records, show_cw):
	def render(record, container): # callback function, see _grammar_resources()
		with container:
			t.div(t.b(record['name']))
			t.div(record['pattern'])
			if record['example']: # TODO: PUT this into "more details" drop?
				t.div('Example: %s - %s' % (record['example'], record['example_worked']))
				if record['example_translated']:
					t.div(' (' + record['example_translated'] + ')')

	_grammar_resources(container, spec, records, show_cw, 'latin', render, True)


@subject_resources('latin_resources')
def latin_resources(container, spec, records, show_cw):
	_external_resources(container, spec, records, show_cw)

@subject_resources('history_grammar')
def history_grammar(container, spec, records, show_cw):
	def render(record, container): # callback function, see _grammar_resources()
		with container:
			t.div(t.b('%s - tell me more' % record['name']))
			t.div(record['primary_sentence'])

	_grammar_resources(container, spec, records, show_cw, 'history', render, True)

@subject_resources('history_resources')
def history_resources(container, spec, records, show_cw):
	_external_resources(container, spec, records, show_cw)

@subject_resources('timeline')
def timeline(container, spec, records, show_cw):
	def render(record, container): # callback function, see _grammar_resources()
		container += t.div(_event_formatted(record))

	_grammar_resources(container, spec, records, show_cw, 'timeline', render, True)


@subject_resources('history_assignments')
def history_assignments(container, spec, records, show_cw):
	_assignments(container, spec, records, show_cw)

@subject_resources('poetry_assignments')
def poetry_assignments(container, spec, records, show_cw):
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

@subject_resources('science_assignments')
def science_assignments(container, spec, records, show_cw):
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
			cw = new_cw
			if hr:
				container += t.hr(cls = 'clear')
			hr = cw[1] >= spec.first_week # don't draw a line next time 'round if our current record's week number preceeds what we're spec'd to look at (this can happen for records that whose first_week is earlier than spec.first_week because the record's last_week may be well within spec's range).  For instance, in Literature, a prefix assignment item might apply to two weeks; if the user is looking at the latter, they want to see the prefix, but don't want a line separating it from the rest of the assignment, which would seem like a meaningless line
			_add_cw(record, container, spec)
			new_list = True
		if resource_name != new_resource_name:
			resource_name = new_resource_name
			div_id = '%s%s' % (valid.k_res_prefix, record['resource_id'])
			title = t.div(cls = 'resource_name')
			if spec.shop:
				title += t.input_(type = 'checkbox')
				if not record['required'] > 0:
					title += '[optional] '
			title += resource_name
			if not spec.for_print:
				title += t.button('...', onclick = 'show_hide_details("%s");' % div_id, cls = 'chaser'),
				title += t.button('$', onclick = 'show_hide_shopping("%s");' % div_id, cls = 'chaser'),
			container += title
			if not spec.for_print:
				container += t.div(cls = 'shopping_links', id = div_id) # contents filled in via websocket upon '$' click to show_hide_shopping()
			new_list = True

		if new_list and not spec.shop:
			new_list = False
			ul = t.ul(cls = 'bulletless')
			container += ul

		if not spec.shop:
			# Assignments:
			instruction = record['instruction']
			instruction = instruction.replace('{chapters}', str(record['chapters']))
			instruction = instruction.replace('{pages}', str(record['pages']))
			instruction = instruction.replace('{items}', str(record['items']))
			if record['optional']:
				instruction = '[optional] ' + instruction
			grade_first = record['grade_first']
			grade_last = record['grade_last']
			if not ((not grade_first and not grade_last) or (record['program_grade_first'] == grade_first and record['program_grade_last'] == grade_last)) and spec.grade == 0: # i.e., if this record does **not** apply to everybody AND the spec isn't set to show only one grade anyway, then...
				if grade_first != grade_last:
					instruction = f'[Grades {grade_first}-{grade_last}] ' + instruction
				else:
					instruction = f'[Grade {grade_first}] ' + instruction

			ul += t.li(t.input_(type = 'checkbox'), raw(instruction))



def _new_subject_section(container, subject_title):
	result = t.div(cls = 'main')
	container += t.div(t.div(subject_title, cls = 'title'), result, cls = 'flex-wrap')
	return result


def resource_list(spec, results, url, show_cw = True):
	# Cycle, Week, Subject, Content (subject-specific presentation, option of "more details"), "essential" resources (e.g., song audio)
	container = t.div(cls = 'resource_list')
	for result in results:
		subject_container = _new_subject_section(container, result.subject_title)
		first = True
		for subresult in result.subresults:
			if not first:
				subject_container += t.hr(cls = 'bighr')
			else:
				first = False
			g_subject_resource_handlers[subresult.handler](subject_container, spec, subresult.records, show_cw)
	return container.render()

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
_aurl = lambda url: settings.k_static_url + 'audio/' + url # audio
_iurl = lambda url: settings.k_static_url + 'images/' + url # images
_lurl = lambda url: settings.k_static_url + 'images/logos/' + url # logos


def _doc(title, css = None, scripts = None):
	d = document(title = title)
	with d.head:
		t.meta(name = 'viewport', content = 'width=device-width, initial-scale=1')
		t.link(href = settings.k_static_url + 'css/main.css?v=14', rel = 'stylesheet')
	return d

def _error(error):
	if error:
		d = t.div(cls = 'errors')
		d += t.div(error, cls = 'error')
		return d

def _errors(errors):
	if errors:
		d = t.div(cls = 'errors')
		with d:
			for error in errors:
				t.div(error, cls = 'error')
		return d

def _invalid(message, visible, id = None):
	return t.div(message, cls = 'invalid', style = 'display:block;' if visible else 'display:none;', id = id if id else '')

def _combine_attrs(attrs, bool_attrs):
	if attrs == None:
		attrs = {}
	if bool_attrs:
		attrs.update(_dress_bool_attrs(bool_attrs))
	return attrs

def _text_input(name, value, bool_attrs = None, attrs = None, label = None, invalid_div = None, type_ = 'text', internal_label = True):
	'''
	The 'name' string is expected to be a lowercase alphanumeric
	"variable name" without spaces.  Use underscores ('_') to
	separate words for a mult-word name.  `label` will be calculated as
	name.replace('_', ' ').title() unless `label` exists.
	Set `type_` to 'password' for a password input field.
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

def _url_dropdown(container, id, options, title = None):
	# TODO: new style has options[0] IS id! (i.e., we can get rid of the extra "id" arg, above
	if not title:
		title = options[0][1]
	with container:
		t.button(title, cls = 'dropdown-button', onclick = 'choose_dropdown_item(%s)' % id)
		with t.div(id = id, cls = 'dropdown-content'):
			for option_title, option in options:
				t.div(option_title, onclick = 'load_page("%s")' % option)

def _dropdown(filt, qargs, cls, urls = False, title = None, button_class = None):
	key, options = filt
	if not options:
		return t.div() # empty div means there's nothing there - no options from which user might choose
	
	start_option_id = qargs.get(key)

	content_id = key
	button_id = '%s-button' % key
	drop_content = t.div(id = content_id, cls = 'dropdown-content')
	with drop_content:
		for option_title, option_id in options:
			t.div(option_title, onclick = 'choose_dropdown_option("%s", "%s", "%s", "%s")' % (key, option_id, option_title, button_id))
			if start_option_id and int(start_option_id) == int(option_id):
				title = option_title # override title with selected option
	if not title:
		title = options[0][0]

	button_classes = 'dropdown-button'
	if button_class:
		button_classes += ' ' + button_class
	return t.div(
		t.button(title, cls = button_classes, id = button_id, onclick = 'choose_dropdown_item(%s)' % content_id),
		drop_content,
		cls = cls,
	)


def _add_cw(record, div, spec):
	# For now: not showing the "cycle" - it just takes up screen real estate
	'''
	cycle = record['cycle']
	if cycle == 4: # TODO: hardcode for id 4, "All Cycles"
		cycle = 'All'
	else:
		cycle = 'C-%s' % cycle
	'''
	with div:
		#temporarily, not showing cycle: t.div(cycle, cls = 'cw')
		week = record['week'] if record['week'] > spec.first_week else spec.first_week # that is, if the actual first week on record predates the first week that we're looking at, just show the first week we're looking at
		t.div('W-', week, cls = 'cw')

def _add_cw_spacer(div):
	with div:
		t.div('. ', cls = 'cw-spacer')

def _event_formatted(record):
	result = record['name']
	if not record['fake_start_date']:
		result += ' ('
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
	if record['subseq']: # "extra" event
		result = '[' + result + ']'
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

def _js_util():
	return raw('''

	function $(id) {
		return document.getElementById(id);
	};
		
	function ws_send(message) {
		if (!ws || ws.readyState == WebSocket.CLOSING || ws.readyState == WebSocket.CLOSED) {
			alert("Lost connection... going to reload page....");
			location.reload();
		} else {
			ws.send(message);
		}
	};
	
	function pingpong() {
		if (!ws) return;
		if (ws.readyState !== WebSocket.OPEN) return;
		ws.send(JSON.stringify({call: "ping"}));
	};
	setInterval(pingpong, 30000); // 30-second heartbeat; default timeouts (like nginx) are usually set to 60-seconds

	''')

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
		ws_send(JSON.stringify({call: "answer", db_handler: "%(db_handler)s", html_function: "%(html_function)s", answer_id: parseInt(answer_id, 10)}));
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

		check_element = $(check)
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
	
	
def _js_filter_list(url):
	# This js not served as a static file for two reasons: 1) it's tiny and single-purpose, and 2) its code is tightly connected to this server code; it's not a candidate for another team to maintain, in other words; it also relies on our URL (for the websocket), whereas true static files might be served by a reverse-proxy server from anywhere, and won't tend to contain any references to the wsgi urls

	# This is the websocket code for filtering, and a search() (filter) function, which is the "standard"
	r = raw('''
	var ws = new WebSocket("%(url)s");

	ws.onmessage = function(event) {
		var payload = JSON.parse(event.data);
		switch(payload.call) {
			case "show":
				$("content").innerHTML = payload.result;
				spec = JSON.parse(payload.spec);
				fw_button = $("first_week-button")
				if (fw_button) { // this basically means that we're printing only
					fw_button.innerHTML = "W-" + spec.first_week;
					$("last_week-button").innerHTML = "W-" + spec.last_week;
					if (payload.grades != null)
						$("grade-container").innerHTML = payload.grades
				}
				break;
			case "show_shopping":
				$(payload.div_id).innerHTML = payload.result
				break;
		}
	};

	// "search" is the standard filter:
	function search(str) {
		ws_send(JSON.stringify({call: "filter", filter: "search", data: str}));
	};
	''' % {'url': url})

	return r


def _js_check_username(url):
	# This js not served as a static file for two reasons: 1) it's tiny and single-purpose, and 2) its code is tightly connected to this server code; it's not a candidate for another team to maintain, in other words; it also relies on our URL (for the websocket), whereas true static files might be served by a reverse-proxy server from anywhere, and won't tend to contain any references to the wsgi urls
	return raw('''
	var ws = new WebSocket("%(url)s");
	ws.onmessage = function(event) {
		$("username_exists_message").style.display = ((event.data == 'exists') ? 'block' : 'none');
	};
	function check_username(username) {
		ws_send(JSON.stringify({call: "check", string: username}));
	};
	''' % {'url': url})

def _js_check_validity():
	return raw('''
	function validate(evt) {
		var e = evt.currentTarget;
		e.nextElementSibling.style.display = e.checkValidity() ? "none" : "block";
	};
	''')

def _js_validate_login_fields():
	return raw('''
	$('username').addEventListener('input', validate);
	''' + _js_check_validity())

def _js_validate_new_user_fields():
	return raw('''
	$('new_username').addEventListener('input', validate);
	$('email').addEventListener('blur', validate);
	$('password').addEventListener('blur', validate);
	$('password_confirmation').addEventListener('blur', validate_passwords);

	function validate_passwords(evt) {
		$('password_match_message').style.display = $('password_confirmation').value == "" || $('password').value == $('password_confirmation').value ? "none" : "block";
	};
	''' + _js_check_validity())


def _js_dropdown():
	return raw('''
	/* When the user clicks on the button,
	toggle between hiding and showing the dropdown content */
	function choose_dropdown_item(element) {
		element.classList.toggle("show");
	};

	function load_page(url) {
		this.document.location.href = url;
	};

	function choose_dropdown_option(key, option_id, option_title, button_id) {
		ws_send(JSON.stringify({call: "filter", filter: key, data: option_id}));
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
					ws_send(JSON.stringify({call: "show_shopping", resource_id: div_id}));
				}
			}
		};
	''')

def _js_play_pause():
	return raw('''
		function play_pause(audio_id, button) {
			var audio = $(audio_id);
			if (!audio.paused || audio.style.display === "block") {
				button.innerHTML = '►';
				audio.style.display = "none";
				audio.pause();
				audio.currentTime = 0;
			} else {
				audio.onended = function() {
					button.innerHTML = '►';
					audio.style.display = "none";
				};
				button.innerHTML = '■';
				audio.style.display = "block";
				audio.play();
			}
		};
	''')

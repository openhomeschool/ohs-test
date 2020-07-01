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

def invitation(form, invitation, person, family, contact, costs, payments, errors = None):
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
		
		with t.div(cls = 'flex-wrap'):
			t.div('Costs', cls = 'title')
			with t.div(cls = 'main'):
				total = 0
				total_payments = 0
				with t.div(cls = 'resource_record'):
					for cost in [c for c in costs if not c['per_student']]:
						cl(t.span(*_format_cost(cost)))
						total += cost['amount']
					for child in family.children:
						cl(t.span(t.b(child['first_name'] + ' ' + child['last_name']), ' (', child['program_name'], ')'))
						child_total = 0
						for cost in [c for c in costs if c['per_student'] and not c['program']]:
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
				with t.div(cls = 'resource_record'):
					cl('Balance Due:')
					cli(_format_money(total - total_payments))

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
		t.script(_js_validate_new_user_fields())
		t.script(_js_check_username(ws_url))
	return d.render()

def select_user(url):
	d = _doc('Select User')
	with d:
		_text_input('search', None, ('autofocus',), {'autocomplete': 'off', 'oninput': 'search(this.value)'}, 'Search', type_ = 'search')
		t.div(id = 'content') # filtered results themselves are added here, in this `content` div, via websocket, as search text is typed (see javascript)
		# JS (intentionally at bottom of file; see https://faqs.skillcrush.com/article/176-where-should-js-script-tags-be-linked-in-html-documents and many stackexchange answers):
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
			_dropdown(t.div(cls = 'dropdown'), 'weeks_dropdown', (
				('...', 'bogus'),
				('All Weeks', 'bogus')), True, 'Weeks...')
			_dropdown(t.div(cls = 'dropdown'), 'difficulty_dropdown', (
				('Easy', 'bogus'),
				('Medium', 'bogus'),
				('Difficult', 'bogus')), True, 'Difficulty...')

		# JS (intentionally at bottom of file; see https://faqs.skillcrush.com/article/176-where-should-js-script-tags-be-linked-in-html-documents and many stackexchange answers):
		t.script(_js_socket_quiz_manager(ws_url, db_handler, html_function))
		t.script(_js_dropdown())
	return d.render()











def resources(url, filters, cycles, weeks, qargs): # TODO: this is basically identical to select_user (and presumably other search-driven pages whose content comes via websocket); consolidate!
	d = _doc('Resources')
	with d:
		with t.div(cls = 'flex-wrap'): # TODO: make a 'header_block' or something; different border color, perhaps
			t.div(t.b('Search'), cls = 'title') # TODO: replace with a magnifying-glass gif!
			with t.div(cls = 'main'):
				for filt in filters:
					_dropdown(filt, qargs, 'ib-left')
				_dropdown(weeks[0], qargs, 'ib-right', button_class = 'cw-button')
				t.div(cls = 'clear') # next row...
				t.div(_text_input('search', None, ('autofocus',), {'autocomplete': 'off', 'oninput': 'search(this.value)'}, 'Search', type_ = 'search'), cls = 'search')
				_dropdown(weeks[1], qargs, 'ib-right', button_class = 'cw-button')
				_dropdown(cycles, qargs, 'ib-right', button_class = 'cw-button')


		t.div(id = 'content') # filtered results themselves are added here, in this `result` div, via websocket, as search text is typed (see javascript)

		# JS (intentionally at bottom of file; see https://faqs.skillcrush.com/article/176-where-should-js-script-tags-be-linked-in-html-documents and many stackexchange answers):
		t.script(_js_filter_list(url))
		t.script(_js_filters())
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
			
				if audio_widgets:
					filename_base = subject_directory + '/c%sw%s' % (record['cycle'], record['week'])
					with buttonstrip:
						t.audio(t.source(src = _aurl(filename_base + '.mp3'), type = 'audio/mpeg'), id = filename_base) # invisible
						t.button('>', title = 'Audio song', onclick = 'play_pause("%s", this);' % filename_base, ondblclick = 'restart_play("%s", this);' % filename_base)
						t.button(t.img(src = _iurl('eighth-note.png')), title = 'Musical score', onclick = 'window.open("%s","_blank");' % _aurl(filename_base + '.pdf'))
						t.button(t.img(src = _iurl('cursive-c.png')), title = 'Copywork')
						t.button('Ξ', title = 'Details')
						
				_add_cw(record, buttonstrip)
				resource_div += buttonstrip
				if record_container_class:
					record_container = record_container_class()
					resource_div += record_container
				else:
					record_container = resource_div

			render(record, record_container)


def _external_resources(container, spec, records, show_cw):
	first = True
	for record in records:
		if not first:
			container += t.hr()
		else:
			first = False
		bs = t.div(cls = 'buttonstrip')
		_add_cw(record, bs)
		container += bs

		resource_title = t.div(cls = 'resource_name')
		if record['optional']:
			resource_title += '[optional] '
		resource_title += t.b(record['resource_name'])
		container += resource_title
		
		if spec.shop:
			div_id = '%s%s' % (valid.k_res_prefix, record['resource_id'])
			bs += t.button('$', onclick = 'show_hide_shopping("%s");' % div_id)
			container += t.div(cls = 'shopping_links', id = div_id) # contents filled in via websocket upon '$' click to show_hide_shopping()
		else:
			pass # TODO: put the $ link under the "more..."
		
		#TODO: ADD "more..." button/link to unfold drop-content loaded via ws  (no, just make the main text itself clickable to drop down more!)


def show_shopping(records):
	result = t.div()
	if not records:
		result += 'Sorry, there are no shopping links for this record at present... try back again soon?'
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

@subject_resources('science_grammar')
def science_grammar(container, spec, records, show_cw):
	def render(record, container): # callback function, see _grammar_resources()
		with container:
			t.div(t.b(record['prompt']))
			t.div(record['answer'])

	_grammar_resources(container, spec, records, show_cw, 'science', render, True)

@subject_resources('science_resources')
def science_resources(container, spec, records, show_cw):
	_external_resources(container, spec, records, show_cw)

@subject_resources('english_vocabulary')
def english_vocabulary(container, spec, records, show_cw):
	def render(record, container): # callback function, see _grammar_resources()
		_add_eqality_record(container, record, 'word', 'definition')

	_grammar_resources(container, spec, records, show_cw, 'english', render, False, t.table)

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
				answer += '(' + record['example'] + ')'
			t.div(answer)

	_grammar_resources(container, spec, records, show_cw, 'english', render, True)
	
@subject_resources('literature_resources')
def literature_resources(container, spec, records, show_cw):
	_external_resources(container, spec, records, show_cw)


@subject_resources('poetry_resources')
def poetry_resources(container, spec, records, show_cw):
	_external_resources(container, spec, records, show_cw)


@subject_resources('latin_vocabulary')
def latin_vocabulary(container, spec, records, show_cw):
	def render(record, container): # callback function, see _grammar_resources()
		_add_eqality_record(container, record, 'word', 'translation')

	_grammar_resources(container, spec, records, show_cw, 'latin', render, False, t.table)

@subject_resources('latin_grammar')
def latin_grammar(container, spec, records, show_cw):
	def render(record, container): # callback function, see _grammar_resources()
		with container:
			t.div(t.b(record['name']))
			answer = record['pattern']
			if record['example']: # TODO: PUT this into "more details" drop?
				example = 'Example: %s - %s' % (record['example'], record['example_worked'])
				if record['example_translated']:
					example += '(' + record['example_translated'] + ')'
				t.div(example)

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

	_grammar_resources(container, spec, records, show_cw, 'timeline', render, False)


@subject_resources('literature_assignments')
def literature_assignments(container, spec, records, show_cw):
	_assignments(container, spec, records, show_cw)

@subject_resources('science_assignments')
def science_assignments(container, spec, records, show_cw):
	_assignments(container, spec, records, show_cw)

def _assignments(container, spec, records, show_cw):
	teased = {}
	cws = []
	grades = []
	for record in records:
		cw = record['cycle'], record['week']
		if not cw in teased:
			teased[cw] = {}
			cws.append(cw)
		if not record['order'] in teased[cw]:
			teased[cw][record['order']] = {}
		if not record['grade']:
			teased[cw][record['order']]['shared'] = record
		else:
			teased[cw][record['order']][record['grade']] = record
			if record['grade'] not in grades:
				grades.append(record['grade'])

	if not grades:
		grades = ['7-9', ] # TODO: hardcode; replace this with DB intel

	with container:
		first = True
		for cw in cws:
			add_cw = True
			for grade in grades:
				if not first:
					t.hr()
				else:
					first = False
				grade_line = t.div(t.b('Grade %s:' % grade))
				with t.ol():
					for order in sorted(teased[cw]):
						if grade in teased[cw][order]:
							record = teased[cw][order][grade]
						elif 'shared' in teased[cw][order]:
							record = teased[cw][order]['shared']
						else:
							continue
						if add_cw:
							_add_cw(record, grade_line)
							add_cw = False
						t.li(raw(record['instruction']))



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
		t.link(href = settings.k_static_url + 'css/main.css?v=2', rel = 'stylesheet')
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


def _add_cw(record, div):
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
		t.div('W-', record['week'], cls = 'cw')


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

def _js_socket_quiz_manager(url, db_handler, html_function):
	# This js not served as a static file for two reasons: 1) it's tiny and single-purpose, and 2) its code is tightly connected to this server code; it's not a candidate for another team to maintain, in other words; it also relies on our URL (for the websocket), whereas true static files might be served by a reverse-proxy server from anywhere, and won't tend to contain any references to the wsgi urls
	return raw('''
		
	var ws = new WebSocket("%(url)s");
	var check = 0;
	var go_button = document.getElementById("go");

	ws.onmessage = function(event) {
		var payload = JSON.parse(event.data);
		switch(payload.call) {
			case "start":
				send_answer(-1); // kick-start
				break;
			case "content":
				document.getElementById("content").innerHTML = payload.content;
				check = payload.check;
				go_button.disabled = false;
				break;
		}
	};
	function send_answer(answer_id) {
		ws.send(JSON.stringify({db_handler: "%(db_handler)s", html_function: "%(html_function)s", answer_id: parseInt(answer_id, 10)}));
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

		check_element = document.getElementById(check)
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
				document.getElementById("foobar").innerHTML = payload.data;
				break;
		}
	};
	''' % {'url': url})

	return r
	
	
def _js_filter_list(url):
	# This js not served as a static file for two reasons: 1) it's tiny and single-purpose, and 2) its code is tightly connected to this server code; it's not a candidate for another team to maintain, in other words; it also relies on our URL (for the websocket), whereas true static files might be served by a reverse-proxy server from anywhere, and won't tend to contain any references to the wsgi urls

	# This is the websocket code for filtering, and a search() (filter) function, which is the "standard"; other functions provided in _js_filters()
	r = raw('''
	var ws = new WebSocket("%(url)s");
	ws.onmessage = function(event) {
		var payload = JSON.parse(event.data);
		switch(payload.call) {
			case "show":
				document.getElementById("content").innerHTML = payload.result;
				spec = JSON.parse(payload.spec);
				document.getElementById("first_week-button").innerHTML = "W-" + spec.first_week;
				document.getElementById("last_week-button").innerHTML = "W-" + spec.last_week;
				break;
			case "show_shopping":
				document.getElementById(payload.div_id).innerHTML = payload['result']
				break;
		}
	};

	// "search" is the standard filter:
	function search(str) {
		ws.send(JSON.stringify({call: "filter", filter: "search", data: str}));
	};
	''' % {'url': url})

	return r


def _js_filters(): # TODO: deprecate?!  Nobody calls these.  Now it's the choose_dropdown_option that handles this (I think)
	return raw('''
	function filter_first_week(week) {
		ws.send(JSON.stringify({call: "filter", filter: "first_week", data: week}));
	};
	function filter_last_week(week) {
		ws.send(JSON.stringify({call: "filter", filter: "last_week", data: week}));
	};
	''')

def _js_check_username(url):
	# This js not served as a static file for two reasons: 1) it's tiny and single-purpose, and 2) its code is tightly connected to this server code; it's not a candidate for another team to maintain, in other words; it also relies on our URL (for the websocket), whereas true static files might be served by a reverse-proxy server from anywhere, and won't tend to contain any references to the wsgi urls
	return raw('''
	var ws = new WebSocket("%(url)s");
	ws.onmessage = function(event) {
		document.getElementById("username_exists_message").style.display = ((event.data == 'exists') ? 'block' : 'none');
	};
	function check_username(username) {
		ws.send(JSON.stringify({call: "check", string: username}));
	};
	''' % {'url': url})

def _js_check_validity():
	return '''
	function validate(evt) {
		var e = evt.currentTarget;
		e.nextElementSibling.style.display = e.checkValidity() ? "none" : "block";
	};
	'''

def _js_validate_login_fields():
	return raw('''
	function $(id) { return document.getElementById(id); };
	$('username').addEventListener('input', validate);
	''' + _js_check_validity())

def _js_validate_new_user_fields():
	return raw('''
	function $(id) { return document.getElementById(id); };
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
		ws.send(JSON.stringify({call: "filter", filter: key, data: option_id}));
		document.getElementById(button_id).innerHTML = option_title;
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
			var div = document.getElementById(div_id);
			if (div.style.display === "block") {
				div.style.display = "none";
			} else {
				div.style.display = "block";
				if (div.innerHTML == "") {
					ws.send(JSON.stringify({call: "show_shopping", resource_id: div_id}));
				}
			}
		};
	''')

def _js_play_pause():
	return raw('''
		function play_pause(audio_id, button) {
			var audio = document.getElementById(audio_id);
			if (audio.paused) {
				button.innerHTML = '||';
				return audio.play();
			} else {
				button.innerHTML = '>';
				return audio.pause();
			}
		};

		function restart_play(audio_id, button) {
			var audio = document.getElementById(audio_id);
			button.innerHTML = '||';
			audio.currentTime = 0;
			return audio.play();
		};
	''')

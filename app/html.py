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
		t.div(id = 'search_result') # filtered results themselves are added here, in this `result` div, via websocket, as search text is typed (see javascript)
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
			_dropdown(t.div(cls = 'dropdown'), 'choose_subject', (
				('Timeline (sequence)', _gurl(settings.k_history_sequence)),
				('Science grammar', _gurl(settings.k_science_grammar)),
				('English vocabulary', _gurl(settings.k_english_vocabulary)),
				('English grammar', _gurl(settings.k_english_grammar)),
				('Latin vocabulary', _gurl(settings.k_latin_vocabulary))), True, 'Subjects...')
			_dropdown(t.div(cls = 'dropdown'), 'cycle_dropdown', (
				('Cycle 1', 'bogus'),
				('Cycle 2', 'bogus'),
				('Cycle 3', 'bogus'),
				('All Cycles', 'bogus'),
				('My Cycle', 'bogus')), True, 'Cycles...')
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

def resources(url, filters, qargs): # TODO: this is basically identical to select_user (and presumably other search-driven pages whose content comes via websocket); consolidate!
	d = _doc('Resources')
	with d:
		with t.div(cls = 'flex-wrap'): # TODO: make a 'header_block' or something; different border color, perhaps
			t.div(t.b('Search'), cls = 'title') # TODO: replace with a magnifying-glass gif!
			with t.div(cls = 'main'):
				with t.table():
					with t.tr():
						for filt in filters:
							_dropdown2(t.td(cls = 'dropdown', colspan = 2), filt, qargs, False)
						#TODO:DEPRECATE: _dropdown(t.td(cls = 'dropdown', colspan = 2), 'choose_program', filters['program'], False, qargs.get('program'))
						_dropdown(t.td(cls = 'dropdown', colspan = 2), 'choose_subject', (
							('All Subjects', 'bogus'),
							('Timeline', 'bogus'),
							('History', 'bogus'), 
							('Geography', 'bogus'),
							('Math', 'bogus'),
							('Science', 'bogus'),
							('Latin', 'bogus'),
							('English', 'bogus'),
							('All', 'bogus')), False)
					with t.tr():
						t.td(_text_input('search', None, ('autofocus',), {'autocomplete': 'off', 'oninput': 'search(this.value)'}, 'Search', type_ = 'search'), style = 'width: 87%', colspan = 6)
						_dropdown(t.td(style = 'width:10%', cls = 'dropdown'), 'cycle_dropdown', (
							('Any Cycle', 'bogus'), ('Cycle 1', 'bogus'), ('Cycle 2', 'bogus'), ('Cycle 3', 'bogus')), False)
						with t.td(style = 'width:20%'):
							t.input(type = 'number', placeholder = 'first wk', id = 'first_week_selector', min='1', max='28', oninput = 'filter_first_week(this.value)')
							t.br()
							t.input(type = 'number', placeholder = 'last wk', id = 'last_week_selector', min='1', max='28', oninput = 'filter_last_week(this.value)')

		t.div(id = 'search_result') # filtered results themselves are added here, in this `result` div, via websocket, as search text is typed (see javascript)

		# JS (intentionally at bottom of file; see https://faqs.skillcrush.com/article/176-where-should-js-script-tags-be-linked-in-html-documents and many stackexchange answers):
		t.script(_js_filter_list(url, (('choose_program', qargs.get('program')),) ))
		t.script(_js_dropdown())
		t.script(_js_filter_weeks())
		t.script(_js_calendar_widget())
	return d.render()

subject_resources = dict()
def subject_resource(subject):
	def decorator(func):
		subject_resources[subject] = func
		return func
	return decorator

def _resources(container, records, show_cw, subject_title, subject_directory, add_record, audio_widgets):
	with container:
		with t.div(cls = 'flex-wrap'):
			t.div(subject_title, cls = 'title')
			cycle_week = None
			with t.div(cls = 'main'):
				for record in records:
					if cycle_week != (record['cycle'], record['week']):
						# For each new week encountered, add the cycle and week numbers on rhs...
						cycle_week = (record['cycle'], record['week'])
						resource_div = t.div(cls = 'resource_record')
						buttonstrip = t.div(cls = 'buttonstrip')
					
						if audio_widgets:
							filename_base = subject_directory + '/c%sw%s' % (record['cycle'], record['week'])
							with buttonstrip:
								t.audio(t.source(src = _aurl(filename_base + '.mp3'), type = 'audio/mpeg'), id = filename_base) # invisible
								t.button('>', onclick = 'getElementById("%s").play();' % filename_base),
								t.button('$', onclick = 'window.open("%s","_blank");' % _aurl(filename_base + '.pdf')),
								t.button('@', onclick = '')
								
						_add_cw(record, buttonstrip)
						resource_div += buttonstrip

					add_record(record, resource_div)
				

	
@subject_resource('science')
def science_resources(container, records, show_cw):
	def add_record(record, div): # callback function, see _resources()
		div += t.div(t.b(record['prompt']))
		div += t.div(record['answer'])

	_resources(container, records, show_cw, 'Science', 'science', add_record, True)


@subject_resource('english_vocabulary')
def english_vocabulary_resources(container, records, show_cw):
	def add_record(record, div): # callback function, see _resources()
		div += t.div(t.b(record['word']), ' = ', cls = 'pair')
		div += t.div(record['definition'])

	_resources(container, records, show_cw, 'English', 'english', add_record, False)


@subject_resource('latin_vocabulary')
def english_vocabulary_resources(container, records, show_cw):
	def add_record(record, div): # callback function, see _resources()
		div += t.div(t.b(record['word']), ' = ', cls = 'pair')
		div += t.div(record['translation'])

	_resources(container, records, show_cw, 'Latin', 'latin', add_record, False)

@subject_resource('history')
def history_resources(container, records, show_cw):
	def add_record(record, div): # callback function, see _resources()
		with div:
			t.div(t.b('%s - tell me more' % record['name']))
			t.div(record['primary_sentence'])

	_resources(container, records, show_cw, 'History', 'history', add_record, True)


@subject_resource('timeline')
def event_resources(container, records, show_cw):
	def add_record(record, div): # callback function, see _resources()
		div += t.div(_event_formatted(record))

	_resources(container, records, show_cw, 'Timeline', 'history', add_record, False)


@subject_resource('external_resources')
def external_resources(container, records, show_cw):
	if records:
			resource_block = None
			subject_name = None
			content = None
			resource_name = None
			resource_detail = None
			for record in records:
				if record['subject_name'] != subject_name:
					subject_name = record['subject_name']
					
					if resource_block:
						container += resource_block # add old one before creating new one
					resource_block = t.div(cls = 'flex-wrap')
					resource_block += t.div(record['subject_name'], cls = 'title')

					content = t.div(cls = 'main')
					resource_block += content # will be filled in below

				with content:
					if record['resource_name'] != resource_name:
						resource_name = record['resource_name']
						resource_title = t.div(cls = 'resource_name')
						if record['optional']:
							resource_title += '[optional] '
						resource_title += t.b(resource_name)
						if record['note']:
							resource_title += ' (%s)' % record['note']
						resource_detail = t.div(cls = 'resource_details')

				_add_shopping_links(resource_detail, record)

			#TODO: the next 3 lines duplicates 3 lines above; consolidate!
			if resource_block:
				resource_block += t.div(cls = 'clear') # force resource_block container to be tall enough for all content
				container += resource_block # add old one before creating new one
			

def _add_shopping_links(container, record):
	s = t.div(t.a(t.img(src = _lurl(record['resource_source_logo'])), href = record['url'], target = '_blank'), cls = 'shopping_links')
	if record['instance_note']:
		s += '(' + record['instance_note'] + ')'
		container += t.br()
		container += s
		container += t.br()
	else:
		container += s


def resource_list(results, url, show_cw = True):
	# Cycle, Week, Subject, Content (subject-specific presentation, option of "more details"), "essential" resources (e.g., song audio)
	container = t.div(cls = 'resource_list')
	for subject, records in results:
		subject_resources[subject](container, records, show_cw)
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
_lurl = lambda url: settings.k_static_url + 'images/logos/' + url # logos


def _doc(title, css = None, scripts = None):
	d = document(title = title)
	with d.head:
		t.meta(name = 'viewport', content = 'width=device-width, initial-scale=1')
		t.link(href = settings.k_static_url + 'css/main.css', rel = 'stylesheet')
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

def _dropdown(container, id, options, urls, title = None):
	# TODO: new style has options[0] IS id! (i.e., we can get rid of the extra "id" arg, above
	if not title:
		title = options[0][1]
	with container:
		t.button(title, cls = 'dropdown-button', onclick = 'choose_dropdown_item(%s)' % id)
		with t.div(id = id, cls = 'dropdown-content'):
			for option_title, option in options:
				t.div(option_title, onclick = 'choose_dropdown_option("%s", "%s", %s)' % (id, option, 'true' if urls else 'false'))

def _dropdown2(container, filt, qargs, urls, title = None):
	key, div_id, options = filt
	start_option_id = qargs.get(key)

	drop_contents = t.div(id = div_id, cls = 'dropdown-content')
	with drop_contents:
		for option_title, option_id in options:
			t.div(option_title, onclick = 'choose_dropdown_option("%s", "%s", %s)' % (div_id, option_id, 'true' if urls else 'false'))
			if start_option_id and int(start_option_id) == int(option_id):
				title = option_title # override title with selected option
	if not title:
		title = options[0][0]

	container += t.button(title, cls = 'dropdown-button', onclick = 'choose_dropdown_item(%s)' % div_id)
	container += drop_contents


def _add_cw(record, div):
	with div:
		t.div('C-', record['cycle'], cls = 'cw')
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


def _js_filter_list(url, selections = None):
	# This js not served as a static file for two reasons: 1) it's tiny and single-purpose, and 2) its code is tightly connected to this server code; it's not a candidate for another team to maintain, in other words; it also relies on our URL (for the websocket), whereas true static files might be served by a reverse-proxy server from anywhere, and won't tend to contain any references to the wsgi urls

	filter_call = ''
	if selections and selections[0][1]: # TODO - bogus... clean this up, enable multiple simultaneous filters
		filter_call = 'ws.send(JSON.stringify({call: "%s", option: "%s"}));' % (selections[0][0], selections[0][1])

	r = raw('''
	var ws = new WebSocket("%(url)s");
	ws.onmessage = function(event) {
		var payload = JSON.parse(event.data);
		switch(payload.call) {
			case "start":
				search("");
				%(filter_call)s
				break;
			case "content":
				document.getElementById("search_result").innerHTML = payload.content;
				break;
		}
	};
	function search(str) {
		ws.send(JSON.stringify({call: "search", string: str}));
	};
	''' % {'url': url, 'filter_call': filter_call})

	return r


def _js_filter_weeks():
	return raw('''
	function filter_first_week(week) {
		ws.send(JSON.stringify({call: "filter_week", string: week, which: 'first'}));
	};
	function filter_last_week(week) {
		ws.send(JSON.stringify({call: "filter_week", string: week, which: 'last'}));
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

	function choose_dropdown_option(call, option, url) {
		if (url == true) {
			this.document.location.href = option;
		}
		else {
			ws.send(JSON.stringify({call: call, option: option}));
		}
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

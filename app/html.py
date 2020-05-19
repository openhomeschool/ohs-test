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
			with t.div(cls = 'dropdown'):
				t.button('Subjects...', cls = 'dropdown-button', onclick = 'choose_subject()')
				with t.div(id = 'subject_dropdown', cls = 'dropdown-content'):
					t.a('Timeline (sequence)', href = settings.k_url_prefix + settings.k_history_sequence)
					t.a('Science grammar', href = settings.k_url_prefix + settings.k_science_grammar)
					t.a('English vocabulary', href = settings.k_url_prefix + settings.k_english_vocabulary)
					t.a('English grammar', href = settings.k_url_prefix + settings.k_english_grammar)
					t.a('Latin vocabulary', href = settings.k_url_prefix + settings.k_latin_vocabulary)

		# JS (intentionally at bottom of file; see https://faqs.skillcrush.com/article/176-where-should-js-script-tags-be-linked-in-html-documents and many stackexchange answers):
		t.script(_js_socket_quiz_manager(ws_url, db_handler, html_function))
		t.script(_js_dropdown())
	return d.render()


def resources(url): # TODO: this is basically identical to select_user (and presumably other search-driven pages whose content comes via websocket); consolidate!
	d = _doc('Resources')
	with d:
		_text_input('search', None, ('autofocus',), {'autocomplete': 'off', 'oninput': 'search(this.value)'}, 'Search', type_ = 'search')
		t.div(id = 'search_result') # filtered results themselves are added here, in this `result` div, via websocket, as search text is typed (see javascript)
		# JS (intentionally at bottom of file; see https://faqs.skillcrush.com/article/176-where-should-js-script-tags-be-linked-in-html-documents and many stackexchange answers):
		t.script(_js_filter_list(url))
	return d.render()

@subject_resource
def science_resources(table, records):
	with table:
		t.th(td('Science'))
		for record in records:
			t.tr(t.td(record['cw.week']), t.td(t.b('Science')), t.td(record['prompt'].title()), t.td(record['cw.cucle'])):
			t.tr(t.td(''), t.td(record['answer'], colspan = 3))
				

	
def resource_list(results, url): # TODO: GENERALIZE for other lists!
	with t.table():
		for db_table, records in results:
			# Cycle, Week, Subject, Content (subject-specific presentation, option of "more details"), "essential" resources (e.g., song audio)
			subject_resources(db_table, records)
			
			
			
		for result in results:
			with t.tr():
				t.td(t.a(result['username'], href = '%s/%d' % (url, result['id'])))
		if len(results) >= 9:
			t.tr(t.td('... (type in search bar to narrow list)'))
	return table.render()

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

def _js_filter_list(url):
	# This js not served as a static file for two reasons: 1) it's tiny and single-purpose, and 2) its code is tightly connected to this server code; it's not a candidate for another team to maintain, in other words; it also relies on our URL (for the websocket), whereas true static files might be served by a reverse-proxy server from anywhere, and won't tend to contain any references to the wsgi urls
	return raw('''
	var ws = new WebSocket("%(url)s");
	ws.onmessage = function(event) {
		var payload = JSON.parse(event.data);
		switch(payload.call) {
			case "start":
				search("");
				break;
			case "content":
				document.getElementById("search_result").innerHTML = payload.content;
				break;
		}
	};
	function search(str) {
		ws.send(JSON.stringify({call: "search", string: str}));
	};
	
	''' % {'url': url})

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
	function choose_subject() {
		document.getElementById("subject_dropdown").classList.toggle("show");
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

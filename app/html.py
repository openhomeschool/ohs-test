__author__ = 'J. Michael Caine'
__copyright__ = '2020'
__version__ = '0.1'
__license__ = 'MIT'

import logging
l = logging.getLogger(__name__)

from dominate import document
from dominate import tags as t
from dominate.util import raw

from . import valid

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
		t.p('This is the stub home-page for ohs-test')
	return d.render()
	
def new_user_success(): # TODO: this is just a lame placeholder
	d = _doc('New User!')
	with d:
		t.p('New user successfully created! ....')
	return d.render()

def new_user(form, errors = None):
	title = 'New User'
	d = _doc(title)
	with d:
		with t.form(action = form.action, method = 'post'):
			with t.fieldset():
				t.legend(title)
				with t.ol(cls = 'step_numbers'):
					with t.li():
						t.p('First, create a one-word username for yourself (lowercase, no spaces)...')
						_text_input(*form.nv('new_username'), ('required', 'autofocus'), {'pattern': valid.re_username}, 'Type new username here',
							_invalid(valid.inv_username, form.invalid('new_username')))
					with t.li():
						t.p("Next, invent a password; type it in twice to make sure you've got it...")
						_text_input('password', None, ('required',), {'pattern': valid.re_password}, 'Type new password here',
							_invalid(valid.inv_password, form.invalid('password')), type_ = 'password')
						_text_input('password_confirmation', None, ('required',), None, 'Type password again for confirmation',
							_invalid(valid.inv_password_confirmation, form.invalid('password_confirmation')), type_ = 'password')
					with t.li():
						t.p("Finally, type in an email address that can be used if you ever need a password reset (optional, but this may be very useful someday!)...")
						_text_input(*form.nv('email'), None, {'pattern': valid.re_email}, 'Type email address here', 
							_invalid(valid.inv_email, form.invalid('email')))
				t.input_(type = "submit", value = "Done!")
		t.script(_js_validate_new_user())
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


def quiz(ws_url, db_function, html_function):
	d = _doc('Quiz')
	with d:
		# Content container - filtered results themselves will be fed into here, via websocket (see _js_socket_quiz_manager):
		t.div(id = 'content')
		# JS (intentionally at bottom of file; see https://faqs.skillcrush.com/article/176-where-should-js-script-tags-be-linked-in-html-documents and many stackexchange answers):
		t.script(_js_socket_quiz_manager(ws_url, db_function, html_function))
	return d.render()


exposed = {}
def expose(func):
	exposed[func.__name__] = func
	def wrapper():
		func()

@expose
def multi_choice_question(question, options):
	d = t.div('Where does "%s" belong in this sequence of events?' % question['name'], cls = 'quiz_question_content')
	with d:
		with t.div(cls = 'quiz_question_option'):
			t.input(type = 'radio', id = 'first', name = 'answer', value = '0')
			t.label('First', fr = 'first')
		for record in options:
			#t.div('Option - %s' % record['name'] + '(%s)' % record['start'], cls = 'quiz_question_option')
			with t.div(cls = 'quiz_question_option'):
				t.input(type = 'radio', id = record['name'], name = 'answer', value = record['id'])
				t.label('After "%s"' % record['name'], fr = record['name'])
	return d.render()


# Utils -----------------------------------------------------------------------

#TODO: deport some of these?

_dress_bool_attrs = lambda attrs: dict([(f, True) for f in attrs])

_invalid = lambda message, visible: t.div(message, cls = 'invalid', style = 'display:%s;' % 'block' if visible else 'none')

def _doc(title, css = None, scripts = None):
	d = document(title = title)
	with d.head:
		t.meta(name = 'viewport', content = 'width=device-width, initial-scale=1')
		t.link(href = 'http://localhost:8001/static/css/main.css', rel = 'stylesheet') # TODO: deport!
	return d

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

def _js_socket_quiz_manager(url, db_function, html_function):
	# This js not served as a static file for two reasons: 1) it's tiny and single-purpose, and 2) its code is tightly connected to this server code; it's not a candidate for another team to maintain, in other words; it also relies on our URL (for the websocket), whereas true static files might be served by a reverse-proxy server from anywhere, and won't tend to contain any references to the wsgi urls
	return raw('''
	var ws = new WebSocket("%(url)s");
	ws.onmessage = function(event) {
		var payload = JSON.parse(event.data);
		switch(payload.call) {
			case "start":
				ws.send(JSON.stringify({db_function: "%(db_function)s", html_function: "%(html_function)s", answer: 0}));
				break;
			case "content":
				document.getElementById("content").innerHTML = payload.content;
				break;
		}
	};
	function send_answer(answer) {
		ws.send(JSON.stringify({db_function: "%(db_function)s", html_function: "%(html_function)s", answer: answer}));
	};
	
	''' % {'url': url, 'db_function': db_function, 'html_function': html_function})

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

def _js_check_validity():
	return '''
	function validate(evt) {
		var e = evt.currentTarget;
		e.nextElementSibling.style.display = e.checkValidity() ? "none" : "block";
	}
	'''

def _js_validate_new_user():
	return raw('''
	function $(id) { return document.getElementById(id); }
	$('new_username').addEventListener('input', validate);
	$('email').addEventListener('blur', validate);
	$('password').addEventListener('blur', validate_passwords);
	$('password_confirmation').addEventListener('blur', validate_passwords);

	function validate_passwords(evt) {
		var e = evt.currentTarget; // "password_confirmation"
		$('password_match_message').style.display = $('password_confirmation').value == "" || $('password').value == $('password_confirmation').value ? "none" : "block";
	}
	''' + _js_check_validity())

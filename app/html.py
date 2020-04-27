__author__ = 'J. Michael Caine'
__copyright__ = '2020'
__version__ = '0.1'
__license__ = 'MIT'

import logging

from dominate import document
from dominate import tags as t
from dominate.util import raw

from . import valid

# Logging ---------------------------------------------------------------------

logging.basicConfig(format = '%(asctime)s - %(levelname)s : %(name)s:%(lineno)d -- %(message)s', level = logging.DEBUG) # TODO: parameterize DEBUG
l = logging.getLogger(__name__)


# Classes ---------------------------------------------------------------------

class Form:
	def __init__(self, action, values = None):
		self.action = action
		self.values = values
		
	def nv(self, name):
		return (name, self.values.get(name) if self.values else None)


# Handlers --------------------------------------------------------------------

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
_error = lambda message: t.div(message, cls = 'error')

def _doc(title, css = None, scripts = None):
	result = document(title = title)
	#TODO...
	return result

def _combine_attrs(attrs, bool_attrs):
	if attrs == None:
		attrs = {}
	if bool_attrs:
		attrs.update(_dress_bool_attrs(bool_attrs))
	return attrs

def _text_input(name, value, bool_attrs = None, attrs = None, label = None, error_message = None, type_ = 'text', internal_label = True):
	'''
	`name_value` is a 2-tuple (usually, *Form.nv('my-field-name') will be convenient)
	The 'name' string (first in the 2-tuple) is expected to be a
	lowercase alphanumeric "variable name" without spaces.  Use underscores ('_') to
	separate words for a mult-word name.  `label` will be calculated as
	name.replace('_', ' ').title() unless `label` exists.
	Set `type_` to 'password' for a password input field.
	'''
	if not label:
		label = name.replace('_', ' ').title()
	attrs = _combine_attrs(attrs, bool_attrs)
	
	i = t.input_(name = name, type = type_, **attrs)
	if value:
		i['value'] = value
	if internal_label:
		i['placeholder'] = label
		result = t.label(i)
	else:
		result = t.label(label + ':', i)
	if error_message:
		result += _error(error_message)
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

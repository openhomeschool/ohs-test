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

def test1_basic(record):
	d = _doc('Test 1')
	with d:
		with t.div(cls = 'test1_cls', id = 'test1_id'):
			t.p('This is a test paragraph; test record id: %s, "test" value: "%s"' % (record['id'], record['name']))
	return d.render()


def test1(form, title_prefix, button_title):
	title = title_prefix + ' Test 1'
	d = _doc(title)
	with d:
		with t.form(action = form.action, method = 'post'):
			with t.fieldset():
				t.legend(title)
				with t.div(cls = 'form_row'):
					_text_input(*form.nv('name'), ('autofocus', 'required'), {'pattern': valid.re_alphanum})
			with t.div(cls = 'form_row'):
				t.input(type = 'submit', value = button_title)
	return d.render()


def success():
	d = _doc('Success!')
	with d:
		t.p('It worked!')
	return d.render()


def select_test1(url):
	d = _doc('Select Test 1')

	with d:
		_text_input('search', None, ('autofocus',), {'autocomplete': 'off', 'oninput': 'search(this.value)'}, label = 'Search', type_ = 'search')
		t.div(id = 'result') # filtered results themselves are added here, in this `result` div, via websocket, as search text is typed (see javascript)
		
		# JS (intentionally at bottom of file; see https://faqs.skillcrush.com/article/176-where-should-js-script-tags-be-linked-in-html-documents and many stackexchange answers):
		t.script(_js_socket_filter(url))
	
	return d.render()


def list_test1(hits, url):
	table = t.table()
	with table:
		for hit in hits:
			with t.tr():
				t.td(t.a(hit['name'], href = '%s/%d' % (url, hit['id'])))
		if len(hits) >= 9:
			t.tr(t.td('... (type in search bar to narrow list)'))
	return table.render()


# Utils -----------------------------------------------------------------------

#TODO: deport some of these?

_dress_bool_attrs = lambda attrs: dict([(f, True) for f in attrs])
_error = lambda message: t.div(message, class_ = 'error')

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

def _js_socket_filter(url):
	# This js not served as a static file for two reasons: 1) it's tiny and single-purpose, and 2) its code is tightly connected to this server code; it's not a candidate for another team to maintain, in other words; it also relies on our URL (for the websocket), whereas true static files might be served by a reverse-proxy server from anywhere, and won't tend to contain any references to the wsgi urls
	return raw('''
	var ws = new WebSocket("%s");
	ws.onmessage = function(result) {
		document.getElementById("result").innerHTML = result.data;
	};
	function search(str) {
		ws.send(str);
	};
	''' % url)

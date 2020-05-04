__author__ = 'J. Michael Caine'
__copyright__ = '2020'
__version__ = '0.1'
__license__ = 'MIT'

import asyncio
import logging
import aiosqlite
import re
import weakref
import json

from aiohttp import web, WSMsgType, WSCloseCode

from . import html
from . import db
from . import valid

_debug = True # TODO: parameterize!

# Logging ---------------------------------------------------------------------

logging.basicConfig(format = '%(asctime)s - %(levelname)s : %(name)s:%(lineno)d -- %(message)s', level = logging.DEBUG if _debug else logging.INFO)
l = logging.getLogger(__name__)

# Utils -----------------------------------------------------------------------

r = web.RouteTableDef()
def hr(text): return web.Response(text = text, content_type = 'text/html')


# Handlers --------------------------------------------------------------------

@r.get('/')
async def home(request):
	return hr(html.home())

@r.view('/new_user')
class New_User(web.View):
	async def get(self):
		return hr(html.new_user(html.Form(self.request.path)))
	
	async def post(self):
		r = self.request
		data = await r.post()
		
		# Validate:
		invalids = []
		_validate_regex(data, invalids, (
				('new_username', valid.re_username),
				('password', valid.re_password),
				('email', valid.re_email),
			))
		if str(data['password']) != str(data['password_confirmation']):
			invalids.append('password_confirmation')

		if invalids:
			# Re-present:
			return hr(html.new_user(html.Form(self.request.path, data, invalids)))
		#else...

		# (Try to) add the user:
		try:
			user_id = await db.add_user(r.app['db'], data['new_username'], data['password'], data['email'])
		except: # TODO: Specify!!!
			# Re-present with errors:
			return hr(html.new_user(html.Form(self.request.path, data), errors))

		#if sess.get('trial'): # True
		#user = db.update_user(dbs, sess['username'], p.username, p.password, p.email)
		#else:
		
		return hr(html.new_user_success()) # lame placeholder


@r.get('/select_user')
async def select_user(request):
	return hr(html.select_user(_ws_url(request, '/ws_filter_list')))

@r.get('/ws_filter_list')
async def ws_filter_list(request):
	# Create a default list to show when nothing is entered into search bar:
	default_list = await db.get_users_limited(request.app['db'], 10)
	edit_url = _http_url(request, 'edit_user')
	
	async def msg_handler(payload, dbc, ws):
		assert(payload['call'] == 'search')
		if payload['string']:
			#TODO: validate first!
			records = await db.find_users(dbc, payload['string'])
		else:
			records = default_list
		await ws.send_json({'call': 'content', 'content': html.filter_user_list(records, edit_url)})

	return await _ws_handler(request, msg_handler)

	

@r.get('/ws_quiz_handler')
async def ws_quiz_handler(request):

	async def msg_handler(payload, dbc, ws):
		if payload['answer']:
			pass # TODO
		question, options = await db.get_question(db.exposed[payload['db_function']], dbc, payload)
		await ws.send_json({'call': 'content', 'content': html.exposed[payload['html_function']](question, options)})

	return await _ws_handler(request, msg_handler)


# Util ------------------------------------------------------------------------

def _ws_url(request, name):
	# Transform a normal URL like http://domain.tld/quiz/history/sequence into ws://domain.tld/<name>
	return re.sub('%s$' % request.rel_url, name, re.sub('.*://', 'ws://', str(request.url)))

def _http_url(request, name):
	# Transform a ws URL like ws://domain.tld/... into a normal URL: http://domain.tld/<name>  - note: what about HTTPs!?TODO
	return re.sub('%s$' % request.rel_url, name, re.sub('.*://', 'http://', str(request.url)))

def _validate_regex(data, invalids, tuple_list):
	for field, regex in tuple_list:
		if not regex.match(str(data[field])):
			invalids.append(field)

async def _ws_handler(request, msg_handler):
	ws = web.WebSocketResponse()
	await ws.prepare(request)
	request.app['websockets'].add(ws)
	dbc = request.app['db']

	await ws.send_json({'call': 'start'})
	l.debug('Websocket prepared, listening for messages...')
	try:
		async for msg in ws:
			try:
				if msg.type == WSMsgType.text:
					#TODO: Validate each msg in ws as search string (use Schema(valid_search_string())?
					payload = json.loads(msg.data)
					l.debug(payload)
					await msg_handler(payload, dbc, ws)
				elif msg.type == aiohttp.WSMsgType.ERROR:
					l.warning('websocket connection closed with exception "%s"' % ws.exception())
				else:
					l.warning('websocket message of unexpected type "%s" received' % msg.type)

			except Exception as e: # per-message exceptions:
				l.error('Exception (%s: %s) during WS message processing; continuing on...' % (str(e), type(e)))
				raise

	except Exception as e:
		l.error('Exception (%s: %s) processing WS messages; shutting down WS...' % (str(e), type(e)))
		raise

	finally:
		request.app['websockets'].discard(ws) # in finally block to ensure that this is done even if an exception propagates out of this function

	return ws


# Init / Shutdown -------------------------------------------------------------

async def init_db(app):
	db = await aiosqlite.connect('ohs-test.db', isolation_level = None) # isolation_level: autocommit TODO: parameterize DB ID!
		# non-async equivalent would have been: db = sqlite3.connect('test1.db', isolation_level = None) # isolation_level: autocommit
	db.row_factory = aiosqlite.Row
	await db.execute('pragma journal_mode = wal') # see https://charlesleifer.com/blog/going-fast-with-sqlite-and-python/ - since we're using async/await from a wsgi stack, this is appropriate
	#await db.execute('pragma case_sensitive_like = true')
	#await db.set_trace_callback(l.debug) - not needed with aiosqlite, anyway
	app['db'] = db
	l.debug('Database initialized')

async def shutdown(app):
	await app['db'].close()
	for ws in set(app['websockets']):
		await ws.close(code = WSCloseCode.GOING_AWAY, message = 'Server shutdown')
	l.debug('Shutdown complete')

# Run server like so, from cli:
#		python -m aiohttp.web -H localhost -P 8080 main:init
# Or, using adev (from parent directory!):
#		adev runserver --app-factory init --livereload --debug-toolbar test1_app
def init(argv):
	app = web.Application()
	app.update(
		websockets = weakref.WeakSet(),
		static_path = 'static/',
		static_url = '/static/',
		static_root_url = 'static/',
	)
	
	# Add standard routes:
	app.add_routes(r)
	# And quiz routes:
	def q(db_function, html_function):
		def quiz(request):
			return hr(html.quiz(_ws_url(request, '/ws_quiz_handler'), db_function, html_function))
		return quiz
	g = web.get
	app.add_routes([
		g('/quiz/history/sequence', q('get_history_sequence_question', 'multi_choice_question')),
		g('/quiz/history/geography', q('get_history_geography_question', 'multi_choice_question')),
		g('/quiz/history/detail', q('get_history_detail_question', 'multi_choice_question')),
		g('/quiz/history/submissions', q('get_history_submissions_question', 'multi_choice_question')),
		g('/quiz/history/random', q('get_history_random_question', 'multi_choice_question')),
		g('/quiz/geography/orientation', q('get_geography_orientation_question', 'multi_choice_question')),
		g('/quiz/geography/map', q('get_geography_map_question', 'multi_choice_question')),
		g('/quiz/science/grammar', q('get_science_grammar_question', 'multi_choice_question')),
		g('/quiz/science/submissions', q('get_science_submissions_question', 'multi_choice_question')),
		g('/quiz/science/random', q('get_science_random_question', 'multi_choice_question')),
		g('/quiz/math/facts/multiplication', q('get_math_facts_question', 'multi_choice_question')),
		g('/quiz/math/grammar', q('get_math_grammar_question', 'multi_choice_question')),
		g('/quiz/english/grammar', q('get_english_grammar_question', 'multi_choice_question')),
		g('/quiz/english/vocabulary', q('get_quiz_english_vocabulary_question', 'multi_choice_question')),
		g('/quiz/english/random', q('get_english_random_question', 'multi_choice_question')),
		g('/quiz/latin/grammar', q('get_latin_grammar_question', 'multi_choice_question')),
		g('/quiz/latin/vocabulary', q('get_latin_vocabulary_question', 'multi_choice_question')),
		g('/quiz/latin/translation', q('get_latin_translation_question', 'multi_choice_question')),
		g('/quiz/latin/random', q('get_latin_random_question', 'multi_choice_question')),
		g('/quiz/music/note', q('get_music_note_question', 'multi_choice_question')),
		g('/quiz/music/key_signature', q('get_music_key_signature_question', 'multi_choice_question')),
		g('/quiz/music/submissions', q('get_music_submissions_question', 'multi_choice_question')),
		g('/quiz/music/random', q('get_music_random_question', 'multi_choice_question')),
	])
	
	# Add startup/shutdown hooks:
	app.on_startup.append(init_db)
	app.on_shutdown.append(shutdown)

	return app


def app():
	return init(None)


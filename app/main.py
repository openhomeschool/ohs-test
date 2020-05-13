__author__ = 'J. Michael Caine'
__copyright__ = '2020'
__version__ = '0.1'
__license__ = 'MIT'

import aiosqlite
import asyncio
import functools
import logging
import re
import weakref
import json

# TODO: These three may be culled once user/session stuff is complete
import time
import base64
from cryptography import fernet

from aiohttp import web, WSMsgType, WSCloseCode
from sqlite3 import IntegrityError
from aiohttp_session import setup as setup_session, get_session
from aiohttp_session.cookie_storage import EncryptedCookieStorage

from . import html
from . import db
from . import cdb
from . import valid
from . import error

_debug = True # TODO: parameterize!

# Logging ---------------------------------------------------------------------

logging.basicConfig(format = '%(asctime)s - %(levelname)s : %(name)s:%(lineno)d -- %(message)s', level = logging.DEBUG if _debug else logging.INFO)
l = logging.getLogger(__name__)

# Utils -----------------------------------------------------------------------

r = web.RouteTableDef()
def hr(text): return web.Response(text = text, content_type = 'text/html')

def auth(roles):
	'''
	Checks `roles` against user's roles, if user is logged in.
	Sends user to login page if necessary.
	`roles` may be a string, signifying a singleton role needed to access this handler,
	or a list/tuple/set of roles that would suffice.  E.g., 
		auth('user')
		async def handler(request):
			...
	or:
		auth(('contributor', 'admin'))
		async def handler2(request):
			...
	'''
	def decorator(func):
		@functools.wraps(func)
		async def wrapper(request): # no need for *args, **kwargs b/c this decorator is for aiohttp handler functions only, which must accept a Request instance as its only argument
			session = await get_session(request)
			arg_roles = roles
			if isinstance(roles, str): # then wrap the singleton:
				arg_roles = {roles,}
			if 'roles' in session and set(session['roles']).intersection(arg_roles):
				# Process the request (handler) as requested:
				return await func(request)
			#else, forward to log-in page:
			session['after_login'] = request.path
			if 'roles' in session: # user is logged in, but the above role-intersection test failed, meaning that user is not permitted to access this particular page
				session['error_flash'] = error.not_permitted
			raise web.HTTPFound(location = request.app.router['login'].url_for())
		return wrapper
	return decorator


# Handlers --------------------------------------------------------------------

@r.get('/login', name = 'login')
async def login(request):
	session = await get_session(request)
	if 'user_id' in session:
		del session['user_id']
	if 'roles' in session:
		del session['roles']
	return hr(html.login(await _flash(request)))

@r.post('/login')
async def login_(request):
	r = request
	data = await r.post()
	session = await get_session(r)
	try:
		#TODO: validate data!
		user_id, roles = await db.authenticate(r.app['db'], data['username'], data['password'])
		if not user_id:
			return hr(html.login(error.authentication_failure))
		else:
			session['user_id'] = user_id
			session['roles'] = roles
			# raise web.HTTPFound below, after blanket exception handler...
	except:
		return hr(html.login(error.unknown_login_failure))
	if 'user_id' in session:
		raise web.HTTPFound(location = session['after_login'] if 'after_login' in session else r.app.router['home'].url_for())

		

@r.get('/', name = 'home')
async def home(request):
	return hr(html.home())

@r.view('/new_user')
class New_User(web.View):
	async def get(self):
		return hr(html.new_user(html.Form(self.request.path), _ws_url(self.request, '/ws_check_username')))
	
	async def post(self):
		r = self.request
		data = await r.post()
		ws_url = _ws_url(r, '/ws_check_username')
		
		# Validate:
		invalids = []
		_validate_regex(data, invalids, (
				('new_username', valid.rec_username, True),
				('password', valid.rec_password, True),
				('email', valid.rec_email, False),
			))
		if str(data['password']) != str(data['password_confirmation']):
			invalids.append('password_confirmation')

		if invalids:
			# Re-present:
			return hr(html.new_user(html.Form(r.path, data, invalids), ws_url))
		#else, go on...

		# (Try to) add the user:
		user_id = None
		try:
			user_id = await db.add_user(r.app['db'], data['new_username'], data['password'], data['email'])
		except IntegrityError: # Note that this should **almost** never happen, as we check username availability in real-time, but it's always possible that another new user with the same username is created milliseconds before the db.add_user() attempt, above; this would make the username suddenly unavailable; we could not possibly have told the user about this in advance, and need to revert to posting an error message now:
			# Re-present with user_exists error:
			return hr(html.new_user(html.Form(r.path, data), ws_url, (error.user_exists,)))

		#if sess.get('trial'): # TODO!
		#user = db.update_user(dbs, sess['username'], p.username, p.password, p.email)
		#else:
		
		return hr(html.new_user_success(user_id)) # TODO: lame placeholder - need to redirect, anyway!

@r.get('/ws_check_username')
async def ws_check_username(request):
	async def msg_handler(payload, dbc, ws):
		assert(payload['call'] == 'check')
		if payload['string']:
			value = str(payload['string'])
			if valid.rec_username.match(value):
				records = await db.get_user(dbc, (('username', payload['string']),))
				await ws.send_str('exists' if records else 'available!')
			else:
				l.warning('username fragment sent to ws_check_username was not a valid string') # but do nothing else; client code already checks for validity; this must/might be an attack attempt; no need to respond

	return await _ws_handler(request, msg_handler)
	

@r.get('/select_user')
@auth('admin')
async def select_user(request):
	return hr(html.select_user(_ws_url(request, '/ws_filter_list')))


@r.get('/ws_filter_list')
async def ws_filter_list(request):
	edit_url = _http_url(request, 'edit_user')
	
	async def msg_handler(payload, dbc, ws):
		assert(payload['call'] == 'search')
		records = None
		if payload['string']:
			string = str(payload['string'])
			if valid.rec_string32.match(string):
				records = await db.find_users(dbc, string)
			else:
				l.warning('string fragment sent to ws_filter_list was not a valid string 32-characters or less') # but do nothing else; client code already checks for validity; this must/might be an attack attempt; no need to respond
		if not records:
			records = await db.get_users_limited(request.app['db'], 10) # A default list (of 10) to show when nothing is entered into search bar:
		await ws.send_json({'call': 'content', 'content': html.filter_user_list(records, edit_url)})

	return await _ws_handler(request, msg_handler)


@r.get('/ws_quiz_handler')
async def ws_quiz_handler(request):
	async def msg_handler(payload, dbc, ws):
		if payload['answer']:
			pass # TODO
		question, options = await db.get_question(db.exposed[payload['db_function']], dbc, payload)
		await ws.send_json({'call': 'content', 'check': question['id'], 'content': html.exposed[payload['html_function']](question, options)})

	return await _ws_handler(request, msg_handler)


# Util ------------------------------------------------------------------------

async def _flash(request):
	session = await get_session(request)
	flash = session.get('error_flash')
	session['error_flash'] = None
	return flash

def _ws_url(request, name):
	# Transform a normal URL like http://domain.tld/quiz/history/sequence into ws://domain.tld/<name>
	return re.sub('%s$' % request.rel_url, name, re.sub('.*://', 'ws://', str(request.url)))

def _http_url(request, name):
	# Transform a ws URL like ws://domain.tld/... into a normal URL: http://domain.tld/<name>  - note: what about HTTPs!?TODO
	return re.sub('%s$' % request.rel_url, name, re.sub('.*://', 'http://', str(request.url)))

def _validate_regex(data, invalids, tuple_list):
	for field, regex, required in tuple_list:
		value = str(data[field])
		if (required and not value) or (value and not regex.match(value)):
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
					payload = json.loads(msg.data) # Note: payload validated in msg_handler()
					#l.debug(payload)
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
	l.debug('Initializing database...')
	db = await aiosqlite.connect('ohs-test.db', isolation_level = None) # isolation_level: autocommit TODO: parameterize DB ID!
		# non-async equivalent would have been: db = sqlite3.connect('test1.db', isolation_level = None) # isolation_level: autocommit
	db.row_factory = aiosqlite.Row
	await db.execute('pragma journal_mode = wal') # see https://charlesleifer.com/blog/going-fast-with-sqlite-and-python/ - since we're using async/await from a wsgi stack, this is appropriate
	#await db.execute('pragma case_sensitive_like = true')
	#await db.set_trace_callback(l.debug) - not needed with aiosqlite, anyway
	app['db'] = db
	l.debug('...database initialized')

async def shutdown(app):
	l.debug('Shutting down...')
	await app['db'].close()
	for ws in set(app['websockets']):
		await ws.close(code = WSCloseCode.GOING_AWAY, message = 'Server shutdown')
	l.debug('...shutdown complete')

# Run server like so, from cli:
#		python -m aiohttp.web -H localhost -P 8080 main:init
# Or, using adev (from parent directory!):
#		adev runserver --app-factory init --livereload --debug-toolbar test1_app
def init(argv):
	app = web.Application()
	app.update(websockets = weakref.WeakSet())

	# Set up sessions:
	fernet_key = fernet.Fernet.generate_key()
	secret_key = base64.urlsafe_b64decode(fernet_key)
	setup_session(app, EncryptedCookieStorage(secret_key))

	# Add standard routes:
	app.add_routes(r)
	# And quiz routes:
	def q(db_function, html_function):
		#@auth('student') -- TODO: comment this back in when it's time to auth students who are looking to quiz
		async def quiz(request):
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
		g('/quiz/science/grammar', q('get_science_grammar_question', 'multi_choice_science_question')),
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


__author__ = 'J. Michael Caine'
__copyright__ = '2020'
__version__ = '0.1'
__license__ = 'MIT'

import aiosqlite
import asyncio
import functools
import json
import logging
import re
import weakref

from os.path import exists
from random import shuffle

from sqlite3 import PARSE_DECLTYPES
from dataclasses import dataclass

# TODO: These three may be culled once user/session stuff is complete
import time
import base64
from cryptography import fernet
from uuid import uuid4

from aiohttp import web, WSMsgType, WSCloseCode
from aiohttp_session import setup as setup_session, get_session

from aiohttp_session.cookie_storage import EncryptedCookieStorage
# Tried both of the following; running a redis server or memcached server, they basically work; not sure I want the dependencies right now
#from aiohttp_session.redis_storage import RedisStorage
#import aioredis
#from aiohttp_session import memcached_storage
#fmport aiomcache

from sqlite3 import IntegrityError
from yarl import URL

from . import html
from . import db
from . import valid
from . import error
from . import settings
from . import util

_debug = True # TODO: parameterize!

# Logging ---------------------------------------------------------------------

logging.basicConfig(format = '%(asctime)s - %(levelname)s : %(name)s:%(lineno)d -- %(message)s', level = logging.DEBUG if _debug else logging.INFO)
l = logging.getLogger(__name__)

# Utils -----------------------------------------------------------------------

#_prefix_url_path = lambda url: URL.build(scheme = url.scheme, host = url.host, path = settings.k_url_prefix + url.path, port = url.port, query = url.query, query_string = url.query_string)
gurl = lambda request, name: settings.k_url_prefix + str(request.app.router[name].url_for())

r = web.RouteTableDef()
def hr(text): return web.Response(text = text, content_type = 'text/html')

# TEMP, DEBUG!!!!  (for running with:
#   python -m aiohttp.web -H 0.0.0.0 -P 8080 app.main:init
# "raw", and to get /static
#r.static('/static', '/home/jmcaine/dev/ohs/ohs-test/static')

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
			session['after_login'] = settings.k_url_prefix + request.path
			if 'roles' in session: # user is logged in, but the above role-intersection test failed, meaning that user is not permitted to access this particular page
				session['error_flash'] = error.not_permitted
			raise web.HTTPFound(location = gurl(request, 'login'))
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
	return hr(html.login(gurl(request, 'login'), await _flash(request)))

@r.post('/login')
async def login_(request):
	r = request
	login_url = gurl(r, 'login')
	data = await r.post()
	session = await get_session(r)
	try:
		# Validate:
		invalids = []
		_validate_regex(data, invalids, (
				('username', valid.rec_username, True),
				('password', valid.rec_password, True),
			))
		if invalids:
			raise Exception('login failure') # TODO: password retrieval mechanism

		user_id, roles = await db.authenticate(r.app['db'], data['username'], data['password'])
		if not user_id:
			return hr(html.login(login_url, error.authentication_failure))
		else:
			session['user_id'] = user_id
			session['roles'] = roles
			# raise web.HTTPFound below, after blanket exception handler...
	except:
		return hr(html.login(login_url, error.unknown_login_failure))
	if 'user_id' in session:
		raise web.HTTPFound(location = session['after_login'] if 'after_login' in session else gurl(r, 'home'))

		

@r.get('/stub-home', name = 'home')
async def home(request):
	return hr(html.home())

@r.view('/new_user')
class New_User(web.View):
	async def get(self):
		return hr(html.new_user(html.Form(settings.k_url_prefix + self.request.path), _ws_url(self.request, '/ws_check_username')))
	
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
			return hr(html.new_user(html.Form(settings.k_url_prefix + r.path, data, invalids), ws_url))
		#else, go on...

		# (Try to) add the user:
		user_id = None
		try:
			user_id = await db.add_user(r.app['db'], data['new_username'], data['password'], data['email'])
		except IntegrityError: # Note that this should **almost** never happen, as we check username availability in real-time, but it's always possible that another new user with the same username is created milliseconds before the db.add_user() attempt, above; this would make the username suddenly unavailable; we could not possibly have told the user about this in advance, and need to revert to posting an error message now:
			# Re-present with user_exists error:
			return hr(html.new_user(html.Form(settings.k_url_prefix + r.path, data), ws_url, (error.user_exists,)))

		#if sess.get('trial'): # TODO!
		#user = db.update_user(dbs, sess['username'], p.username, p.password, p.email)
		#else:
		
		return hr(html.new_user_success(user_id)) # TODO: lame placeholder - need to redirect, anyway!

@r.view('/invitation/{code}')
class Invitation(web.View):
	async def get(self):
		r = self.request
		code = r.match_info['code']
		if valid.rec_invitation.match(code):
			dbc = r.app['db']
			invitation = await db.get_new_user_invitation(dbc, code)
			person_id, academic_year = invitation['person'], invitation['academic_year']
			person = await db.get_person(dbc, person_id)
			family = await db.get_family(dbc, person_id, academic_year)
			contact = await db.get_person_contact_info(dbc, person_id)
			costs = await db.get_costs(dbc, academic_year)
			cost_offsets = await db.get_cost_offset(dbc, person_id, academic_year)
			leader = await db.get_leader(dbc, person_id, academic_year)
			payments = await db.get_payments(dbc, [g['id'] for g in family.guardians], academic_year)
			return hr(html.invitation(html.Form(settings.k_url_prefix + r.path), invitation, person, family, contact, costs, cost_offsets, leader, payments))
		else:
			return hr(html.invalid_invitation()) # this might be an attack attempt!
		
	
	async def post(self):
		r = self.request
		data = await r.post()
		

r.view('/invitation2/{code}')
async def invitation2(request):
	code = request.match_info['code']
	if valid.rec_invitation.match(code):
		dbc = r.app['db']
		invitation = await db.get_new_user_invitation(dbc, code)
		person_id = invitation['person']
		person = await db.get_person_user(dbc, person_id)

		return hr(html.invitation2())

	else:
		return hr(html.invalid_invitation()) # this might be an attack attempt!



@r.get('/ws_check_username')
async def ws_check_username(request):
	dbc = request.app['db']
	
	async def msg_handler(payload, ws):
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
	edit_url = _http_url(request, '/edit_user')
	dbc = request.app['db']
	
	async def msg_handler(payload, ws):
		assert(payload['call'] == 'search')
		records = None
		if payload['string']:
			string = str(payload['string'])
			if valid.rec_string32.match(string):
				records = await db.find_users(dbc, string)
			else:
				l.warning('string fragment sent to ws_filter_list was not a valid string 32-characters or less') # but do nothing else; client code already checks for validity; this must/might be an attack attempt; no need to respond
		if not records:
			records = await db.get_users_limited(dbc, 10) # A default list (of 10) to show when nothing is entered into search bar:
		await ws.send_json({'call': 'show', 'result': html.filter_user_list(records, edit_url)})

	return await _ws_handler(request, msg_handler)

@r.get('/ws_quiz_handler')
async def ws_quiz_handler(request):
	'''
	Generic "glue" code that manages question/answer mechanics between websocket/client and database/server.
	Specific types of questions are handled quite differently, so the actual DB handler functions are in
	payload['db_answer_function'] and etc., and the HTML-creation code is in payload['html_function'], and
	the payload content may be different, but will be what the particular handler function expects.
	'''
	r = request
	session = await get_session(r)
	dbc = r.app['db']
	db_handler = None # new one will be created each transaction

	async def msg_handler(payload, ws):
		nonlocal db_handler
		if db_handler and payload['call'] == 'answer':
			if payload['answer_id'] >= 0: # -1 indicates "skip"... for now we just allow this and log nothing... TODO: evaluate!
				db_handler.log_user_answer(payload['answer_id'])
		if 'db_handler' in payload: # assume that 'html_function' is there, too
			db_handler = await db.get_handler(payload['db_handler'], dbc, session.get('user_id', None)) # TODO: add args; e.g., history might utilize date_range....
			await ws.send_json({
				'call': 'content',
				'content': html.exposed[payload['html_function']](db_handler.question, db_handler.options),
				'check': db_handler.answer_id})
		else:
			l.warning('Unexpected payload for ws_quiz_handler - no db_handler field!')

	return await _ws_handler(request, msg_handler)

async def foobar():
    await asyncio.sleep(2)  # 2-second sleep
    return 'thats great'

# Can't store coroutines in sessions, directly; not even redis or memcached directories, so we store them in global memory, in this dict:
g_twixt_work = {}

@r.get('/test_twixt')
async def test_twixt(request):
	session = await get_session(request)
	twixt_key = str(uuid4())
	session['twixt'] = twixt_key

	g_twixt_work[twixt_key] = asyncio.create_task(foobar())

	return hr(html.test_twixt(_ws_url(request, '/ws_test_twixt')))

@r.get('/ws_test_twixt')
async def ws_test_twixt(request):
	session = await get_session(request)
	result = await g_twixt_work[session['twixt']]
	
	async def msg_handler(payload, ws):
		await ws.send_json({'call': 'content', 'data': await foobar()})

	return await _ws_handler(request, msg_handler, {'call': 'content', 'data': result})
	
# Container for session-specific "random-play" playlists:
g_playlists = {}


@r.get('/')
async def default(request):
	return await _resources(request, {})

@r.get('/resources')
async def resources(request):
	return await _resources(request, request.query)

@r.get('/shop3')
async def shop_year_program3(request):
	return await _resources(request, {'shop': 1, 'cycle': 2, 'program': 3, 'first_week': 0, 'last_week': 28, 'grammar_supplement': 0})

@r.get('/shop4')
async def shop_year_program4(request):
	return await _resources(request, {'shop': 1, 'cycle': 2, 'program': 4, 'first_week': 0, 'last_week': 28, 'grammar_supplement': 0})



@r.get('/quiz/arithmetic')
async def quiz_arithmetic(request):
	pass #calculator!



g_detail_handlers = dict()
def detail_handler(handler):
	def decorator(func):
		g_detail_handlers[handler] = func
		return func
	return decorator

@r.get('/Q/{key}')
async def detail(request):
	dbc = request.app['db']
	detail = await db.get_detail(dbc, request.match_info['key'])
	if detail: # is a 4-tuple: {table, record, details, signs}
		table, record, details, signs = detail
		return await g_detail_handlers[table](record, details, signs)
	else:
		raise web.HTTPNotFound(location = gurl(r, 'home')) # TODO - replace with a pagetthat indicates failure to find the 'key'

@r.get('/detail/{table}/{id}')
async def event_detail(request):
	dbc = request.app['db']
	table = request.match_info['table']
	detail = await db.get_detail_by_id(dbc, table, request.match_info['id'])
	if detail: # is a 3-tuple: {record, details, signs (sign-language signs)}
		record, details, signs = detail
		return await g_detail_handlers[table](record, details, signs)
	else:
		raise web.HTTPNotFound(location = gurl(r, 'home')) # TODO - replace with a pagetthat indicates failure to find the 'key'


@detail_handler('event')
async def timeline_event_detail(record, details, signs):
	return hr(html.timeline_event_detail(record, details, signs))

@detail_handler('science')
async def science_detail(record, details, signs):
	return hr(html.science_detail(record, details, signs))

k_temp_this_week = 23
k_temp_this_cycle = 2

# cool characters: ⌂♩♪♫♬▲►▼◄→
_links = lambda request: (
	#('Grammar', _http_url(request, '/resources', {'program': 1}), True),
	('⌂', _http_url(request, '/resources', {}), True),
	('→', _http_url(request, '/resources', {'week': k_temp_this_week + 1}), True),
	('4-Review', _http_url(request, '/resources', {'program': 1, 'first_week': max(0, k_temp_this_week - 4), 'last_week': k_temp_this_week}), True),
	('All-Review', _http_url(request, '/resources', {'program': 1, 'first_week': 1, 'last_week': k_temp_this_week}), True),
	('► Random', 'toggle_random_play(this)', False),
	#('4-6 assignments': _http_url(request, '/resources?program=2'),
	#('7th-9th', _http_url(request, '/resources', {'program': 3}), True),
	#('10th-12th', _http_url(request, '/resources', {'program': 4}), True),
	#('Shop', _http_url(request, '/shop'), True),
	#('Quiz', _http_url(request, '/quiz/history/sequence'), True), # TODO!
)

async def _resources(request, qargs):
	session = await get_session(request)

	session['twixt'] = str(uuid4())
	dbc = request.app['db']
	g_twixt_work[session['twixt']] = asyncio.create_task(_first_resources(dbc, qargs)) # start the first lookup now... should be done by the time the page is loaded and websocket handshake occurs, when this result is passed on into the loaded skeletal page

	filters = (
		('program', [(program['name'], program['id']) for program in await db.get_programs(dbc)]),
		('grade', ()), # will be populated later
		('subject', [(subject['name'], subject['id']) for subject in await db.get_subjects(dbc)]),
	)
	cycles = ('cycle', [(cycle['name'], cycle['id']) for cycle in await db.get_cycles(dbc)])
	weeks = (
		('first_week', [('W-%d' % week, week) for week in range(0, 29)]), # TODO: hardcode 29!
		('last_week', [('W-%d' % week, week) for week in range(0, 29)]), # TODO: hardcode 29!
	)

	links = _links(request)
	return hr(html.resources(_ws_url(request, '/ws_resources'), filters, cycles, weeks, qargs, links))





k_db_handlers = { # 'id' keys must coincide with DB 'program' table
	1: db.get_grammar_resources,
	2: db.get_middle_resources,
	3: db.get_high1_resources,
	4: db.get_high1_resources, # TODO: placeholder
	5: db.get_grammar_resources, # TODO: placeholder
	6: db.get_grammar_resources, # TODO: placeholder
	7: db.get_grammar_resources, # TODO: placeholder
	8: db.get_high1_resources, # TODO: placeholder
	9: db.get_high1_resources, # TODO: placeholder
}

async def _first_resources(dbc, qargs):
	spec = util.Struct(
		#user_id = session['user_id'],
		search = qargs.get('search'),
		deep_search = False,
		program = int(qargs.get('program', 1)), # hardcode default to "grammar school" program if program choice not made (TODO: set this, instead, to logged-in-user's attached program
		grade = int(qargs.get('grade', 0)), # 0 = "unspecified" or "all"; common, when a program is treated all the same, and there's no need to differentiate grade
		solo = int(qargs.get('solo', 0)), # 0 = show the designed content for the program; 1 = show *only* the content unique to the program -- TODO: DEPRECATED? I think 'grammar_supplement' now takes care of this, and can't find references to solo elsewhere.....
		shop = int(qargs.get('shop', 0)), # 1 = show shopping links
		subject = qargs.get('subject', 0), # 0 = "all" indicator
		cycles = (4, int(qargs.get('cycle', k_temp_this_cycle))), # default: k_temp_this_cycle ("4" refers to grammar that belongs to "all cycles" (like timeline grammar) - this is hardcode! TODO:FIX!)
		first_week = int(qargs.get('first_week', k_temp_this_week)), # TODO: hardcode default to week 0! replace with lookup for user's "current week"
		last_week = int(qargs.get('last_week', k_temp_this_week)), # TODO: see above; look up user's current-week
		week = qargs.get('week', None), # convenience - use this to specify first_week = last_week = week
		grammar_supplement = int(qargs.get('grammar_supplement', 0)), # 1 = show grammar (at the bottom of assignments)
		for_print = int(qargs.get('for_print', 0)), # 1 = no buttons, no header
		secondaries = int(qargs.get('secondaries', 0)), # 1 = include secondary history sentences, etc. ("advanced" material), 0 = don't
		timeline_sentences = int(qargs.get('timeline_sentences', 0)), # 1 = include timeline sentences, 0 = don't
		show_search = int(qargs.get('show_search', 1)), # 1 = show search bar, 0 = don't
		show_go = int(qargs.get('show_go', 1)), # 1 = show go bar, 0 = don't
		random_audio_type = int(qargs.get('random_audio_type', 7)), # 4 = 'song-simple'
	)
	if spec.week != None:
		spec.first_week = spec.last_week = int(spec.week)
	return (spec, await k_db_handlers[spec.program](dbc, spec)) # need to send spec, itself, as there's no other way for retrieving end (ws_resources function) to get spec hereafter!


k_call_map = {
	'search': (str, valid.rec_string32.match),
	'program': (int, None),
	'grade': (int, None),
	'subject': (int, None),
	'first_week': (int, None), # TODO: add validator to constrain to weeks 0-28?!
	'last_week': (int, None), # TODO: add validator to constrain to weeks 0-28?!
	'external_resource_detail': (int, None),
	'shop': (int, None),
}




@r.get('/ws_resources') #TODO: this has strong similarities to ws_filter_list (which should be named ws_filter_user_list)
async def ws_resources(request):
	session = await get_session(request)
	dbc = request.app['db']
	open_resource = _http_url(request, '/open_resource') #TODO?!?? (figure out how we want to advance a user's click on a specific resource); TODO: call this, simply, "more"?
	spec, result = await g_twixt_work[session['twixt']]
	_make_msg = lambda result, rspec, grades = None: {'call': 'show', 'result': html.resource_list(spec, result, open_resource), 'spec': json.dumps(rspec.asdict()), 'grades': grades}
	async def _grades(program_id):
		program = await db.get_program(dbc, program_id)
		grades = [] # cue to show no "grade" button at all.
		if program['differentiate']:
			grades = [('All', 0), ] # select to show all grades together (within program)
			grades.extend([('%sth' % grade, grade) for grade in range(program['grade_first'], program['grade_last'] + 1)])
		return html.grades_filter_button('grade', grades, program['show_grammar_option'])

	async def msg_handler(payload, ws):
		nonlocal spec
		try:
			if payload['call'] == 'filter':
				cast, validator = k_call_map[payload['filter']]
				value = cast(payload['data'])
				if validator and not validator(value):
					raise ValueError() # treat like failed cast, above; either way - invalid filter input was tried
				setattr(spec, payload['filter'], value) # note that payload calls must match field names in `spec`; but this is convention only
				result = await k_db_handlers[spec.program](dbc, spec)
				# Program changes require special treatment of the "grade" filter/button -- grab the grades that are appropriate for this (new) program selected:
				grades = None if payload['filter'] != 'program' else await _grades(value) # value is program_id in this case
				# reset any existing playlist; will have to be reconstructed if play_random is attempted again after this filter establishes a new set of grammar
				if 'playlist_id' in session:
					del session['playlist_id']
				# send the message:
				await ws.send_json(_make_msg(result, spec, grades))

			elif payload['call'] == 'show_shopping': # handles individual resource clicked to show the shopping options for that resource
				match = valid.rec_resource_id_div.match(payload['resource_id'])
				if not match:
					raise ValueError() # treat like a failed cast
				result = await db.get_shopping_links(dbc, match.group(1)) # group(1) is the actual id matched, after the prefix
				await ws.send_json({'call': 'show_shopping', 'div_id': payload['resource_id'], 'result': html.show_shopping(result)})

			elif payload['call'] == 'get_random_url_playlist':
				await ws.send_json({'call': 'set_random_url_playlist', 'playlist': _create_random_playlist(spec)})

		except ValueError as e:
			l.warning('invalid filter input to ws_resources') # but do nothing else; client code already checks for validity; this must/might be an attack attempt; no need to respond

	# First WS send wrapped up in return of handler...
	return await _ws_handler(request, msg_handler, _make_msg(result, spec, await _grades(spec.program)))


# Util ------------------------------------------------------------------------

def _create_random_playlist(spec):
	# Assemble the playlist (we build an entire playlist at once in order to avoid repetition (each song/etc. shows up only once), and because it's very easy to do one DB operation that results in a whole (randomly-ordered) set/list of "hits", rather than asking the DB every time, one song at a time):
	path_map = {
		db.k_subject_ids['History']: 'history/',
		db.k_subject_ids['Science']: 'science/',
	}
	new_path_map = {
		db.k_subject_ids['English']: 'english/',
		db.k_subject_ids['Latin']: 'latin/',
	}
	playlist = []
	for subject, path in path_map.items():
		if spec.subject in (0, subject): # i.e., spec.subject is either "all subjects" or this one
			url = html._aurl(path)
			for cycle in spec.cycles:
				for week in range(spec.first_week, spec.last_week + 1):
					fn = f'c{cycle}w{week}.mp3'
					p_fn = f'c{cycle}w{week}-prompt.mp3'
					if exists('static/audio/' + path + p_fn) and exists('static/audio/' + path + fn): # TODO: fix hardcode static path (local/server path... static files may be stored elsewhere in future!)
						playlist.append((url + p_fn, url + fn))
	shuffle(playlist)
	result = []
	for pair in playlist:
		result.extend(pair)
	return result

async def _flash(request):
	session = await get_session(request)
	flash = session.get('error_flash')
	session['error_flash'] = None
	return flash

def _ws_url(request, name):
	# Transform a normal URL like http://domain.tld/quiz/history/sequence into ws://domain.tld/<name>
	rurl = request.url
	return URL.build(scheme = settings.k_ws, host = request.host, path = settings.k_ws_url_prefix + name)

def _http_url(request, name, query = None):
	# Transform a ws URL like ws://domain.tld/... into a normal URL: http://domain.tld/<name>  - note: what about HTTPs!?TODO
	rurl = request.url
	return URL.build(scheme = settings.k_http, host = request.host, path = settings.k_url_prefix + name, query = query)

def _validate_regex(data, invalids, tuple_list):
	for field, regex, required in tuple_list:
		value = str(data[field])
		if (required and not value) or (value and not regex.match(value)):
			invalids.append(field)

async def _ws_handler(request, msg_handler, initial_send = {'call': 'start', 'data': None}):
	ws = web.WebSocketResponse()
	await ws.prepare(request)
	request.app['websockets'].add(ws)

	await ws.send_json(initial_send)

	l.debug('Websocket prepared, listening for messages...')
	try:
		async for msg in ws:
			try:
				if msg.type == WSMsgType.PING: # some browsers will actually send keepalive pings!
					 ws.pong() # respond
				elif msg.type == WSMsgType.PONG:
					pass # nothing to do, but it's nice if the client/browser actually sends PONGs!
				elif msg.type == WSMsgType.TEXT:
					payload = json.loads(msg.data) # Note: payload validated in msg_handler()
					if payload['call'] == 'ping':
						await ws.send_json({'call': 'pong'}) # would prefer to use WSMsgType.PING rather than a normal message, but javascript doesn't seem to have specified support for that! (see https://stackoverflow.com/questions/10585355/sending-websocket-ping-pong-frame-from-browser)
						await ws.ping() # because some browsers will respond to "real" pings from server, or, at *least*, some browsers will keep the connection open, upon receiving a ping, even if they don't properly PONG!
							# in an ideal world, we wouldn't have our own 'call' 'ping' or 'pong'; rather, we'd rely on ws.ping() or msg.type == WSMsgType.PING, to which we could respond with a PONG, but there's no evidence that many browsers do this
					else:
						await msg_handler(payload, ws)
				elif msg.type == WSMsgType.ERROR:
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

async def init_db(filename):
	db = await aiosqlite.connect(filename, isolation_level = None, detect_types = PARSE_DECLTYPES) # isolation_level: autocommit TODO: parameterize DB ID!
		# non-async equivalent would have been: db = sqlite3.connect('test1.db', isolation_level = None) # isolation_level: autocommit
	db.row_factory = aiosqlite.Row
	await db.execute('pragma journal_mode = wal') # see https://charlesleifer.com/blog/going-fast-with-sqlite-and-python/ - since we're using async/await from a wsgi stack, this is appropriate
	#await db.execute('pragma case_sensitive_like = true')
	#await db.set_trace_callback(l.debug) - not needed with aiosqlite, anyway
	return db

async def _init(app):
	l.debug('Initializing database...')
	app['db'] = await init_db('ohs-test.db')
	l.debug('...database initialized')
	
async def _shutdown(app):
	l.debug('Shutting down...')
	await app['db'].close()
	for ws in set(app['websockets']):
		await ws.close(code = WSCloseCode.GOING_AWAY, message = 'Server shutdown')
	l.debug('...shutdown complete')


	
# Run server like so, from cli:
#		python -m aiohttp.web -H localhost -P 8080 main:init
# Or, using adev (from parent directory!):
#		adev runserver --app-factory init --livereload --debug-toolbar test1_app
async def init(argv):
	app = web.Application()
	app.update(websockets = weakref.WeakSet())

	# Set up sessions:
	fernet_key = fernet.Fernet.generate_key()
	secret_key = base64.urlsafe_b64decode(fernet_key)
	setup_session(app, EncryptedCookieStorage(secret_key))
	# Tried both of the following; running a redis server or memcached server, they basically work; not sure I want the dependencies right now
	#redis = await aioredis.create_redis_pool('redis://localhost')
	#setup_session(app, RedisStorage(redis))
	#mc = aiomcache.Client('localhost', 11211)
	#setup_session(app, memcached_storage.MemcachedStorage(mc))


	# Add standard routes:
	app.add_routes(r)
	# And quiz routes:
	def q(db_handler, html_function):
		#@auth('student') # TODO: comment this back in when it's time to auth students who are looking to quiz
		async def quiz(request):
			return hr(html.quiz(_ws_url(request, '/ws_quiz_handler'), db_handler, html_function))
		return quiz
	g = web.get
	app.add_routes([
		g(settings.k_history_sequence, q('History_Sequence_QT', 'multi_choice_history_sequence_question')),
		g('/quiz/history/geography', q('get_history_geography_question', 'multi_choice_question')),
		g('/quiz/history/detail', q('get_history_detail_question', 'multi_choice_question')),
		g('/quiz/history/submissions', q('get_history_submissions_question', 'multi_choice_question')),
		g('/quiz/history/random', q('get_history_random_question', 'multi_choice_question')),
		g('/quiz/geography/orientation', q('get_geography_orientation_question', 'multi_choice_question')),
		g('/quiz/geography/map', q('get_geography_map_question', 'multi_choice_question')),
		g(settings.k_science_grammar, q('Science_Grammar_QT', 'multi_choice_science_question')),
		g('/quiz/science/submissions', q('get_science_submissions_question', 'multi_choice_question')),
		g('/quiz/science/random', q('get_science_random_question', 'multi_choice_question')),
		g('/quiz/math/facts/multiplication', q('get_math_facts_question', 'multi_choice_question')),
		g('/quiz/math/grammar', q('get_math_grammar_question', 'multi_choice_question')),
		# trying new, more directional approach ... g(settings.k_arithmetic_grammar, q('Arithmetic_QT', 'multi_choice_arithmetic_question')),
		g(settings.k_english_grammar, q('English_Grammar_QT', 'multi_choice_english_grammar_question')),
		g(settings.k_english_vocabulary, q('English_Vocabulary_QT', 'multi_choice_english_vocabulary_question')),
		g('/quiz/english/random', q('get_english_random_question', 'multi_choice_question')),
		g('/quiz/latin/grammar', q('get_latin_grammar_question', 'multi_choice_question')),
		g(settings.k_latin_vocabulary, q('Latin_Vocabulary_QT', 'multi_choice_latin_vocabulary_question')),
		g('/quiz/latin/translation', q('get_latin_translation_question', 'multi_choice_question')),
		g('/quiz/latin/random', q('get_latin_random_question', 'multi_choice_question')),
		g('/quiz/music/note', q('get_music_note_question', 'multi_choice_question')),
		g('/quiz/music/key_signature', q('get_music_key_signature_question', 'multi_choice_question')),
		g('/quiz/music/submissions', q('get_music_submissions_question', 'multi_choice_question')),
		g('/quiz/music/random', q('get_music_random_question', 'multi_choice_question')),
	])
	
	# Add startup/shutdown hooks:
	app.on_startup.append(_init)
	app.on_shutdown.append(_shutdown)

	return app


def app():
	return init(None)


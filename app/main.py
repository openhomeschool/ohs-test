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
import time
import traceback

from os.path import exists
from random import shuffle

from sqlite3 import PARSE_DECLTYPES
from dataclasses import dataclass

from uuid import uuid4
from cryptography import fernet
import base64

from aiohttp import web, WSMsgType, WSCloseCode
from aiohttp_session import setup as setup_session, get_session, new_session
from multidict import MultiDict

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
from . import exception
from . import text
from . import settings
from . import util as U


# Logging ---------------------------------------------------------------------

logging.getLogger('aiosqlite').setLevel(logging.WARN)
logging.getLogger('aiohttp').setLevel(logging.WARN)
logging.getLogger('aiohttp_session').setLevel(logging.WARN)
logging.getLogger('asyncio').setLevel(logging.WARN)

logging.getLogger('adev').setLevel(logging.WARN)
#logging.getLogger('adev.server.dft').setLevel(logging.CRITICAL)
#logging.getLogger('adev.server.aux').setLevel(logging.CRITICAL)
#logging.getLogger('adev.tools').setLevel(logging.CRITICAL)
#logging.getLogger('adev.main').setLevel(logging.CRITICAL)

logging.basicConfig(format = '%(asctime)s - %(levelname)s : %(name)s:%(lineno)d -- %(message)s', level = logging.DEBUG if settings.debug else logging.CRITICAL)
l = logging.getLogger(__name__)

# Globals -----------------------------------------------------------------------

# Can't store coroutines in sessions, directly; not even redis or memcached directories, so we store them in global memory, in this dict:
g_twixt_work = {} # TODO: note, we 'del g_twixt_work[twixt_id]' and 'del session['twixt_id']' "as we go", but there's a real possibility of abandonment (as in, a page fails to fully load or to create the ws in its javascript, so the first ws_messages call never issues) -- so we should make a watchdog that cleans this out occasionally; thus, we'd need timestamps on the items within, as well

# Container for session-specific "random-play" playlists:
g_playlists = {}


# Utils -----------------------------------------------------------------------

rt = web.RouteTableDef()
def hr(text): return web.Response(text = text, content_type = 'text/html')

# TEMP, DEBUG!!!!  (for running with:
#   python -m aiohttp.web -H 0.0.0.0 -P 8080 app.main:init
# "raw", and to get /static
#if settings.debug:
#	rt.static('/static', '/home/jmcaine/dev/ohs/ohs-test/static')


def auth(roles):
	'''
	Checks `roles` against user's roles, if user is logged in.
	Sends user to login page if necessary.
	`roles` may be a string, signifying a singleton role needed to access this handler,
	or a list/tuple/set of roles that would suffice.  E.g., 
		auth('user')
		async def handler(rq):
			...
	or:
		auth(('contributor', 'admin'))
		async def handler2(rq):
			...
	'''
	def decorator(func):
		@functools.wraps(func)
		async def wrapper(rq): # no need for *args, **kwargs b/c this decorator is for aiohttp handler functions only, which must accept a Request instance as its only argument
			session = await get_session(rq)
			arg_roles = roles
			if isinstance(roles, str): # then wrap the singleton:
				arg_roles = (roles,)

			if session.get('uuid') and await db.authorized(rq.app['db'], session['uuid'], arg_roles):
				# Process the request (handler) as requested:
				return await func(rq)
			#else, forward to log-in page:
			session['after_login'] = str(rq.rel_url)
			if 'roles' in session: # user is logged in, but the above role-intersection test failed, meaning that user is not permitted to access this particular page
				_add_flash_e(session, error.not_permitted)
			raise web.HTTPFound(_gurl(rq, 'login'))
		return wrapper
	return decorator


# Handlers --------------------------------------------------------------------

async def _finish_login(rq, dbc, username, result, redirect):
	session = await new_session(rq) # "Always use new_session() instead of get_session() in your login views to guard against Session Fixation attacks!" - https://aiohttp-session.readthedocs.io/en/stable/reference.html
		# it's the next bit of information: the new uuid, that is important to not attatch to the old session, to avoid a Session Fixation attack; starting clean here is the place; prior to now, we needed stuff in the (old) session, such as username_logging_in and after_login
	session['uuid'], session['login_time'] = result # result is a two-tuple: (uuid, ts)
	#session.pop('username_logging_in', None) # unnecessary - we just grabbed a fresh session
	raise web.HTTPFound(redirect)

async def _logout(dbc, session, uuid = None):
	if uuid == None:
		uuid = session.get('uuid')
	if uuid:
		await db.forget_login(dbc, uuid)
		session.pop('uuid', None)
	
@rt.get('/login', name = 'login')
async def login(rq):
	session = await get_session(rq)
	await _logout(rq.app['db'], session)
	return hr(html.login(str(rq.rel_url), _get_flash(session), session.get('username_logging_in'))) # special "hide_username" case - during a switch_user to a user that requires a password for the switch

@rt.post('/login')
async def login_(rq):
	data = await rq.post()
	session = await get_session(rq) # TODO: see _finish_login -- that's where we'll do new_session(), before adding in the uuid; for now, we need some things from the existing session
	unli = session.get('username_logging_in')
	if unli: # data['username'] will be empty
		data = {'username': unli, 'password': data['password']} # create a form of `data` that contains username (unli, in this case)
	try:
		# Validate:
		invalids = []
		_validate_regex(data, invalids, (
				('username', valid.rec_username, True),
				('password', valid.rec_string32, True),
			))
		if invalids:
			return hr(html.login(rq.rel_url, _wrap_error(error.invalid_login_input)))

		username = data['username']
		dbc = rq.app['db']
		result = await db.login(dbc, username, data['password'])
		l.debug("LOGIN %s: (uuid, timestamp) = %s", username, result)
		if not result:
			return hr(html.login(rq.rel_url, _wrap_error(error.login_failure))) # TODO: password retrieval mechanism
		#else, success!:
		await _finish_login(rq, dbc, username, result, session['after_login'] if 'after_login' in session else _gurl(rq, 'home'))

	except web.HTTPRedirection:
		raise # move on
	except: # everything else
		return hr(html.login(rq.rel_url, _wrap_error(error.unknown_login_failure)))

@rt.get('/logout', name = 'logout')
async def logout(rq):
	await _logout(rq.app['db'], await get_session(rq))
	raise web.HTTPFound(_gurl(rq, 'home'))

@rt.get('/switch_user/{username}')
async def switch_user(rq):
	session = await get_session(rq)
	# Confirm that current user is authorized to switch:
	uuid = session.get('uuid')
	if not uuid:
		raise web.HTTPFound(_gurl(rq, 'home')) # TODO - replace with a paget that indicates failure?! (or NOT, since this is probably evidence of a malicious attempt to manually /switch_user/ when not logged in as a user that is allowed to switch to the requested user!  In fact, not logged in at all!!)
	#else:
	dbc = rq.app['db']
	try:
		new_username = rq.match_info['username']
		l.debug("(SWITCH_USER) LOGIN (attempt), new user = %s", new_username)
		session.pop('uuid', None) # clear session uuid early; log-out will occur as part of db.switch_user(), below, behind the scenes.  Note that if anything "goes wrong", it's actually good that we are logged-out and session-cleared because the "problem" is indicative of malicious attempts to force a login
		session.pop('login_time', None)
		result = await db.switch_user(dbc, uuid, new_username)
		if result == None: # then password is required for this switch
			session['username_logging_in'] = new_username # removes 'username' burden in login page
			_add_flash_m(session, text.password_required % new_username)
			raise web.HTTPFound(_gurl(rq, 'login'))
		#else: (no password required; real new uuid returned from switch_user(), so, switch was successful (including logout/forget, etc.)...
		await _finish_login(rq, dbc, new_username, result, session['after_login'] if 'after_login' in session else _gurl(rq, 'home'))

	except web.HTTPRedirection:
		raise # move on
	except: # everything else (including exception.InvalidSwitch)... 
		l.error(error.unknown_login_failure)
		_add_flash_e(session, error.unknown_login_failure)
		raise web.HTTPFound(_gurl(rq, 'login'))


@rt.view('/reset_password', name = 'reset_password')
class Reset_Password(web.View):

	async def get(self):
		vw = await _set_up_common_view_get(self, dbc = False, re_log_in_seconds = 60) # dbc only needed in post(), so only set it up there
		return hr(html.reset_password(html.Form(vw.rq.rel_url)))

	async def post(self):
		vw = await _set_up_common_view_post(self, re_log_in_seconds = 60)
		# Validate:
		invalids = []
		_validate_regex(vw.data, invalids, (
				('password', valid.rec_password, True),
				('password_confirmation', valid.rec_password, True),
			))
		if str(vw.data['password']) != str(vw.data['password_confirmation']):
			invalids.append('password_confirmation')
		if invalids:
			# Re-present:
			return hr(html.reset_password(html.Form(vw.rq.rel_url, vw.data, invalids)))
		#else, go on...

		# (Try to) change the password:
		if await db.reset_user_password(vw.dbc, vw.uuid, vw.data['password']):
			vw.session.pop('after_login', None)
			raise web.HTTPFound(_gurl(vw.rq, 'reset_password_success'))
		#else, re-present:
		return hr(html.reset_password(html.Form(vw.rq.rel_url, vw.data, invalids), error.reset_password_failure))

@rt.get('/reset_password_success', name = 'reset_password_success')
async def reset_password_success(rq):
	return hr(html.reset_password_success((
			('Home', _gurl(rq, 'home')),
			('User Settings', _gurl(rq, 'user_settings')),
		)))

@rt.get('/user_settings', name = 'user_settings')
async def user_settings(rq):
	pass # TODO


@rt.view('/new_user', name = 'new_user')
class New_User(web.View):
	async def get(self):
		return hr(html.new_user(html.Form(_gurl(self.request, 'new_user')), _check_username_url(self)))
	
	async def post(self):
		rq = self.request
		data = await rq.post()
		ws_url = _check_username_url(self)
		
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
			return hr(html.new_user(html.Form(rq.rel_url, data, invalids), ws_url, _wrap_error(error.invalid_new_user_input)))
		#else, go on...

		# (Try to) add the user:
		user_id = None
		try:
			user_id = await db.add_user(rq.app['db'], data['new_username'], data['password'], data['email'])
		except IntegrityError: # Note that this should **almost** never happen, as we check username availability in real-time, but it's always possible that another new user with the same username is created milliseconds before the db.add_user() attempt, above; this would make the username suddenly unavailable; we could not possibly have told the user about this in advance, and need to revert to posting an error message now:
			# Re-present with user_exists error:
			return hr(html.new_user(html.Form(rq.rel_url, data), ws_url, text.user_exists))

		#if sess.get('trial'): # TODO!
		#user = db.update_user(dbs, sess['username'], p.username, p.password, p.email)
		#else:
		return hr(html.new_user_success(user_id)) # TODO: lame placeholder - need to redirect, anyway!


@rt.get('/practice', name = 'practice')
@auth('student')
async def practice(rq):
	session = await get_session(rq)
	uuid = session.get('uuid')
	dbc = rq.app['db']

	session['after_login'] = str(rq.rel_url) # come back here after a user-switch; this is a kludgey way of pushing this... haven't worked out how to elegantly retain current page after user-switch, or if it's even desirable.

	# TODO: the following is hard-coded to arithmetic, instead of obeying any filters!! (still in "proof of concept)
	_set_up_twixt(session, _arithmetic_new_problems(dbc, uuid, None, rq.query)) # start the first problem-set lookup now... will be easily done by the time the page is loaded and websocket handshake occurs, when this result is passed on into the loaded page

	links = (
		#(name/title, hint, content, is-url?)
		('⌂', "Home (RETURN to this week's GRAMMAR)", _http_url(rq, '/resources', {}), True),
		('4←', "PRACTICE last four weeks' grammar", _http_url(rq, '/practice', {'program': 1, 'first_week': max(0, k_temp_this_week - 4), 'last_week': k_temp_this_week}), True),
		('%s←' % k_temp_this_week, "PRACTICE ALL grammar so far this year", _http_url(rq, '/practice', {'program': 1, 'first_week': 1, 'last_week': k_temp_this_week}), True),
	)
	login, settings = await _login_button(session, dbc)

	filters = (
		('subject', [(subject['name'], subject['id']) for subject in await db.get_subjects(dbc)], 'Subject'),
		('arithmetic_op', [('+ (Addition)', '+'), ('- (Subtraction)', '-'), ('× (Multiplication)', '×'), ('÷ (Division)', '÷')], 'Operation: + - × ÷'),
	)

	fake_query = {'subject': 4, 'arithmetic_op': '×'} # TODO: this is temporary!!!
	
	return hr(html.practice(_ws_url(rq, '/ws_messages'), links, filters, fake_query, login, settings)) # TODO: return to rq.query!!


@rt.view('/family_invitation/{code}', name = 'family_invitation')
class Family_Invitation(web.View):
	async def common(self):
		code = self.request.match_info['code']
		if not valid.rec_invitation.match(code):
			return hr(html.invalid_invitation()) # this might be an attack attempt!
		#else:
		vw = await _set_up_common_view_get(self)
		invitation = await db.get_new_user_invitation(vw.dbc, code)
		if not invitation:
			return hr(html.invalid_invitation()) # this might be an attack attempt!
		#else:
		person_id, academic_year = invitation['person'], invitation['academic_year']
		person = await db.get_person(vw.dbc, person_id)
		family = await db.get_family_enrollments(vw.dbc, person_id, academic_year)
		return (vw, person, family.children)
		
	async def get(self):
		commons = await self.common()
		if isinstance(commons, web.Response):
			return commons
		#else:
		vw, person, children = commons
		covered = [] # `family` may contain duplicates of a student who is enrolled in multiple programs; we only want each student once, here, so we'll track those covered as we process each of family.children
		all_exist_already = True
		async def _user(p):
			nonlocal all_exist_already
			covered.append(p['id'])
			username = await db.get_person_username(vw.dbc, p['id'])
			exists = True
			if not username:
				username = await db.suggest_username(vw.dbc, p)
				exists = False
				all_exist_already = False
			return {'id': p['id'], 'first_name': p['first_name'], 'last_name': p['last_name'], 'username': username, 'exists': exists}
		users = [await _user(person)]
		users += [await _user(child) for child in children if child['id'] not in covered]
		passwords = await db.forge_noun_passwords(vw.dbc)
		flash = _quick_flash_message(text.new_accounts_family % (person['first_name'], person['last_name']))
		if all_exist_already:
			flash = _quick_flash_message(text.existing_accounts_family)
		return hr(html.family_user_setup(str(vw.rq.rel_url), users, passwords, _ws_url(vw.rq, '/ws_messages'), all_exist_already, flash))


	async def post(self):
		commons = await self.common()
		if isinstance(commons, web.Response):
			return commons
		#else:
		vw, person, children = commons
		data = await self.request.post()
		ids, exists, usernames, passwords = [], [], [], []
		for key, value in data.items():
			# we know these will come in the following order, by contract! first, user 1's pid, then etc... ; then on to user 2, and we're building parallel lists; we don't care about 'names', so we just skip it
			if key.startswith('pid'):
				ids.append(value)
			if key.startswith('exists'):
				exists.append(U.KVPair(key, value))
			if key.startswith('username'):
				usernames.append(value)
			if key.startswith('password'):
				passwords.append(value)

		flash = None
		invalids = []
		# Check for duplicate usernames:
		if len(usernames) != len(set(usernames)): # (sets never include duplicates)
			flash = _quick_flash_error(text.duplicate_usernames_error)
			
		# Try to the database:
		if flash == None:
			await vw.dbc.execute('begin') # apparently the only way to really do transactions like this (see https://stackoverflow.com/questions/15856976/transactions-with-python-sqlite3)
			try:
				used_colors = []
				for x in range(len(ids)):
					if exists[x].value not in ('true', 'True'):
						try:
							# Create user:
							new_uid = await db.create_user(vw.dbc, usernames[x], passwords[x], ids[x], False)
							# Add roles:
							roles = ['student',]
							if await db.is_a_guardian(vw.dbc, ids[x]):
								roles.append('parent')
							await db.add_roles(vw.dbc, new_uid, roles, False)
							# Set default settings (bg-color, etc.)
							used_colors.append(await db.set_user_bg_color(vw.dbc, new_uid, used_colors, False))
							
							# CANNOT do this:  data[each] = 'True' # now they actually do exist!
							#    Note, we can't modify data (it's a MultiDictProxy, so not editable), we will just set all_exist_already to True, below, if all succeeds, and that will flag html.family_user_setup_retry to show all fields as "existing" users, successfully created, despite lingering .exists fields that are "false"
							#    Actually, this doesn't matter, since we're (properly) forwarding on via HTTPFound when all goes well, anyway, to avoid re-POSTs; thus, the 'exists' fields will be rebuilt from database anyway
						except IntegrityError: # Note that this should **almost** never happen, as we check username availability in real-time, but it's possible that another new user with the same username is created milliseconds before the db.add_user() attempt, above; this would make the username suddenly unavailable; we could not possibly have told the user about this in advance, and need to revert to posting an error message now:
							invalids.append(U.tag_it('username', ids[x]))
							flash = _quick_flash_error(text.user_exists)
							raise # break out of loop and induce rollback
				
				uids = [await db.get_user_id(vw.dbc, username) for username in usernames]
				for uid in uids:
					other_uids = uids.copy()
					other_uids.remove(uid)
					await db.add_user_switch_allows(vw.dbc, other_uids, uid, not await db.is_user_teacher(vw.dbc, uid), False)

				# Once all have succeeded:
				await vw.dbc.execute('commit')
			except:
				await vw.dbc.execute('rollback')
				if not flash:
					flash = _quick_flash_error(text.unable_to_save_new_users_error)
				l.debug(traceback.format_exc())
				
		# If flash is unset, we succeeded!:
		if flash == None:
			# Reload the GET for this request, to show all complete:
			raise web.HTTPFound(str(vw.rq.rel_url))
			
		# Finally, if we need to re-present family_user_setup_retry, then generate new random_passwords for use within, and re-present:
		random_passwords = await db.forge_noun_passwords(vw.dbc) # only do this lookup if needed, at the last minute
		return hr(html.family_user_setup_retry(str(vw.rq.rel_url), data, random_passwords, _ws_url(vw.rq, '/ws_messages'), invalids, False, flash)) # assume all_exist_already is False if we're here, or else we would have HTTPFound-forwarded


@rt.view('/invitation/{code}', name = 'invitation')
class Invitation(web.View):
	async def get(self):
		rq = self.request
		code = rq.match_info['code']
		if valid.rec_invitation.match(code):
			dbc = rq.app['db']
			invitation = await db.get_new_user_invitation(dbc, code)
			person_id, academic_year = invitation['person'], invitation['academic_year']
			person = await db.get_person(dbc, person_id)
			enrollments = await db.get_enrollments(dbc, person_id)
			if enrollments: # this is a student
				return hr(html.student_invitation(html.Form(rq.rel_url), invitation, person, enrollments))
			else: # assume this is a parent (TODO: better way todo this -- for person, add "parent" where head-of-household is kept as a record, anyway (though HOH isn't even as useful!)
				family = await db.get_family_enrollments(dbc, person_id, academic_year)
				contact = await db.get_person_contact_info(dbc, person_id)
				costs = await db.get_costs(dbc, academic_year)
				cost_offsets = await db.get_cost_offset(dbc, person_id, academic_year)
				leader = await db.get_leader(dbc, person_id, academic_year)
				payments = await db.get_payments(dbc, [g['id'] for g in family.guardians], academic_year)
				return hr(html.invitation(html.Form(rq.rel_url), invitation, person, family, contact, costs, cost_offsets, leader, payments))
		else:
			return hr(html.invalid_invitation()) # this might be an attack attempt!
		
	async def post(self):
		rq = self.request
		data = await rq.post()


@rt.get('/select_user')
@auth('admin')
async def select_user(rq):
	return hr(html.select_user(_ws_url(rq, '/ws_filter_list')))


@rt.get('/ws_filter_list')
async def ws_filter_list(rq):
	edit_url = _http_url(rq, '/edit_user') # don't use _gurl here - need http specifically, since we're ws/ here
	dbc = rq.app['db']
	
	async def msg_handler(payload, ws):
		assert(payload['task'] == 'search')
		records = None
		if payload['string']:
			string = str(payload['string'])
			if valid.rec_string32.match(string):
				records = await db.find_users(dbc, string)
			else:
				l.warning('string fragment sent to ws_filter_list was not a valid string 32-characters or less') # but do nothing else; client code already checks for validity; this must/might be an attack attempt; no need to respond
		if not records:
			records = await db.get_users_limited(dbc, 10) # A default list (of 10) to show when nothing is entered into search bar:
		await ws.send_json({'task': 'show', 'result': html.filter_user_list(records, edit_url)})

	return msg_handler

@rt.get('/ws_quiz_handler')
async def ws_quiz_handler(rq):
	'''
	Generic "glue" code that manages question/answer mechanics between websocket/client and database/server.
	Specific types of questions are handled quite differently, so the actual DB handler functions are in
	payload['db_answer_function'] and etc., and the HTML-creation code is in payload['html_function'], and
	the payload content may be different, but will be what the particular handler function expects.
	'''
	session = await get_session(rq)
	dbc = rq.app['db']
	db_handler = None # new one will be created each transaction

	async def msg_handler(payload, ws):
		nonlocal db_handler
		if db_handler and payload['task'] == 'answer':
			if payload['answer_id'] >= 0: # -1 indicates "skip"... for now we just allow this and log nothing... TODO: evaluate!
				db_handler.log_user_answer(payload['answer_id'])
		if 'db_handler' in payload: # assume that 'html_function' is there, too
			db_handler = await db.get_handler(payload['db_handler'], dbc, session.get('uuid', None)) # TODO: add args; e.g., history might utilize date_range....
			await ws.send_json({
				'task': 'content',
				'content': html.exposed[payload['html_function']](db_handler.question, db_handler.options),
				'check': db_handler.answer_id})
		else:
			l.warning('Unexpected payload for ws_quiz_handler - no db_handler field!')

	return msg_handler


@rt.get('/', name = 'home')
async def default(rq):
	return await _resources(rq, {})

@rt.get('/grammar')
async def default(rq):
	return await _resources(rq, rq.query)

@rt.get('/resources')
async def resources(rq):
	return await _resources(rq, rq.query)

@rt.get('/shop3')
async def shop_year_program3(rq):
	return await _resources(rq, {'shop': 1, 'cycle': 2, 'program': 3, 'first_week': 0, 'last_week': 28, 'grammar_supplement': 0})

@rt.get('/shop4')
async def shop_year_program4(rq):
	return await _resources(rq, {'shop': 1, 'cycle': 2, 'program': 4, 'first_week': 0, 'last_week': 28, 'grammar_supplement': 0})



@rt.get('/quiz/arithmetic')
async def quiz_arithmetic(rq):
	pass #calculator!



g_detail_handlers = dict()
def detail_handler(handler):
	def decorator(func):
		g_detail_handlers[handler] = func
		return func
	return decorator

@rt.get('/Q/{key}')
async def detail(rq):
	dbc = rq.app['db']
	detail = await db.get_detail(dbc, rq.match_info['key'])
	if detail: # is a 4-tuple: {table, record, details, signs}
		table, record, details, signs = detail
		return await g_detail_handlers[table](record, details, signs)
	else:
		raise web.HTTPFound(_gurl(rq, 'home')) # TODO - replace with a page/message that indicates failure to find the 'key'

@rt.get('/detail/{table}/{id}')
async def event_detail(rq):
	dbc = rq.app['db']
	table = rq.match_info['table']
	detail = await db.get_detail_by_id(dbc, table, rq.match_info['id'])
	if detail: # is a 3-tuple: {record, details, signs (sign-language signs)}
		record, details, signs = detail
		return await g_detail_handlers[table](record, details, signs)
	else:
		raise web.HTTPFound(_gurl(rq, 'home')) # TODO - replace with a page/message that indicates failure to find the 'table/id'


@detail_handler('event')
async def timeline_event_detail(record, details, signs):
	return hr(html.timeline_event_detail(record, details, signs))

@detail_handler('science')
async def science_detail(record, details, signs):
	return hr(html.science_detail(record, details, signs))

k_temp_this_week = 28
k_temp_this_cycle = 2

# cool characters: ⌂♩♪♫♬▲►▼◄→ ʘΞΞΩΨΦΣΠϘЮФѺѼ׀ᴓ₪Ω⃰∞∑∆◊?¿ ᵯ«»
_links = lambda rq: (
	#(name/title, hint, content, is-url?)
	('⌂', "Home (THIS week's grammar)", _http_url(rq, '/resources', {}), True),
	('?', 'Practice/quiz grammar', _http_url(rq, '/practice', {}), True),
	# ¿ - ASSESS?!! (practice, but with teeth!?
	('→', "NEXT week's grammar", _http_url(rq, '/resources', {'week': k_temp_this_week + 1}), True),
	('4←', "REVIEW last four weeks' grammar", _http_url(rq, '/resources', {'program': 1, 'first_week': max(0, k_temp_this_week - 4), 'last_week': k_temp_this_week}), True),
	('%s←' % k_temp_this_week, "REVIEW ALL grammar so far this year", _http_url(rq, '/resources', {'program': 1, 'first_week': 1, 'last_week': k_temp_this_week}), True),
	('►♫', "PLAY random grammar showing below (filtered)", 'toggle_random_play(this)', False),
	#('4-6 assignments': _http_url(rq, '/resources?program=2'),
	#('7th-9th', _http_url(rq, '/resources', {'program': 3}), True),
	#('10th-12th', _http_url(rq, '/resources', {'program': 4}), True),
	#('Shop', _http_url(rq, '/shop'), True),
	#('Quiz', _http_url(rq, '/quiz/history/sequence'), True), # TODO!
)

async def _resources(rq, qargs):
	session = await get_session(rq)
	dbc = rq.app['db']

	_set_up_twixt(session, _first_resources(dbc, qargs)) # start the first lookup now... should be done by the time the page is loaded and websocket handshake occurs, when this result is passed on into the loaded skeletal page

	filters = (
		('program', [(program['name'], program['id']) for program in await db.get_programs(dbc)], 'Program'),
		('grade', (), 'Grade'), # will be populated later
		('subject', [(subject['name'], subject['id']) for subject in await db.get_subjects(dbc)], 'Subject'),
	)
	cycles = ('cycle', [(cycle['name'], cycle['id']) for cycle in await db.get_cycles(dbc)])
	weeks = (
		('first_week', [('W-%d' % week, week) for week in range(0, 29)]), # TODO: hardcode 29!
		('last_week', [('W-%d' % week, week) for week in range(0, 29)]), # TODO: hardcode 29!
	)

	links = _links(rq)
	login, settings = await _login_button(session, dbc)

	return hr(html.resources(_ws_url(rq, '/ws_messages'), filters, cycles, weeks, qargs, links, login, settings))



@rt.get('/ws_messages')
async def ws_messages(rq):
	try:
		ws = web.WebSocketResponse()
		await ws.prepare(rq)
		
		# Send first data if packaged in the initial-data-package called 'twixed', which was fetched from the database between the GET reply and this call to set up the web socket in the page (thus the name "twixt")
		session = await get_session(rq)
		uuid = session.get('uuid')
		twixt_id = session.get('twixt_id')
		spec = None
		if twixt_id:
			twixt = await g_twixt_work[twixt_id] # since session['twixt_id'] exists, then g_twixt_work[twixt_id] should definitely exist; it would be a true 500 exception if it didn't
			spec = twixt.spec
			dbc = rq.app['db']
			if twixt.task == 'resources':
				await ws.send_json(_make_show_resources_message(spec, twixt.result, await _grades_filter(dbc, spec.program)))
				del g_twixt_work[twixt_id] # the show_resources twixt is a 1-timer; just delete now
				del session['twixt_id']
			elif twixt.task == 'arithmetic':
				await ws.send_json(_make_arithmetic_message(twixt_id, twixt, dbc, uuid))
				# First time, we actually need to send TWO problems, as one is cached to swap in as soon as user answers, so...:
				await ws.send_json(_make_arithmetic_message(twixt_id, twixt, dbc, uuid))

		handlers = {
			'check_username': _ws_check_username,
			'filter': _ws_filter,
			'show_shopping': _ws_show_shopping,
			'arithmetic': _ws_arithmetic,
			'arithmetic_totals': _ws_arithmetic_totals,
			'arithmetic_start': _ws_arithmetic_start,
			'arithmetic_filter': _ws_arithmetic_filter,
			'get_random_url_playlist': _get_random_url_playlist,
		}
	
		l.info('Websocket prepared, listening for messages...')
		async for msg in ws:
			try:
				if msg.type == WSMsgType.PING: # some browsers will actually send keepalive pings!
					ws.pong() # respond
				elif msg.type == WSMsgType.PONG:
					pass # nothing to do, but it's nice if the client/browser actually sends PONGs!
				elif msg.type == WSMsgType.TEXT:
					payload = json.loads(msg.data) # Note: payload validated in real msg_handler, below
					if payload['task'] == 'ping':
						# TODO: watch out for potential DOS - don't reply indiscriminately; rather, only reply if enough time has passed since the last ping from the same client
						await ws.send_json({'task': 'pong'}) # would prefer to use WSMsgType.PING rather than a normal message, but javascript doesn't seem to have specified support for that! (see https://stackoverflow.com/questions/10585355/sending-websocket-ping-pong-frame-from-browser)
						await ws.ping() # because some browsers will respond to "real" pings from server, or, at *least*, some browsers will keep the connection open, upon receiving a ping, even if they don't properly PONG!
							# in an ideal world, we wouldn't have our own 'task' 'ping' or 'pong'; rather, we'd rely on ws.ping() or msg.type == WSMsgType.PING, to which we could respond with a PONG, but it doesn't seem that many browsers do this
					else:
						await handlers[payload['task']](rq, payload, ws, spec)
				elif msg.type == WSMsgType.ERROR:
					l.warning('websocket connection closed with exception "%s"' % ws.exception())
				else:
					l.warning('websocket message of unexpected type "%s" received' % msg.type)

			except Exception as e: # per-message exceptions:
				l.error(traceback.format_exc())
				l.error('Exception during WS message processing (detail above); continuing on...')
				if settings.debug:
					raise # force attention...

	except Exception as e:
		l.error(traceback.format_exc())
		l.error('Exception processing WS messages; shutting down WS...')

	return ws


# Util ------------------------------------------------------------------------

_gurl = lambda rq, name: str(rq.app.router[name].url_for())

def _ws_url(rq, name):
	# Builds a url from `rq` (host part, mainly) and `name`, as a websocket-schemed version; e.g.
	#	http://domain.tld/quiz/history/sequence --> ws://domain.tld/<name>
	return URL.build(scheme = settings.k_ws, host = rq.host, path = settings.k_ws_url_prefix + name)

def _http_url(rq, name, query = None):
	# Builds a url from `rq` (host part, mainly) and `name`, as a http(s)-schemed version; e.g.
	#	https://domain.tld/... --> http://domain.tld/<name>
	return URL.build(scheme = settings.k_http, host = rq.host, path = name, query = query)

def _validate_regex(data, invalids, tuple_list):
	for field, regex, required in tuple_list:
		value = str(data[field])
		if (required and not value) or (value and not regex.match(value)):
			invalids.append(field)


_wrap_error = lambda error: ((error,), ()) # make a single error look like a normal (errors, messages) flash pair

k_flash_errors_key = 'flash_errors'
k_flash_messages_key = 'flash_messages'

def _add_flash_m(session, message):
	return _add_flash(session, message, k_flash_messages_key)
def _add_flash_e(session, error):
	return _add_flash(session, error, k_flash_errors_key)
def _add_flash(session, message, key):
	if key not in session:
		session[key] = []
	session[key].append(message)

def _get_flash(session):
	errors = session.get(k_flash_errors_key, [])
	messages = session.get(k_flash_messages_key, [])
	session[k_flash_errors_key] = [] # new empty list
	session[k_flash_messages_key] = [] # new empty list
	return (errors, messages)

def _quick_flash_error(error):
	return ((error,), [])

def _quick_flash_message(message):
	return ([], (message,))
	

# WS Handler stuff  ----------------------------------------------------------------------

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
	spec = U.Struct(
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
		
	return U.Struct(
		task = 'resources',
		spec = spec, # need to send spec, itself, as there's no other way for retrieving end (ws_messages function) to get spec hereafter!
		result = await k_db_handlers[spec.program](dbc, spec),
	)


k_filter_map = {
	'search': (str, valid.rec_string32.match),
	'program': (int, None),
	'grade': (int, None),
	'subject': (int, None),
	'first_week': (int, None), # TODO: add validator to constrain to weeks 0-28?!
	'last_week': (int, None), # TODO: add validator to constrain to weeks 0-28?!
	'external_resource_detail': (int, None),
	'shop': (int, None),
}


async def _ws_filter(rq, payload, ws, spec):
	assert(payload['task'] == 'filter')
	session = await get_session(rq)
	dbc = rq.app['db']

	try:
		cast, validator = k_filter_map[payload['filter']]
		value = cast(payload['data'])
		if validator and not validator(value):
			raise ValueError() # treat like failed cast, above; either way - invalid filter input was tried
		setattr(spec, payload['filter'], value) # note that payload calls must match field names in `spec`; but this is only so by declaration
		result = await k_db_handlers[spec.program](dbc, spec)
		# program changes require special treatment of the "grade" filter/button -- grab the grades that are appropriate for this (new) program selected:
		grades = None if payload['filter'] != 'program' else await _grades_filter(dbc, value) # value is program_id in this case
		# reset any existing playlist; will have to be reconstructed if play_random is attempted again after this filter establishes a new set of grammar
		if 'playlist_id' in session:
			session.pop('playlist_id', None)
		# send the message:
		await ws.send_json(_make_show_resources_message(spec, result, grades))
		
	except ValueError as e:
		l.warning('invalid filter input to ws_resources') # but do nothing else; client code already checks for validity; this must/might be an attack attempt; no need to respond

async def _grades_filter(dbc, program_id):
	program = await db.get_program(dbc, program_id)
	grades = [] # cue to show no "grade" button at all.
	if program['differentiate']:
		grades = [('All', 0), ] # select to show all grades together (within program)
		grades.extend([('%sth' % grade, grade) for grade in range(program['grade_first'], program['grade_last'] + 1)])
	return html.grades_filter_button('grade', grades, program['show_grammar_option'])


async def _arithmetic_new_problems(dbc, uuid, spec, qargs = None):
	if not spec:
		assert(qargs != None) # should only be None if spec is provided; else, should at least be the {} that an empty request.query might be
		spec = U.Struct(
			# NOTE: this is copied from _resources(); consolidate!?!  (Not yet used, but may be a great way of doing this consistently)
			arithmetic_op = qargs.get('arithmetic_op', '×'),
			#program = int(qargs.get('program', 1)), # hardcode default to "grammar school" program if program choice not made (TODO: set this, instead, to logged-in-user's attached program
			#grade = int(qargs.get('grade', 0)), # 0 = "unspecified" or "all"; common, when a program is treated all the same, and there's no need to differentiate grade
			subject = qargs.get('subject', 0), # 0 = "all" indicator
			#cycles = (4, int(qargs.get('cycle', k_temp_this_cycle))), # default: k_temp_this_cycle ("4" refers to grammar that belongs to "all cycles" (like timeline grammar) - this is hardcode! TODO:FIX!)
			first_week = int(qargs.get('first_week', k_temp_this_week)), # TODO: hardcode default to week 0! replace with lookup for user's "current week"
			last_week = int(qargs.get('last_week', k_temp_this_week)), # TODO: see above; look up user's current-week
			week = qargs.get('week', None), # convenience - use this to specify first_week = last_week = week
		)
		if spec.week != None:
			spec.first_week = spec.last_week = int(spec.week)
	
	return U.Struct(
		task = 'arithmetic',
		spec = spec, # need to send spec, itself, as there's no other way for retrieving end (ws_messages function) to get spec hereafter!
		problems = await db.arithmetic_new_problems(dbc, uuid, spec),
		index = 0, # `problems` is a list, so this index is used to track transaction-by-transaction use of the items until they're all used up and another call to _arithmetic_problems()
	)
	

async def _ws_check_username(rq, payload, ws, spec = None):
	# Note: `spec` not used in this function, but required in function signature for generic calling
	assert(payload['task'] == 'check_username')
	dbc = rq.app['db']
	
	if payload['string']:
		value = str(payload['string'])
		if valid.rec_username.match(value):
			exists = await db.username_exists(dbc, payload['string'])
			await ws.send_json({'task': 'check_username', 'div': payload['div'], 'reply': 'exists' if exists else 'available!'})
		else:
			l.warning('username fragment sent to ws_check_username was not a valid string') # but do nothing else; client code already checks for validity; this must/might be an attack attempt; no need to respond


async def _ws_arithmetic_answer(uuid, dbc, payload):
	await db.arithmetic_answer(dbc, uuid, payload)

async def _ws_arithmetic_send_next(session, uuid, dbc, payload, ws, spec):
	
	twixt_id = session.get('twixt_id')
	if not twixt_id:
		# We'll have to fetch the _arithmetic_new_problems now, instead of relying on having been done in twixt, as it should've been...
		# leave spec = `spec`, as there's no twixt.spec; (function arg) `spec` will always be the initial spec sent to ws_messages at time of ws setup, but may get modified internally along the way
		l.warning("_ws_arithmetic was entered without a session['twixt_id']; this is unexpected.  Handling the problem by await'ing a new _arithmetic_new_problems(), but you might want to find out why this happened, contrary to design.")
		twixt_id = _set_up_twixt(session, _arithmetic_new_problems(dbc, uuid, spec))

	twixt = await g_twixt_work[twixt_id]
	assert(twixt.task == 'arithmetic')

	# send the 'next' problem to the client 
	await ws.send_json(_make_arithmetic_message(twixt_id, twixt, dbc, uuid))


async def _ws_arithmetic(rq, payload, ws, spec): # we ignore this 'spec' unless there's no twixt; else we propagate the (possibly changing) spec in the twixt each iteration
	session = await get_session(rq)
	uuid = session.get('uuid')
	dbc = rq.app['db']

	await _ws_arithmetic_answer(uuid, dbc, payload)
	if payload['correct']: # only send next if payload['correct']; if not correct, user is re-presented with previous problem; not ready to be sent another new problem yet):
		await _ws_arithmetic_send_next(session, uuid, dbc, payload, ws, spec)


async def _ws_arithmetic_totals(rq, payload, ws, spec): # we ignore this 'spec' unless there's no twixt; else we propagate the (possibly changing) spec in the twixt each iteration
	session = await get_session(rq)
	uuid = session.get('uuid')
	dbc = rq.app['db']

	result = dict(await db.arithmetic_totals(dbc, uuid, spec))
	result['task'] = 'arithmetic_totals'
	result['total_sizzle_score'] = result['total_correct_count'] * result['total_accuracy'] * 10 / result['total_time']

	await ws.send_json(result)


async def _ws_arithmetic_start(rq, payload, ws, spec): # we ignore this 'spec' unless there's no twixt; else we propagate the (possibly changing) spec in the twixt each iteration
	session = await get_session(rq)
	uuid = session.get('uuid')
	db = rq.app['db']
	# send TWO! - have to always be one ahead
	await _ws_arithmetic_send_next(session, uuid, db, payload, ws, spec)
	await _ws_arithmetic_send_next(session, uuid, db, payload, ws, spec)

async def _ws_arithmetic_filter(rq, payload, ws, spec):
	spec.arithmetic_op = payload.get('data') # operator ('+', '-', etc. sent as data: option_id)
	await _ws_arithmetic_start(rq, payload, ws, spec)

async def _ws_show_shopping(rq, payload, ws, spec = None):
	# Note: `spec` not used in this function, but required in function signature for generic calling
	dbc = rq.app['db']
	match = valid.rec_resource_id_div.match(payload['resource_id'])
	if not match:
		raise ValueError() # treat like a failed cast
	result = await db.get_shopping_links(dbc, match.group(1)) # group(1) is the actual id matched, after the prefix
	await ws.send_json({'task': 'show_shopping', 'div_id': payload['resource_id'], 'result': html.show_shopping(result)})


async def _get_random_url_playlist(rq, payload, ws, spec):
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

	await ws.send_json({'task': 'set_random_url_playlist', 'playlist': result})

async def _login_button(session, dbc):
	result = {'type': 'button'} # default, unless we're already logged in...
	uuid = session.get('uuid')
	settings = {'bg_color': '#eff7f6'} # default (see main.css .flex-wrap .main background-color
	if uuid:
		result = {
			'type': 'menu',
			'username': await db.get_username(dbc, uuid),
			'switch_users': await db.get_switch_users(dbc, uuid) }
		settings = await db.get_user_settings(dbc, uuid)
	return result, settings


def _make_show_resources_message(spec, query_result, grades):
	return {
		'task': 'show_resources',
		'content': html.resource_list(spec, query_result),
		'spec': json.dumps(spec.asdict()),
		'grades': grades,
	}

def _make_arithmetic_message(twixt_id, twixt, dbc, uuid):
	assert(twixt.index < len(twixt.problems))
	problem = twixt.problems[twixt.index]
	twixt.index += 1 # for next fetch
	if twixt.index == len(twixt.problems):
		g_twixt_work[twixt_id] = asyncio.create_task(_arithmetic_new_problems(dbc, uuid, twixt.spec))
	return {
		'task': 'arithmetic',
		'assessment_id': problem['assessment_id'],
		'op1': problem['operand1'],
		'operator': problem['operator'],
		'op2': problem['operand2'],
		'answer': problem['answer'],
		#'spec': json.dumps(spec.asdict()), # really need this?!!!  Don't do the work unless we need this client-side
	}


# Other ----------------------------------------------------------------------

async def _set_up_common_view(view, dbc = True, uuid = True, data = True, re_log_in_seconds = None):
	result = U.Struct(rq = view.request, session = await get_session(view.request))
	if dbc:
		result.dbc = result.rq.app['db'] # TODO: .cursor()
	if uuid:
		result.uuid = result.session.get('uuid')
	if data:
		result.data = await result.rq.post()
	if not re_log_in_seconds:
		return result # done!
	# else...
	login_time = result.session.get('login_time')
	if not result.session.get('uuid') or not login_time: # use result.session.get('uuid') b/c there's no guarantee that uuid=True in args
		_add_flash_m(result.session, text.login_required)
	elif time.time() - login_time > re_log_in_seconds: # we know login_time is non-None, by now; confirm that user logged in within the last re_log_in_seconds seconds, else redirect to login
		_add_flash_m(result.session, text.verify_login_required)
	else:
		return result # all is good; we only want the next two lines if either of the above tests failed and we have flash_m (and have to re-present login page):
	result.session['after_login'] = str(result.rq.url) # come back here after logging in
	raise web.HTTPFound(_gurl(result.rq, 'login'))

async def _set_up_common_view_get(view, dbc = True, re_log_in_seconds = None):
	return await _set_up_common_view(view, dbc, uuid = False, data = False, re_log_in_seconds = re_log_in_seconds)

async def _set_up_common_view_post(view, dbc = True, uuid = True, data = True, re_log_in_seconds = None):
	return await _set_up_common_view(view, dbc, uuid = uuid, data = data, re_log_in_seconds = re_log_in_seconds)

def _set_up_twixt(session, async_call):
	session['twixt_id'] = twixt_id = str(uuid4())
	g_twixt_work[twixt_id] = asyncio.create_task(async_call)
	return twixt_id


# Init / Shutdown -------------------------------------------------------------

async def init_db(filename):
	conn = await aiosqlite.connect(filename, isolation_level = None, detect_types = PARSE_DECLTYPES) # "isolation_level = None disables the Python wrapper's automatic handling of issuing BEGIN etc. for you. What's left is the underlying C library, which does do "autocommit" by default. That autocommit, however, is disabled when you do a BEGIN (b/c you're signaling a transaction with that statement" - from https://stackoverflow.com/questions/15856976/transactions-with-python-sqlite3 - thanks Thanatos
	conn.row_factory = aiosqlite.Row
	await conn.execute('pragma journal_mode = wal') # see https://charlesleifer.com/blog/going-fast-with-sqlite-and-python/ - since we're using async/await from a wsgi stack, this is appropriate
	await conn.execute('pragma foreign_keys = ON')
	#await conn.execute('pragma case_sensitive_like = true')
	#await conn.set_trace_callback(l.debug) - not needed with aiosqlite, anyway
	return conn # consider conn.cursor(), instead, according to more "typical" use; sqlite3 has an "efficient" approach that involves just using the database directly (a temp cursor is auto-created under the hood): https://pysqlite.readthedocs.io/en/latest/sqlite3.html#using-sqlite3-efficiently

async def _init(app):
	l.info('Initializing database...')
	app['db'] = await init_db('ohs-test.db')
	l.info('...database initialized')
	
async def _shutdown(app):
	l.info('Shutting down...')
	if 'db' in app:
		await app['db'].close()
	l.info('...shutdown complete')


	
# Run server like so, from cli:
#		python -m aiohttp.web -H localhost -P 8080 main:init
# Or, using adev (from parent directory!):
#		adev runserver --app-factory init --livereload --debug-toolbar test1_app
async def init(argv):
	app = web.Application()

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
	app.add_routes(rt)
	# And quiz routes:
	def q(db_handler, html_function):
		#@auth('student') # TODO: comment this back in when it's time to auth students who are looking to quiz
		async def quiz(rq):
			return hr(html.quiz(_ws_url(rq, '/ws_quiz_handler'), db_handler, html_function))
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


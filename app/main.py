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

from datetime import datetime, timedelta
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

logging.getLogger('aiosqlite').setLevel(logging.CRITICAL)
logging.getLogger('aiohttp').setLevel(logging.CRITICAL)
logging.getLogger('aiohttp_session').setLevel(logging.CRITICAL)
logging.getLogger('asyncio').setLevel(logging.CRITICAL)

logging.getLogger('adev').setLevel(logging.CRITICAL)
logging.getLogger('adev.server.dft').setLevel(logging.CRITICAL)
logging.getLogger('adev.server.aux').setLevel(logging.CRITICAL)
logging.getLogger('adev.tools').setLevel(logging.CRITICAL)
logging.getLogger('adev.main').setLevel(logging.CRITICAL)

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
		if session.get('username_logging_in'): # just to be on the safe side
			session.pop('username_logging_in')
	
@rt.get('/login', name = 'login')
async def login(rq):
	session = await get_session(rq)
	await _logout(rq.app['db'], session)
	return hr(html.login(str(rq.rel_url), _get_flash(session), session.get('username_logging_in'))) # special "hide_username" case - during a switch_user to a user that requires a password for the switch

@rt.get('/login/{after_login}')
async def login_then(rq):
	session = await get_session(rq)
	await _logout(rq.app['db'], session)
	session['after_login'] = _gurl(rq, rq.match_info['after_login'])
	return hr(html.login(_gurl(rq, 'login')))


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
		await _finish_login(rq, dbc, username, result, session.get('after_login', _gurl(rq, 'home')))

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
		await _finish_login(rq, dbc, new_username, result, session.get('after_login', _gurl(rq, 'home')))

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
		if await db.reset_user_password(vw.dbc, await db.get_user_id_from_uuid(vw.dbc, vw.uuid), vw.data['password']):
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
		return hr(html.new_user(html.Form(_gurl(self.request, 'new_user')), self.request.host))
	
	async def post(self):
		rq = self.request
		data = await rq.post()
		
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
			return hr(html.new_user(html.Form(rq.rel_url, data, invalids), rq.host, _wrap_error(error.invalid_new_user_input)))
		#else, go on...

		# (Try to) add the user:
		user_id = None
		try:
			user_id = await db.add_user(rq.app['db'], data['new_username'], data['password'], data['email'])
		except IntegrityError: # Note that this should **almost** never happen, as we check username availability in real-time, but it's always possible that another new user with the same username is created milliseconds before the db.add_user() attempt, above; this would make the username suddenly unavailable; we could not possibly have told the user about this in advance, and need to revert to posting an error message now:
			# Re-present with user_exists error:
			return hr(html.new_user(html.Form(rq.rel_url, data), rq.host, text.user_exists))

		#if sess.get('trial'): # TODO!
		#user = db.update_user(dbs, sess['username'], p.username, p.password, p.email)
		#else:
		return hr(html.new_user_success(user_id)) # TODO: lame placeholder - need to redirect, anyway!


@rt.get('/practice_stats')
@auth('admin')
async def practice_stats(rq):
	session = await get_session(rq)
	dbc = rq.app['db']
	results = await db.get_practice_stats(dbc)
	links = (
		#(name/title, hint, content, is-url?)
		('⌂', "Home (RETURN to this week's GRAMMAR)", _http_url(rq, '/resources', {}), True),
	)
	login, settings = await _login_button(session, dbc)
	return hr(html.practice_stats(links, login, settings, results))


@rt.get('/practice', name = 'practice')
@auth('student')
async def practice(rq):
	session = await get_session(rq)
	session['after_login'] = str(rq.rel_url) # come back here after a user-switch; this is a kludgey way of pushing this... haven't worked out how to elegantly retain current page after user-switch, or if it's even desirable.
	uuid = session.get('uuid')
	dbc = rq.app['db']

	spec = _make_practice_spec(rq.query)
	_set_up_twixt(session, 'practice', _practice_fetch_new_problems(dbc, uuid, spec), spec) # start the first problem-set lookup now... will be easily done by the time the page is loaded and websocket handshake occurs, when this result is passed on into the loaded page

	links = (
		#(name/title, hint, content, is-url?)
		('⌂', "Home (RETURN to this week's GRAMMAR)", _http_url(rq, '/resources', {}), True),
		('4←', "PRACTICE last four weeks' grammar", _http_url(rq, '/practice', {'program': 1, 'first_week': max(0, k_temp_this_week - 4), 'last_week': k_temp_this_week}), True),
		('%s←' % k_temp_this_week, "PRACTICE ALL grammar so far this year", _http_url(rq, '/practice', {'program': 1, 'first_week': 1, 'last_week': k_temp_this_week}), True),
	)
	login, settings = await _login_button(session, dbc)

	filters = (
		# (key, options, hint, selected_id)
		('subject', [(subject['name'], subject['id']) for subject in await db.get_subjects(dbc, 'practice')], 'Subject', spec.subject),
	)

	return hr(html.practice(links, filters, login, settings, rq.host))


@rt.view('/enroll', name = 'enroll')
@auth('coordinator')
class Enroll(web.View):
	async def get(self):
		vw = await _set_up_common_view_get(self)
		# TODO: Plan: list of users w/ filter-field on top, to instantly filter via WS, then spot for grade, program, and academic-year (translated to name like "Cycle 3")
		return hr(html.enroll())
	async def set(self):
		return hr(html.enroll())

#@rt.view('/go_edit_user/{username}')
@rt.view('/go_edit_user/{username}/{family_invitation_code}')
class Go_Edit_User(web.View):
	async def common(self):
		#code = None
		code = self.request.match_info['family_invitation_code']
		if code and not valid.rec_invitation.match(code):
			return hr(html.invalid_invitation()) # this might be an attack attempt!
		#else:
		username = self.request.match_info['username']
		vw = await _set_up_common_view_get(self, re_log_in_seconds = None if code else 60) # force re-login (if login was more than 60 seconds ago) if a special invitation code is not used here
		uid = None
		if not code: # if no code; attempt is being made by a logged-in user; but, with code, we'll need to look up uid of invitation-bearer
			vw.uuid = vw.session.get('uuid')
			if not vw.uuid:
				raise web.HTTPFound(_gurl(vw.rq, 'login'))
			#else:
			uid = await db.get_user_id_from_uuid(vw.dbc, vw.uuid, False)
		else:
			invitation = await db.get_new_user_invitation(vw.dbc, code)
			if not invitation:
				return hr(html.invalid_invitation()) # this might be an attack attempt!
			#else:
			# Get uid of invitation-bearer:
			uid = await db.get_user_id_from_person_id(vw.dbc, invitation['person'])

		if not uid:
			raise web.HTTPFound(_gurl(vw.rq, 'login')) # a message might be useful here; there is a chance of this being attempted for an invitation that hasn't yet been processed (no user exists yet!)....

		if not (await db.is_guardian_of(vw.dbc, uid, username) or await db.is_user(vw.dbc, uid, username)):
			return hr(html.invalid_invitation()) # this might be an attack attempt! (note, this isn't exactly the right kind of message; bottom line is that the user attempting this isn't a guardian of the user needing the password reset (and isn't self)....

		vw.uid = await db.get_user_id_from_username(vw.dbc, username)
		return vw
		
	async def get(self):
		commons = await self.common()
		if isinstance(commons, web.Response):
			return commons
		#else:
		vw = commons
		return hr(html.reset_password(html.Form(vw.rq.rel_url)))

	async def post(self):
		commons = await self.common()
		if isinstance(commons, web.Response):
			return commons
		#else:
		vw = commons
		data = await self.request.post()

		invalids = []
		_validate_regex(data, invalids, (
				('password', valid.rec_password, True),
				('password_confirmation', valid.rec_password, True),
			))
		if str(data['password']) != str(data['password_confirmation']):
			invalids.append('password_confirmation')
		if invalids:
			# Re-present:
			return hr(html.reset_password(html.Form(vw.rq.rel_url, data, invalids)))
		#else...

		# (Try to) change the password:
		if await db.reset_user_password(vw.dbc, vw.uid, data['password']):
			vw.session.pop('after_login', None)
			raise web.HTTPFound(_gurl(vw.rq, 'reset_password_success'))
		#else, re-present:
		return hr(html.reset_password(html.Form(vw.rq.rel_url, data, invalids), error.reset_password_failure))
		

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
		return (vw, person, family.children, code)
		
	async def get(self):
		commons = await self.common()
		if isinstance(commons, web.Response):
			return commons
		#else:
		vw, person, children, code = commons
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
		_set_up_twixt(vw.session, 'family_invitation', None, None)

		return hr(html.family_user_setup(str(vw.rq.rel_url), code, users, passwords, _ws_url(vw.rq, '/ws_messages'), all_exist_already, flash))


	async def post(self):
		commons = await self.common()
		if isinstance(commons, web.Response):
			return commons
		#else:
		vw, person, children, code = commons
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
				
				uids = [await db.get_user_id(vw.dbc, username) for username in usernames] # don't worry about exists[x]; in fact, we need ALL users in order to establish switch-allows between existing and new users.  db.add_user_switch_allows() resists duplications
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
		return hr(html.family_user_setup_retry(str(vw.rq.rel_url), code, data, random_passwords, _ws_url(vw.rq, '/ws_messages'), invalids, False, flash)) # assume all_exist_already is False if we're here, or else we would have HTTPFound-forwarded


#@rt.view('/invitation/{code}', name = 'invitation')
class Invitation_DEPRECATED(web.View):
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

async def _financial(rq, dbc, session, person, academic_year):
	session['after_login'] = str(rq.rel_url) # come back here after a user-switch; this is a kludgey way of pushing this... haven't worked out how to elegantly retain current page after user-switch, or if it's even desirable.

	links = (
		#(name/title, hint, content, is-url?)
		('⌂', "Home (RETURN to this week's GRAMMAR)", _http_url(rq, '/resources', {}), True),
	)
	login, settings = await _login_button(session, dbc)

	#academic_year = 2 # !!!!!!!!!!!!!!!!!! # TODO: '3' (2022-23) is hard-coded!  ALSO, should look up ONLY years this user has been enrolled!
	#academic_year = 3 # TODO: '3' is hard-coded!!! ALSO, should look up ONLY years this user has been enrolled!
	years_filter = ( # (key, options, hint, selected_id)
		'academic_year', [(year['name'], year['id']) for year in await db.get_academic_years(dbc)], 'Year', academic_year) 

	person_id = person['id']
	family = await db.get_family_enrollments(dbc, person_id, academic_year)
	contact = await db.get_person_contact_info(dbc, person_id)
	costs = await db.get_costs(dbc, academic_year)
	cost_offsets = await db.get_cost_offset(dbc, person_id, academic_year)
	leaders = await db.get_leaders(dbc, family.guardians, academic_year)
	payments = await db.get_payments(dbc, [g['id'] for g in family.guardians], academic_year)
	return hr(html.financial(links, years_filter, login, settings, person, family, contact, costs, cost_offsets, leaders, payments, rq.host))

@rt.get('/a_financial/{person_id}')
@auth('admin')
async def a_financial(rq):
	dbc = rq.app['db']
	return await _financial(rq, dbc, await get_session(rq), await db.get_person(dbc, rq.match_info['person_id']), int(rq.query.get('academic_year', -1)))

@rt.get('/financial')
@auth('parent')
async def financial(rq):
	session = await get_session(rq)
	dbc = rq.app['db']
	return await _financial(rq, dbc, session, await db.get_person_by_uuid(dbc, session.get('uuid')), rq.query.get('academic_year', -1))

@rt.get('/appointments')
async def appointments(rq):
	session = await get_session(rq)
	dbc = rq.app['db']
	now = datetime.now()
	appointments = await db.get_appointments(dbc, now, now + timedelta(days = 30))
	links = (
		#(name/title, hint, content, is-url?)
		('⌂', "Home (RETURN to this week's GRAMMAR)", _http_url(rq, '/resources', {}), True),
	)
	login, settings = await _login_button(session, dbc)
	
	return hr(html.appointments(links, login, settings, appointments))


@rt.get('/ical/{appointment_id}.ics')
async def ical_appointment(rq):
	dbc = rq.app['db']
	ical = await db.get_appointment_ical(dbc, rq.match_info['appointment_id'])
	text = "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//openhome.school//calendar\n" + ical['ical'] + "END:VCALENDAR"
	return web.Response(text = text, content_type = 'text/calendar')

@rt.get('/ical_all/all.ics')
async def ical_all_appointments(rq):
	dbc = rq.app['db']
	events = ''.join([e['ical'] for e in await db.get_appointments_ical(dbc)])
	text = "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//openhome.school//calendar\n" + events + "END:VCALENDAR"
	return web.Response(text = text, content_type = 'text/calendar')

@rt.get('/select_user')
@auth('admin')
async def select_user(rq):
	return hr(html.select_user(_ws_url(rq, '/ws_filter_list'), rq.host))


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

@rt.get('/shop1', name = 'shop1')
async def shop_year_program1(rq):
	return await _resources(rq, {'shop': 1, 'cycle': 3, 'program': 1, 'week': -1, 'grammar_supplement': 0})

@rt.get('/shop2', name = 'shop2')
async def shop_year_program2(rq):
	return await _resources(rq, {'shop': 1, 'cycle': 3, 'program': 2, 'week': -1, 'grammar_supplement': 0})

@rt.get('/shop3', name = 'shop3')
async def shop_year_program3(rq):
	return await _resources(rq, {'shop': 1, 'cycle': 3, 'program': 3, 'week': -1, 'grammar_supplement': 0})

@rt.get('/shop4', name = 'shop4')
async def shop_year_program4(rq):
	return await _resources(rq, {'shop': 1, 'cycle': 3, 'program': 4, 'week': -1, 'grammar_supplement': 0})



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
		return await g_detail_handlers[table](record, details, signs, rq.host)
	else:
		raise web.HTTPFound(_gurl(rq, 'home')) # TODO - replace with a page/message that indicates failure to find the 'key'

@rt.get('/detail/{table}/{id}')
async def event_detail(rq):
	dbc = rq.app['db']
	table = rq.match_info['table']
	detail = await db.get_detail_by_id(dbc, table, rq.match_info['id'])
	if detail: # is a 3-tuple: {record, details, signs (sign-language signs)}
		record, details, signs = detail
		return await g_detail_handlers[table](record, details, signs, rq.host)
	else:
		raise web.HTTPFound(_gurl(rq, 'home')) # TODO - replace with a page/message that indicates failure to find the 'table/id'


@detail_handler('event')
async def timeline_event_detail(record, details, signs, host):
	return hr(html.timeline_event_detail(record, details, signs, host))

@detail_handler('science')
async def science_detail(record, details, signs, host):
	return hr(html.science_detail(record, details, signs, host))

k_temp_this_week = 6
k_temp_this_cycle = 3
k_temp_this_academic_year = 3

# cool characters: ⌂♩♪♫♬▲►▼◄→ ʘΞΞΩΨΦΣΠϘЮФѺѼ׀ᴓ₪Ω⃰∞∑∆◊?¿ ᵯ«»   ₧◙□∞Ξ©π
_links = lambda rq: (
	#(name/title, hint, content, is-url?)
	('⌂', "Home (THIS week)", _http_url(rq, '/resources', {}), True),
	('π', 'Practice/quiz grammar', _http_url(rq, '/practice', {}), True),
	('©', 'Calendar', _http_url(rq, '/appointments', {}), True),
	('$', 'Shop', _http_url(rq, '/shop1', {}), True),
	
	# ¿ - ASSESS?!! (practice, but with teeth!?
	('→1', "NEXT week", _http_url(rq, '/resources', {'week': k_temp_this_week + 1}), True),
	('4←', "REVIEW last four weeks", _http_url(rq, '/resources', {'program': 1, 'first_week': max(0, k_temp_this_week - 4), 'last_week': k_temp_this_week}), True),
	('%s←' % k_temp_this_week, "REVIEW ALL so far this year", _http_url(rq, '/resources', {'program': 1, 'first_week': 1, 'last_week': k_temp_this_week}), True),
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
	uid = await db.get_user_id_from_uuid(dbc, session.get('uuid'), False)
	#uid = 1 #!!!!!!
	spec = _make_resources_spec(qargs)
	_set_up_twixt(session, 'resources', _first_resources(dbc, uid, spec), spec) # start the first lookup now... should be done by the time the page is loaded and websocket handshake occurs, when this result is passed on into the loaded skeletal page

	filters = ( # title, key:
		('All Programs', 'program'),
		('All Grades', 'grade'),
		('All Subjects', 'subject'),
	)
	# (key, options, selected_id) for following:
	cycles = ('cycle', [(cycle['name'], cycle['id']) for cycle in await db.get_cycles(dbc)], qargs.get('cycle'))
	weeks = (
		('first_week', [('W-%d' % week, week) for week in range(0, 29)], spec.first_week), # TODO: hardcode 29!
		('last_week', [('W-%d' % week, week) for week in range(0, 29)], spec.last_week), # TODO: hardcode 29!
	)

	links = _links(rq)
	login, settings = await _login_button(session, dbc)

	content = None if not spec.linear else html.resource_list(spec, await _first_resources(dbc, uid, spec)) # content = None is the "normal" mode; spec.linear is just for (see above).  NOTE: inefficient DUPLICATE call to get first resources! (since twixt is already looking to fulfill - in the case of k_linear, we'll just never utilized the fetch that is done in the background while initial page-load occurs and websocket is set up; rather, that work is throw-away; however, this ONLY happens in the spec.linear case, which is ONLY used to generate printable syllabi using print-syllabi.py, so this should be fine.)
	return hr(html.resources(_ws_url(rq, '/ws_messages'), filters, cycles, weeks, qargs, links, login, settings, content))


@rt.get('/ws_messages')
async def ws_messages(rq):
	ws = web.WebSocketResponse()
	await ws.prepare(rq)
	session = await get_session(rq)
	try:
		# The first data (to send back to client) was packaged in the initial-data-package called 'twixt'; it was fetched from the database between ("betwixt") the initial GET and this call to set up the web socket within the page (thus the name "twixt")
		twixt = g_twixt_work[session['twixt_id']] # g_twixt_work[twixt_id] should definitely exist. By design, twixt must always exist for every ws kicked off;  it is a true 500 exception error case for a twixt to not exist; NOTE: we'll 'await' twixt.result later...

		hd = handler_data = U.Struct(
			rq = rq,
			ws = ws,
			session = session,
			uuid = session.get('uuid'),
			dbc = rq.app['db'],
			spec = twixt.spec,
			data = twixt.result, # we don't even 'await' this now!  Just pass it on... will await handler_data.data later! (In the meantime, it's finishing (or finished), but the real reason we're delaying the await is for the uniformity of handling `data`; later, in some cases, data is assigned to a new asyncio.create_task(); we want the await() to happen in the same place always, whether we got this data/result from twixt or from another, later assignment
		)
		try:
			if twixt.task == 'resources':
				programs = await _programs_filter_button(hd.dbc, hd.spec.program)
				grades = await _grades_filter_button(hd.dbc, hd.spec.program, hd.spec.grade)
				subjects = await _subjects_filter_button(hd.dbc, hd.spec.program, hd.spec.subject)
				await _send_show_resources_message(hd, programs, grades, subjects)
			elif twixt.task == 'practice':
				send_show_practice_message_makers = {
					14: _send_show_arithmetic_message,
				}
				await send_show_practice_message_makers[hd.spec.subject](hd)
			else:
				l.warning(f'Unknown twixt.task: ({twixt.task})!')
		finally:
			del g_twixt_work[session['twixt_id']]
			del session['twixt_id']

		handlers = {
			'ping': _ws_ping_pong,
			'check_username': _ws_check_username,
			'filter': _ws_filter,
			'show_shopping': _ws_show_shopping,
			'practice_filter': _ws_practice_filter,
			'arithmetic_answer': _ws_arithmetic_answer_swap,
			'arithmetic_start': _ws_arithmetic_start,
			'arithmetic_filter': _ws_arithmetic_filter,
			'arithmetic_totals': _ws_arithmetic_totals,
			'get_random_url_playlist': _get_random_url_playlist,
			'mark_assignment': _ws_mark_assignment,
		}

		l.info('Websocket prepared, listening for messages...')
		async for msg in ws:
			try:
				if msg.type == WSMsgType.PING: # some browsers will actually send keepalive pings!
					ws.pong() # respond
				elif msg.type == WSMsgType.PONG:
					pass # nothing to do, but it's nice if the client/browser actually sends PONGs!
				elif msg.type == WSMsgType.TEXT:
					hd.payload = json.loads(msg.data) # Note: payload validated in real msg_handlers, later
					await handlers[hd.payload['task']](hd)
				elif msg.type == WSMsgType.ERROR:
					l.warning('websocket connection closed with exception "%s"' % ws.exception())
				else:
					l.warning('websocket message of unexpected type "%s" received' % msg.type)

			except Exception as e: # per-message exceptions:
				l.error(traceback.format_exc())
				l.error('Exception during WS message processing (detail above); continuing on...')

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
	0: db.get_grammar_resources,
	1: db.get_grammar_resources,
	2: db.get_middle_resources,
	3: db.get_high1_resources,
	4: db.get_high1_resources, # TODO: placeholder
	5: db.get_grammar_resources, # TODO: placeholder
	6: db.get_grammar_resources, # TODO: placeholder
	7: db.get_grammar_resources, # TODO: placeholder
	8: db.get_high1_resources, # TODO: placeholder
	9: db.get_high1_resources, # TODO: placeholder
	10: db.get_high1_resources, # TODO: placeholder
}

def _make_resources_spec(qargs):
	spec = U.Struct(
		search = qargs.get('search'),
		deep_search = False,
		program = int(qargs.get('program', 0)), # 0 = "default" (will probably be interpreted as "grammarschool" (program "1")
		grade = int(qargs.get('grade', 0)), # 0 = "unspecified" or "all"; common, when a program is treated all the same, and there's no need to differentiate grade
		solo = int(qargs.get('solo', 0)), # 0 = show the designed content for the program; 1 = show *only* the content unique to the program -- TODO: DEPRECATED? I think 'grammar_supplement' now takes care of this, and can't find references to solo elsewhere.....
		shop = int(qargs.get('shop', 0)), # 1 = show shopping links (all opened up); only pertains to "resources" views, not "grammar" views, which don't show any purchasable resources
		subject = qargs.get('subject', 0), # 0 = "all" indicator
		cycles = (0, int(qargs.get('cycle', k_temp_this_cycle))), # default: k_temp_this_cycle ("0" refers to grammar that belongs to "all cycles" (like timeline grammar) - this is hardcode! TODO:FIX!)
		first_week = int(qargs.get('first_week', k_temp_this_week)), # TODO: hardcode default to week 0! replace with lookup for user's "current week"
		last_week = int(qargs.get('last_week', k_temp_this_week)), # TODO: see above; look up user's current-week
		week = qargs.get('week', None), # convenience - use this to specify first_week = last_week = week
		grammar_supplement = int(qargs.get('grammar_supplement', 0)), # 1 = show grammar (at the bottom of assignments)
		for_print = int(qargs.get('for_print', 0)), # 1 = no buttons, no header
		secondaries = int(qargs.get('secondaries', 0)), # 1 = include secondary history sentences, etc. ("advanced" material), 0 = don't
		timeline_sentences = int(qargs.get('timeline_sentences', 0)), # 1 = include timeline sentences, 0 = don't
		no_maps = int(qargs.get('no_maps', 0)), # 1 = OMIT maps in geography section, 0 = don't
		show_search = int(qargs.get('show_search', 1)), # 1 = show search bar, 0 = don't
		show_go = int(qargs.get('show_go', 1)), # 1 = show go bar, 0 = don't
		random_audio_type = int(qargs.get('random_audio_type', 7)), # 4 = 'song-simple'
		as_user_id = int(qargs.get('as_user_id', 0)), # will require 'admin' to work (or maybe a parent)
		linear = int(qargs.get('linear', 0)), # 1 = load linearly, in-line, rather than "dynamically" via follow-up websocket call.  Currently (2022-9-8) this is only supported by resources/, and is use primarily in the creation of syllabus printing, using print-syllabi.py
		academic_year = int(qargs.get('academic_year', -1)), # the academic_year field in tables like enrollment; designating the specific year of a student's enrollment, and thus, e.g., showing them the right syllabus (e.g., as a 9th grader, rather than the 8th-grader they were last year); the default of -1 just means "the highest on record", i.e., the "current" or at least "most recent"
	)
	if spec.week != None:
		spec.first_week = spec.last_week = int(spec.week)

	return spec


async def _first_resources(dbc, uid, spec):
	program = spec.program if spec.program else (await db.get_primary_program(dbc, uid, spec) if uid else 1) # "interpret" (default) program "0" to imply program (ID) "1" (grammarschool), a little hard-codey?  Note: leave spec.program, itself, 0, which may clue deeper code to interpret its as default, and calculate it
	return await k_db_handlers[program](dbc, spec, uid) # spec should hold "default" (program = 0, grade = 0) values, if that's what spec has, so that it can interpret program and grade from user (id), but, of course, the right k_db_handlers has to be called upon...


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


async def _ws_filter(hd):
	cast, validator = k_filter_map[hd.payload['filter']]
	value = cast(hd.payload['data'])
	if validator and not validator(value):
		raise ValueError() # treat like failed cast, above; either way - invalid filter input was tried
	setattr(hd.spec, hd.payload['filter'], value) # note that hd.payload calls must match field names in `hd.spec`; but this is only so by declaration
	uid = await db.get_user_id_from_uuid(hd.dbc, hd.uuid, False)
	hd.data = k_db_handlers[hd.spec.program](hd.dbc, hd.spec, uid) # await() later, upon use; in this case, there's no real advantage, as we're not setting this up to run between transactions, but we want a uniform treatment, which (by declaration) always involves await()ing data right before use
	# program changes require special treatment of the "grade" filter/button -- grab the grades that are appropriate for this (new) program selected:
	grades = None if hd.payload['filter'] != 'program' else await _grades_filter_button(hd.dbc, value, hd.spec.grade) # value is program_id in this case
	# reset any existing playlist; will have to be reconstructed if play_random is attempted again after this filter establishes a new set of grammar
	if 'playlist_id' in hd.session:
		hd.session.pop('playlist_id', None)
	# send the message:
	await _send_show_resources_message(hd, None, grades, None) # never (?) a need to re-load the "programs" in response to a filter selection, but may want to re-load "subjects" - e.g., some programs include different subjects than others....


async def _grades_filter_button(dbc, program_id, selected_id):
	program = await db.get_program(dbc, program_id)
	if program and program['differentiate']:
		grades = [('All Grades', 0), ] # select to show all grades together (within program)
		grades.extend([('%sth' % grade, grade) for grade in range(program['grade_first'], program['grade_last'] + 1)])
		return html.grades_filter_button('grade', grades, selected_id, False) #TODO? last arg: program['show_grammar_option']) --- probably the wrong place for this, if we even want it at all?
			# consider just using html.filter_button() if, indeed, we totally kill (or move) the 'show_grammar_option' functionality
	else:
		return -1 # cue to show no "grade" button at all.

async def _programs_filter_button(dbc, selected_id):
	programs = [(program['name'], program['id']) for program in await db.get_programs(dbc)]
	return html.filter_button('program', programs, selected_id)

async def _subjects_filter_button(dbc, program_id, selected_id):
	# TODO: add support for program_id...?  maybe even grade? (be careful, a student may have ONE class in another grade (not her default grade), which will show up, in general, but perhaps the subject of that class wouldn't show, based on her primary program/grade? tricky!
	subjects = [(subject['name'], subject['id']) for subject in await db.get_subjects(dbc)]
	return html.filter_button('subject', subjects, selected_id)


def _arithmetic_add_spec_details(spec, qargs):
	spec.arithmetic_op = qargs.get('arithmetic_op', '×') # default to multiplication if not specified

_practice_subject_add_spec_details = { # Note, keys in this dict are hard-tied to id field in Subject table, in database!
	14: _arithmetic_add_spec_details
	# others...
}
_practice_subject_fetch_new_problems = { # Note, keys in this dict are hard-tied to id field in Subject table, in database!
	14: lambda dbc, uuid, spec: db.fetch_new_arithmetic_problems(dbc, uuid, spec),
	# others...
}

def _make_practice_spec(qargs):
	spec = U.Struct(
		# NOTE: this is copied from _resources(); consolidate!?!  (Not yet used, but may be a great way of doing this consistently)
		subject = qargs.get('subject', 14), # 14 = "Arithmetic" (hard-code default)
		#program = int(qargs.get('program', 1)), # hardcode default to "grammar school" program if program choice not made (TODO: set this, instead, to logged-in-user's attached program
		#grade = int(qargs.get('grade', 0)), # 0 = "unspecified" or "all"; common, when a program is treated all the same, and there's no need to differentiate grade
		#cycles = (4, int(qargs.get('cycle', k_temp_this_cycle))), # default: k_temp_this_cycle ("4" refers to grammar that belongs to "all cycles" (like timeline grammar) - this is hardcode! TODO:FIX!)
		first_week = int(qargs.get('first_week', k_temp_this_week)), # TODO: hardcode default to week 0! replace with lookup for user's "current week"
		last_week = int(qargs.get('last_week', k_temp_this_week)), # TODO: see above; look up user's current-week
		week = qargs.get('week', None), # convenience - use this to specify first_week = last_week = week
	)
	if spec.week != None:
		spec.first_week = spec.last_week = int(spec.week)
	_practice_subject_add_spec_details[spec.subject](spec, qargs)
	return spec

async def _practice_fetch_new_problems(dbc, uuid, spec):
	return U.Struct(
		problems = await db.fetch_new_arithmetic_problems(dbc, uuid, spec),
		index = 0, # `problems` is a list, so this index is used to track problem-by-problem use, through the list, until they're all used up and another call to _practice_fetch_new_problems() needs to be made
	)


async def _ws_check_username(hd):
	if hd.payload['string']:
		value = str(hd.payload['string'])
		if valid.rec_username.match(value):
			exists = await db.username_exists(hd.dbc, hd.payload['string'])
			await hd.ws.send_json({'task': 'check_username', 'div': hd.payload['div'], 'reply': 'exists' if exists else 'available!'})
		else:
			l.warning('username fragment sent to ws_check_username was not a valid string') # but do nothing else; client code already checks for validity; this must/might be an attack attempt; no need to respond


async def _ws_arithmetic_answer_swap(hd):
	await db.arithmetic_answer(hd.dbc, hd.uuid, hd.payload)
	if hd.payload['correct']: # only send next problem if hd.payload['correct']; if not correct, user is re-presented with previous problem; not ready to be sent another new problem yet):
		# send the 'next' problem to the client:
		await hd.ws.send_json(await _make_arithmetic_problem_message(hd))


async def _ws_arithmetic_totals(hd):
	result = dict(await db.arithmetic_totals(hd.dbc, hd.uuid, hd.spec))
	result['task'] = 'arithmetic_totals'

	await hd.ws.send_json(result)


async def _ws_ping_pong(hd):
	# TODO: watch out for potential DOS - don't reply indiscriminately; rather, only reply if enough time has passed since the last ping from the same client
	await hd.ws.send_json({'task': 'pong'}) # would prefer to use WSMsgType.PING rather than a normal message, but javascript doesn't seem to have specified support for that! (see https://stackoverflow.com/questions/10585355/sending-websocket-ping-pong-frame-from-browser)
	await hd.ws.ping() # because some browsers will respond to "real" pings from server, or, at *least*, some browsers will keep the connection open, upon receiving a ping, even if they don't properly PONG!
		# in an ideal world, we wouldn't have our own 'task' 'ping' or 'pong'; rather, we'd rely on ws.ping() or msg.type == WSMsgType.PING, to which we could respond with a PONG, but it doesn't seem that many browsers do this

async def _ws_arithmetic_start(hd):
	await _send_show_arithmetic_message(hd)

async def _ws_arithmetic_filter(hd):
	hd.spec.arithmetic_op = hd.payload.get('data') # operator ('+', '-', etc. (option_id) sent as 'data')
	await _ws_arithmetic_start(hd)

async def _ws_practice_filter(hd):
	hd.spec.subject = hd.payload.get('data') # id of subject
	#!!!!await _ws_arithmetic_start(hd)


async def _ws_show_shopping(hd):
	match = valid.rec_resource_id_div.match(hd.payload['resource_id'])
	if not match:
		raise ValueError() # treat like a failed cast
	result = await db.get_shopping_links(hd.dbc, match.group(1)) # group(1) is the actual id matched, after the prefix
	await hd.ws.send_json({'task': 'show_shopping', 'div_id': hd.payload['resource_id'], 'result': html.show_shopping(result)})

async def _ws_mark_assignment(hd):
	result = await db.mark_assignment(hd.dbc, hd.uuid, int(hd.payload['assignment_id']), bool(hd.payload['checked'])) # group(1) is the actual id matched, after the prefix
	#TODO: return something useful from mark_assignment() and use this to indicate any trouble to user

async def _get_random_url_playlist(hd):
	# Assemble the playlist (we build an entire playlist at once in order to avoid repetition (each song/etc. shows up only once), and because it's very easy to do one DB operation that results in a whole (randomly-ordered) set/list of "hits", rather than asking the DB every time, one song at a time):
	path_map = {
		db.k_subject_ids['History']: 'history/',
		db.k_subject_ids['Science']: 'science/',
 		db.k_subject_ids['English']: 'english/',
		db.k_subject_ids['Latin']: 'latin/',
	}
	new_path_map = {
 		db.k_subject_ids['English']: 'english/',
		db.k_subject_ids['Latin']: 'latin/',
	}
	playlist = []
	for subject, path in path_map.items():
		if hd.spec.subject in (0, subject): # i.e., hd.spec.subject is either "all subjects" or this one
			url = html._aurl(path)
			for cycle in hd.spec.cycles:
				for week in range(hd.spec.first_week, hd.spec.last_week + 1):
					fn = f'c{cycle}w{week}.mp3'
					p_fn = f'c{cycle}w{week}-prompt.mp3'
					ksa = 'static/audio/' # TODO: fix hardcode static path (local/server path... static files may be stored elsewhere in future!)
					if exists(ksa + path + fn):
						if exists(ksa + path + p_fn): 
							playlist.append((url + p_fn, url + fn))
						else:
							playlist.append(url + fn)
	shuffle(playlist)
	result = []
	for each in playlist:
		if type(each) is tuple:
			result.extend(each)
		else:
			result.append(each)

	await hd.ws.send_json({'task': 'set_random_url_playlist', 'playlist': result})

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


async def _send_show_resources_message(hd, programs, grades, subjects):
	if not hd.spec.linear:
		await hd.ws.send_json({
			'task': 'show_resources',
			'content': html.resource_list(hd.spec, await hd.data),
			'spec': json.dumps(hd.spec.asdict()),
			'programs': programs,
			'grades': grades,
			'subjects': subjects,
		})

async def _send_show_arithmetic_message(hd):
	msg = await _make_arithmetic_problem_message(hd)
	msg['task'] = 'show_arithmetic'
	key = 'arithmetic_op'
	msg['content'] = html.arithmetic_practice(
		key = key,
		options = (('+ (Addition)', '+'), ('- (Subtraction)', '-'), ('× (Multiplication)', '×'), ('÷ (Division)', '÷')),
		hint = 'Operation: + - × ÷',
		selected_id = hd.spec.arithmetic_op
	)
	await hd.ws.send_json(msg)
	# Starting a new arithmetic session requires sending the original problem (and content, per above) AND a follow-up problem (immediately), which is cached, ready to swap in as soon as user answers first problem:
	await hd.ws.send_json(await _make_arithmetic_problem_message(hd))

async def _make_arithmetic_problem_message(hd):
	ct = lambda: asyncio.create_task(_practice_fetch_new_problems(hd.dbc, hd.uuid, hd.spec))
	data = await hd.data # at long last!  By now the task 	(which was spun off a whole transaction ago) should be complete... else, this (of course) awaits its completion.  create_task() was called in an earlier transaction
	if hd.spec.arithmetic_op != data.problems[0]['operator']:
		# operator changed; immediately fetch new problems:
		hd.data = ct()
		data = await hd.data # need it immediately!
	assert(data.index < len(data.problems))
	problem = data.problems[data.index]
	data.index += 1 # for next fetch
	if data.index == len(data.problems): # if we're now "to the end"...
		hd.data = ct() # ... fetch the new request now, so that it will be complete, and we'll have a problem ready to go the next time the user answers the current problem....
	return {
		'task': 'arithmetic_problem',
		'assessment_id': problem['assessment_id'],
		'op1': problem['operand1'],
		'operator': problem['operator'],
		'op2': problem['operand2'],
		'answer': problem['answer'],
		#'spec': json.dumps(hd.spec.asdict()), # really need this?!!!  Don't do the work unless we need this client-side
	}


# Other ----------------------------------------------------------------------

async def _set_up_common_view(view, dbc = True, uuid = True, data = True, re_log_in_seconds = None):
	result = U.Struct(rq = view.request, session = await get_session(view.request))
	result.dbc = result.rq.app['db'] if dbc else None # TODO: .cursor()
	result.uuid = result.session.get('uuid') if uuid else None
	result.data = await result.rq.post() if data else None
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

def _set_up_twixt(session, task_name, async_call, spec):
	session['twixt_id'] = twixt_id = str(uuid4())
	twixt = U.Struct(
		task = task_name,
		result = asyncio.create_task(async_call) if async_call else None,
		spec = spec, # need to send spec, itself, as there's no other way for retrieving end (ws_messages function) to get spec!
	)
	g_twixt_work[twixt_id] = twixt
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
			return hr(html.quiz(_ws_url(rq, '/ws_quiz_handler'), db_handler, html_function, rq.host))
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


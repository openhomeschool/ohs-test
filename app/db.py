__author__ = 'J. Michael Caine'
__copyright__ = '2020'
__version__ = '0.1'
__license__ = 'MIT'

import hashlib
import re

from os import urandom

import logging
l = logging.getLogger(__name__)

from . import cdb

# Handlers --------------------------------------------------------------------

_hash = lambda password, salt: hashlib.pbkdf2_hmac('sha256', bytes(password, 'UTF-8'), salt, 100000)

async def add_user(db, username, password, email):
	salt = urandom(32)
	c = await db.cursor() # need cursor because we need lastrowid, only available via cursor
	r = await c.execute('insert into user(username, password, salt, email) values (?, ?, ?, ?)', (username, _hash(password, salt), salt, email))
	user_id = c.lastrowid
	r = await c.execute('insert into user_role(user, role) values (?, 1)', (user_id,)) #TODO: hard-coded to "role #1, student" -- parameterize!
	return user_id

_get_users_limited = lambda limit: ('select * from user limit ?', (limit,))
async def get_users_limited(db, limit):
	c = await db.execute(*_get_users_limited(limit))
	return await c.fetchall()

_find_users = lambda like: ('select * from user where username like ?', ('%' + like + '%',))
async def find_users(db, like):
	c = await db.execute(*_find_users(like))
	return await c.fetchall()

def _prep_where_matches(where_matches):
	'''
	`where_matches` must be a list or tuple of 2-tuple pairs, such as:
		(('username', 'frank'),)
		(('first_name', 'John'), ('last_name', 'Smith'))
		(('id', 5),)
	'''
	wheres, values = list(zip(*where_matches))
	wheres = ' and '.join([i + ' = ?' for i in wheres])
	return wheres, values

async def get_user(db, where_matches):
	'''
	See _prep_where_matches() for `where_matches` spec
	'''
	wheres, values = _prep_where_matches(where_matches)
	c = await db.execute('select * from user where ' + wheres, values)
	return await c.fetchall()


async def authenticate(db, username, password):
	c = await db.execute('select * from user where username = ?', (username,))
	user = await c.fetchone()
	if user and (user['password'] == _hash(password, user['salt'])):
		c = await db.execute('select role.name as role_name from role join user_role on role.id = user_role.role join user on user.id = user_role.user where user.username = ?', (username,))
		roles = await c.fetchall()
		return user['id'], [role['role_name'] for role in roles]
	#else:
	return None, None

# ------------

async def get_question(function, db, payload):
	return await function(db, payload)

exposed = dict()
def expose(func):
	exposed[func.__name__] = func
	return func

@expose
async def get_history_sequence_question(db, payload):
	s_events = cdb.cSqlUtilEvents('event')
	primary = await s_events.get_random_event(db, week_range = (1, 12), date_range = None, exclude_people_groups = True)
	events = await s_events.get_surrounding_events(db, primary, week_range = (1, 12))
	return (primary, events)

@expose
def get_history_geography_question(db, payload):
	pass

@expose
def get_history_detail_question(db, payload):
	pass

@expose
def get_history_submissions_question(db, payload):
	pass

@expose
def get_history_random_question(db, payload):
	pass

@expose
def get_geography_orientation_question(db, payload):
	pass

@expose
def get_geography_map_question(db, payload):
	pass

@expose
async def get_science_grammar_question(db, payload):
	s_resps = cdb.cSqlUtilResponses('science')
	primary = await s_resps.get_random_event(db, week_range = (1, 12), exclude_people_groups = False)
	events = await s_resps.get_surrounding_responses(db, primary, week_range = (1, 12))
	return (primary, events)

@expose
def get_science_submissions_question(db, payload):
	pass

@expose
def get_science_random_question(db, payload):
	pass

@expose
def get_math_facts_question(db, payload):
	pass

@expose
def get_math_grammar_question(db, payload):
	pass

@expose
def get_english_grammar_question(db, payload):
	pass

@expose
def get_quiz_english_vocabulary_question(db, payload):
	pass

@expose
def get_english_random_question(db, payload):
	pass

@expose
def get_latin_grammar_question(db, payload):
	pass

@expose
def get_latin_vocabulary_question(db, payload):
	pass

@expose
def get_latin_translation_question(db, payload):
	pass

@expose
def get_latin_random_question(db, payload):
	pass

@expose
def get_music_note_question(db, payload):
	pass

@expose
def get_music_key_signature_question(db, payload):
	pass

@expose
def get_music_submissions_question(db, payload):
	pass

@expose
def get_music_random_question(db, payload):
	pass


'''
# Unit testing... <fledgling start> -------------------------------------------

def _ut_get_random_event(week_range = None, date_range = None):
	event = db.execute(*s_get_random_event('event', week_range, date_range)).fetchone()
	l.debug('%s (%s)' % (event['name'], event['start']) if event else 'No events!')
	return event

def _ut_get_surrounding_events(event, week_range = None, date_range = None, count = 5):
	c = db.cursor()
	e1 = c.execute(*s_get_keyword_similar_events(event, week_range, date_range, count)).fetchall()
	exids = [e['id'] for e in e1]
	e2 = c.execute(*s_get_temporal_random_events(event, week_range, date_range, count, exids)).fetchall()
	exids.extend([e['id'] for e in e2])
	keyword_similars, temporal_randoms, random_count = _get_surrounding_events(e1, e2, count)
	randoms = []
	exids.append(event['id'])
	for i in range(random_count):
		r = c.execute(*s_get_random_event('event', week_range, date_range, exids)).fetchone()
		if r:
			randoms.append(r)
			exids.append(r['id'])

	l.debug('kws:')
	for event in keyword_similars:
		l.debug(event['name'])
	l.debug('trs:')
	for event in temporal_randoms:
		l.debug(event['name'])
	l.debug('rs:')
	for event in randoms:
		l.debug(event['name'])
'''


'''
"Deferred fetch" example
In this case, the view code executes a fetchone on each:

	async def multi_choice_question(records):
		d = t.div('The question would be here...', cls = 'quiz_question_content')
		with d:
			async with records:
				async for record in records:
					t.div('Option - %s' % record['name'], cls = 'quiz_question_option')
		return d.render()
		
This is the better way to go if there's a chance that the
number of records is more than needed client-side, because
bail-out can occur before all records are fetched, saving
needless fetching.  The controller code looks like this:

	data = await call_map[payload['call']](payload, dbc) # that is: reply = await db.get_history_sequence_question(dbc)
	await ws.send_json({'call': 'content', 'content': await html.multi_choice_question(data)})

Here is the model code:

	_get_history_sequence_question = lambda: ('select * from test1 order by random() limit 5')
	async def get_history_sequence_question(db):
		return await db.execute(_get_history_sequence_question())
'''

# --------

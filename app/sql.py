__author__ = 'J. Michael Caine'
__copyright__ = '2020'
__version__ = '0.1'
__license__ = 'MIT'

import copy
import re
import random
import bcrypt # cf https://security.stackexchange.com/questions/133239/what-is-the-specific-reason-to-prefer-bcrypt-or-pbkdf2-over-sha256-crypt-in-pass
import time

from uuid import uuid4
#OLD user stuff: import hashlib
#OLD user stuff: import re
from datetime import date, timedelta
from dataclasses import dataclass

from . import util
from . import exception

import logging
l = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
'''
Async wrappers
Use like this:
	fetchone(db, get_random_science_records(spec, 1))
	fetchall(db, get_random_event_records(spec, 5))
'''

async def fetchone(db, sql_and_args):
	#TODO: sql_and_args[0] += ' limit 1'
	e = await db.execute(*sql_and_args)
	return await e.fetchone()

async def fetchone_(db, sql, args):
	sql += ' limit 1' # TODO: why do this here, but not in the above fetchone() fn?  Fix.
	e = await db.execute(sql, args)
	return await e.fetchone()

async def fetchall(db, sql_and_args):
	e = await db.execute(*sql_and_args)
	return await e.fetchall()

def prep_where_matches(where_matches):
	'''
	`where_matches` must be a list or tuple of 2-tuple pairs, such as:
		(('username', 'frank'),)
		(('first_name', 'John'), ('last_name', 'Smith'))
		(('id', 5),)
	The results for each of the above would be:
		('username = ?', ('frank',))
		('first_name = ? and last_name = ?', ('John', 'Smith')
		('id = ?', (5,))
	You could put any of these into a SQL call, like:
		db.execute('select * from foo where %s' % wheres, values)
	Where `wheres' and 'values' are the two returns 
	'''
	wheres, values = list(zip(*where_matches))
	wheres = ' and '.join([i + ' = ?' for i in wheres])
	return wheres, values


# -----------------------------------------------------------------------------
'''
Main database functions
Expectation / pattern: these typically return 2-tuples: (sql, arg_list)
'''

# User stuff ------------------------------------------------------------------

async def _login(dbc, user_id):
	uuid = str(uuid4())
	ts = time.time()
	await dbc.execute('insert into user_login ("user", uuid, timestamp) values (?, ?, ?)', (user_id, uuid, ts))
	await dbc.commit()
	return (uuid, ts)

async def login(dbc, username, password):
	r = await fetchone(dbc, ('select id, password from "user" where username = ?', (username,)))
	if r and (password == None or bcrypt.checkpw(password.encode(), r['password'])):
		return await _login(dbc, r['id'])
	#else:
	return None

async def forget_login(dbc, uuid):
	await dbc.execute('delete from user_login where uuid = ?', (uuid,))
	await dbc.commit()

async def authenticated(dbc, uuid):
	return await bool(fetchone(dbc, ('select id from user_login where uuid = ?', (uuid,))))

async def authorized(dbc, uuid, roles):
	users_roles = await fetchall(dbc, ('select role.name from role join user_role on role.id = user_role.role join user on user.id = user_role.user join user_login on user.id = user_login.user where user_login.uuid = ?', (uuid,)))
	return bool(set([role['name'] for role in users_roles]).intersection(roles))

async def verify_password__(dbc, uuid, password): # TODO: DEPRECATE; don't really need this, after all
	r = await fetchone(dbc, ('select password from "user" join user_login on user_login.user = user.id where uuid = ?', (uuid,)))
	if r and bcrypt.checkpw(password.encode(), r['password']):
		return True
	return False

async def create_user(dbc, username, password, person_id):
	pwcrypt = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
	await dbc.execute('insert into "user" (username, password, person) values (?, ?, ?)', [username, pwcrypt, person_id]) # 'verified' defaults to 0 per db setup
	await dbc.commit()

async def add_role(dbc, username, role):
	await add_roles(dbc, username, (role,))

async def add_roles(dbc, username, roles):
	all_roles = await fetchall(dbc, ('select id, name from role', ()))
	user = await fetchone(dbc, ('select id from "user" where username = ?', (username,)))
	roles = [(user['id'], role['id']) for role in all_roles if role['name'] in roles]
	await add_role_ids(dbc, roles)

async def add_role_id(dbc, role_id, user_id = None):
	return add_role_ids(dbc, (role_id,), user_id)

async def add_role_ids(dbc, role_ids, user_id = None):
	'''
	`role_ids` can either be a list of 2-tuples, each as (user_id, role_id)
	(Note that user_id might be the same in many tuples, if you're adding many
	roles for the same user), or else role_ids can be a plain list (or tuple)
	of role_ids, and the list-of-tuples will be built for you using the provided
	`user_id`.
	'''
	if user_id:
		role_ids = [(user_id, role_id) for role_id in role_ids]
	#else role_ids is already a list of (user_id, role_id) tuples
	l.debug('adding roles: %s', role_ids)
	await dbc.executemany('insert into user_role ("user", role) values (?, ?)', role_ids)
	await dbc.commit()

async def verify_new_user(dbc, username):
	await dbc.execute('update "user" set verified = 1 where username = ?', [username,])

async def delete_user(dbc, username):
	await dbc.execute('delete from "user" where username = ?', [username,])
	await dbc.commit()

async def disable_user(dbc, username):
	await dbc.execute('update "user" set password = NULL where username = ?', [username,]) # can't login with null pw
	await dbc.commit()
	
async def reset_user_password(dbc, uuid, new_password):
	pwcrypt = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt())
	result = await dbc.execute('update "user" set password = ? from user_login where user.id = user_login.user and uuid = ?', (pwcrypt, uuid))
	await dbc.commit()
	assert(result.rowcount < 2)
	return (result.rowcount == 1)

async def get_switch_user_ids(dbc, uuid):
	return await fetchall(dbc, ('select "user", without_password from user_switch_allow join "user" on user.id = user_switch_allow.from_user join user_login on user.id = user_login.user where user_login.uuid = ?', (uuid,)))
	
async def get_usernames(dbc, user_ids):
	return await fetchall(dbc, ('select id, username from "user" where id in (?)', (user_ids,)))

async def get_username(dbc, uuid):
	r = await fetchone(dbc, ('select username from "user" join user_login on user_login.user = user.id where user_login.uuid = ?', (uuid,)))
	if r:
		return r['username']
	#else:
	return None

async def get_user_id(dbc, username):
	r = await fetchone(dbc, ('select id from "user" where username = ?', (username,)))
	if r:
		return r['id']
	#else:
	return None

async def add_user_switch_allows(dbc, from_user_ids, user_id = None, without_password = True):
	'''
	`from_user_ids` can either be a list of 2-tuples, each as
		(user_id, from_user(id), without_password))
	(Note that user_id might be the same in many tuples, if you're adding many
	from_user_ids for the same user), or else from_user_ids can be a plain list (or tuple)
	of user ids, and the list-of-tuples will be built for you using the provided
	`user_id` and `without_password`.
	'''
	if user_id:
		from_user_ids = [(user_id, from_user_id, without_password) for from_user_id in from_user_ids]
	#else from_user_ids is already a list of (user_id, from_user_id, without_password) tuples
	l.debug('adding from_user_ids: %s', from_user_ids)
	await dbc.executemany('insert into user_switch_allow ("user", from_user, without_password) values (?, ?, ?)', from_user_ids)
	await dbc.commit()

async def get_switch_users(dbc, uuid):
	return await fetchall(dbc, ('select switch_user.username, user_switch_allow.without_password from user_switch_allow join "user" on user.id = user_switch_allow.from_user join "user" as switch_user on switch_user.id = user_switch_allow.user join user_login on user_login.user = user.id where user_login.uuid = ?', (uuid,)))

async def switch_user(dbc, from_uuid, to_username):
	r = await fetchone(dbc, ('select switch_user.id as new_user_id, without_password from user_switch_allow join "user" on user.id = user_switch_allow.from_user join user_login on user.id = user_login.user join "user" as switch_user on switch_user.id = user_switch_allow.user where user_login.uuid = ? and switch_user.username = ?', (from_uuid, to_username)))
	if r:
		if r['without_password']:
			await forget_login(dbc, from_uuid)
			return await _login(dbc, r['new_user_id'])
		else:
			return None # to signal required login (i.e., send to login page)
	#else:
	raise exception.InvalidSwitch()

async def get_user_settings(dbc, uuid):
	return await fetchone(dbc, ('select * from user_settings join user on user_settings.user = user.id join user_login on user.id = user_login.user where user_login.uuid = ?', (uuid,)))

# -----------------------------------------------------------------------------
# OLD user stuff

_hash = lambda password, salt: hashlib.pbkdf2_hmac('sha256', bytes(password, 'UTF-8'), salt, 100000)

async def add_user_DEPRECATED(db, username, password, email):
	salt = urandom(32)
	c = await db.cursor() # need cursor because we need lastrowid, only available via cursor
	r = await c.execute('insert into user (username, password, salt, email) values (?, ?, ?, ?)', (username, _hash(password, salt), salt, email))
	user_id = c.lastrowid
	r = await c.execute('insert into user_role (user, role) values (?, 1)', (user_id,)) #TODO: hard-coded to "role #1, student" -- parameterize!
	return user_id

_get_users_limited = lambda limit: ('select * from user limit ?', (limit,))
async def get_users_limited_PORT(db, limit):
	c = await db.execute(*_get_users_limited(limit))
	return await c.fetchall()

_find_users = lambda like: ('select * from user where username like ?', ('%' + like + '%',))
async def find_users_PORT(db, like):
	c = await db.execute(*_find_users(like))
	return await c.fetchall()

async def get_user_DEPRECATED(db, where_matches):
	'''
	See _prep_where_matches() for `where_matches` spec
	'''
	wheres, values = _prep_where_matches(where_matches)
	c = await db.execute('select * from user where ' + wheres, values)
	return await c.fetchall()


async def authenticate_DEPRECATED(db, username, password):
	c = await db.execute('select * from user where username = ?', (username,))
	user = await c.fetchone()
	if user and (user['password'] == _hash(password, user['salt'])):
		c = await db.execute('select role.name as role_name from role join user_role on role.id = user_role.role join user on user.id = user_role.user where user.username = ?', (username,))
		roles = await c.fetchall()
		return user['id'], [role['role_name'] for role in roles]
	#else:
	return None, None


# ----------------------------------------------------------

def get_random_records(spec, count, exclude_ids = None):
	'''
	Get `count` random records from the spec table using `spec` object.
	`spec` object expected to be a English_Vocabulary_QT object.
	Any records with ids in `exclude_ids` are excluded.
	'''
	joins, wheres, args = [], [], []
	_filter_cycle_week_range(spec, joins, wheres, args)
	_filter_exclude_ids(spec, wheres, exclude_ids)
	return _random_select(spec, joins, wheres, count), args


def get_random_event_records(spec, count, exclude_ids = None):
	'''
	Get `count` random records from the spec table using `spec` object
	(Question_Transaction) object, excluding any records with ids in `exclude_ids`.
	'''
	assert(spec.table == 'event') # sanity check
	joins, wheres, args = [], [], []
	if spec.exclude_people_groups:
		wheres.append(f'{spec.table}.people_group is not true')
	_filter_cycle_week_range(spec, joins, wheres, args)
	_filter_date_range(spec, wheres, args)
	_filter_exclude_ids(spec, wheres, exclude_ids)
	result = _random_select(spec, joins, wheres, count)
	return result, args


async def get_surrounding_event_records(spec, count, event):
	'''
	Get `count` random records from the event table using `spec`
	(Question_Transaction) object (excluding spec.question['id'])
	In particular, an assortment of keyword-similar events and
	temporally-proximal events, supplemented with purely random
	events as necessary to fill up to `count`.
	'''
	joins, wheres, args = [], [], []
	if spec.exclude_people_groups:
		wheres.append(f'{spec.table}.people_group is not true')
	_filter_cycle_week_range(spec, joins, wheres, args)
	_filter_date_range(spec, wheres, args)

	# Get keyword-similar events:
	exids = [event['id'],]
	keyword_similars = await fetchall(spec.db, (_get_keyword_similar_events(spec, count, event, exids, joins, wheres), args))
	exids.extend([e['id'] for e in keyword_similars]) # ids to exclude from future search results; we only need any given event once
	# And temporally-random ("proximal") events:
	temporal_randoms = await fetchall(spec.db, (_get_temporal_random_events(spec, count, event, exids, joins, wheres), args))
	exids.extend([e['id'] for e in temporal_randoms]) # ids to exclude from future search results; we only need any given event once

	# Now gather them proportionately; note that keyword_similars and temporal_randoms are already randomly-sorted lists:
	keyword_similar_count = min(round(count * 2 / 5), len(keyword_similars)) # limit the keyword records to two-fifths of `count`
	temporal_random_count = min(round(count * 2 / 5), len(temporal_randoms)) # limit the temporal/proximity records to two-fifth of `count`
	# One or two should be anachronistic and/or truly "unrelated":
	total_random_count = count - (keyword_similar_count + temporal_random_count)

	# Finally, finish filling the set with totally random events:
	randoms = await fetchall(spec.db, get_random_event_records(spec, total_random_count, exids))
	# Put them all together and sort chronologically:
	result = keyword_similars[:keyword_similar_count] + temporal_randoms[:temporal_random_count] + randoms
	result.sort(key = lambda e: e['start'] if e['start'] else e['fake_start_date'])
	
	# Calculate answer - first option with a start date greater than (target) event's:
	answer = 0 # default: "first" in sequence
	main_event_start = event['start'] if event['start'] else event['fake_start_date']
	for option in result:
		option_start = option['start'] if option['start'] else option['fake_start_date']
		if main_event_start > option_start: # this will happen every event until we've gone too far
			answer = option['id'] # this won't be accurate until we've gone too far and 'break', below
		else:
			break # the previous hit was the right one

	l.debug('TARGET EVENT: %s (%s)' % (event['name'], event['id']))
	l.debug('SURROUNDING EVENTS: %s' % ['%s (%s), ' % (e['name'], e['id']) for e in result])
	l.debug('ANSWER: %d' % answer)
	return result, answer







async def _fetch_new_fact(dbc, spec):
	joins = [f"{spec.assessment_join_table} on {spec.assessment_join_table}.fact = {spec.fact_table}.id",
				f"assessment on {spec.assessment_join_table}.assessment = assessment.id", ]
	order_by_desc = ', '.join([f'{field} desc' for field in spec.order_by_fields])
	order_by_asc = ', '.join(spec.order_by_fields)
	
	last = await fetchone_(dbc, f"select {spec.fact_table}.* from {spec.fact_table} " + _join(joins) + _where(spec.wheres + ["assessment.student = ?", ]) + f" order by {order_by_desc} ", [spec.student_id, ])
	if not last: # Not a single record that matches spec; therefore, fetch a first (use order_by in ascent):
		return await fetchone_(dbc, f"select {spec.fact_table}.* from {spec.fact_table} " + _where(spec.wheres) + f" order by {order_by_asc} ", [])
	#else, get next fact "after" fetched one:
	new_fact = await fetchone_(dbc, f"select {spec.fact_table}.* from {spec.fact_table} " 
				+ _where(spec.wheres + ["arithmetic_fact.operand1 >= ?", "arithmetic_fact.operand2 > ?"]) + f" order by {order_by_asc} ", [last['operand1'], last['operand2']])
	return new_fact
	
def _add_assessment(dbc, spec):
	cursor = dbc.cursor()
	cursor.execute("insert into assessment (speed_ms, correct, student) values (?, ?, ?)", [spec.speed_ms, spec.correct, spec.student])
	cursor.execute(f"insert into {spec.assessment_join_table} (fact, assessment) values (?, ?)", [spec.fact_id, cursor.lastrowid])
	dbc.commit()
	
"""
spec = util.Struct(
  assessment_join_table = 'arithmetic_fact_assessments',
  fact_table = 'arithmetic_fact',
  wheres = [f"arithmetic_fact.operator = '+'", ],
  order_by_fields = ['arithmetic_fact.operand1', 'arithmetic_fact.operand2']
)
spec.student_id = 2

after sql._fetch_new_fact(dbc, spec) ...
>>> result['operand1']
0
>>> result['operand2']
1
>>> result['operator']
'+'
>>> result['answer']
1

spec2 = util.Struct(
	assessment_join_table = 'arithmetic_fact_assessments',
	fact_id = 146, # = result['id'] from _fetch_new_fact() or like
	speed_ms = 5,
	correct = 1,
	student = 2,
)
sql._add_assessment(dbc, spec2) # results in new records in assessment and arithmetic_fact_assessments


async def _fetch_new(dbc, spec):
	joins = [f"{spec.assessment_join_table} on {spec.assessment_join_table}.fact = {spec.fact_table}.id",
				f"assessment on {spec.assessment_join_table}.assessment = assessment.id", ]
	wheres = [f"student = {spec.student_id}", ]
	
	return await fetchone(dbc, (f"select {spec.fact_table}.* from {spec.fact_table} " + _join(joins) + _where(wheres) + f" order by {spec.order_by} ", args))


spec.assessment_join_table = 'arithmetic_fact_assessments'
spec.fact_table = 'arithmetic_fact'
spec.wheres = ["arithmetic_fact.operator = '+'", ] # TODO: add random operator support
# For progressive or 'new' - find the "highest" record attached to the student, so far:
spec.order_by_fields = ['arithmetic_fact.operand1', 'arithmetic_fact.operand2']

#_fetch_personal_challenger
#_fetch_typical_challenger
#_fetch_mastered


async def get_arithmetic_facts(dbc, spec):
	if spec.progressive:
		
	joins, wheres, args = [f"general_title on {resource_spec.table}.title = general_title.id", f"download on {resource_spec.table}.path = download.id"], [], []
	_filter_cycle_week_range(spec, joins, wheres, args, False)
	
	return await fetchall(dbc, (f"select {resource_spec.table}.*, general_title.title as real_title, download.filename_suffix, download.path as download_path, cw.cycle as cycle, cw.week as week from {resource_spec.table} "
											+ _join(joins) + _where(wheres) + f" order by cw.cycle, cw.week, general_title.seq, {resource_spec.table}.seq", args))

	await fetchall(spec.db, 
	return await sql.get_arithmetic_fact(dbc, spec)
"""






# ---------------------------------------------------
# Resources

#TODO: considering renaming "resources" to "lode".... (and using other 4-letter terms: quiz, test,  case (study), gist (view), pith (probe)


k_subject_ids = { # IDs from DB table, mapped to handler names TODO: just create from DB table (and cache, so we don't have to constantly look up)!
	'Timeline': 1,
	'History': 2,
	'Geography': 3,
	'Math': 4,
	'Science': 5,
	'English': 6,
	'Latin': 7,
	'Literature': 8,
	'Poetry': 9,
	'Computer': 10,
	'Spanish': 11,
	'Logic': 12,
	'Shakespeare': 13,
}

@dataclass
class SS: # Subject Specification
	subject_title: str
	resource_specs: list # of RS objects

@dataclass
class RS: # Resource Specification
	getter: object #function
	subject_title: str
	handler: str
	table: str
	search_fields: tuple
	deep_search_fields: tuple = None
	extra_joins: tuple = None
	order_by: str = 'cw.cycle, cw.week'
	triple: bool = False
	def triplify(self):
		tripled = copy.copy(self)
		tripled.triple = True
		return tripled

@dataclass
class SR: # Subject Result
	subject_title: str
	subresults: list # of RR objects

@dataclass
class RR: # Resource Result
	handler: str
	records: list = None


async def _get_general_grammar(dbc, spec, resource_spec):
	if spec.shop:
		pass # TODO: put top-level comments here!
	spec.table = resource_spec.table # some of the following functions want table in spec (they don't get passed resource_spec)
	joins, wheres, args = [f"general_title on {resource_spec.table}.title = general_title.id", f"download on {resource_spec.table}.path = download.id"], [], []
	_filter_cycle_week_range(spec, joins, wheres, args, False)
	
	return await fetchall(dbc, (f"select {resource_spec.table}.*, general_title.title as real_title, download.filename_suffix, download.path as download_path, cw.cycle as cycle, cw.week as week from {resource_spec.table} "
											+ _join(joins) + _where(wheres) + f" order by cw.cycle, cw.week, general_title.seq, {resource_spec.table}.seq", args))


async def _get_geography_grammar(dbc, spec, resource_spec):
	if spec.shop:
		pass # TODO: put top-level comments here!
	spec.table = resource_spec.table # some of the following functions want table in spec (they don't get passed resource_spec)
	joins, wheres, args = [], [f"{resource_spec.table}.bonus is not true"], []
	_filter_cycle_week_range(spec, joins, wheres, args, False)
	
	return await fetchall(dbc, (f"select * from {resource_spec.table} " + _join(joins) + _where(wheres) + f" order by cw.cycle, cw.week, seq", args))


async def _get_grammar_resources(dbc, spec, resource_spec):
	if spec.shop:
		return [] # We don't want grammar while shopping
	#else...
	spec.table = resource_spec.table # some of the following functions want table in spec (they don't get passed resource_spec)
	joins, wheres, args = [], [], []
	if resource_spec.extra_joins:
		joins.extend(resource_spec.extra_joins)
	_filter_cycle_week_range(spec, joins, wheres, args, broaden = _triplify if resource_spec.triple else _no_broaden)
	if spec.search and resource_spec.search_fields:
		or_wheres = []
		for field in resource_spec.search_fields:
			or_wheres.append(f'{field} like ?')
			args.append('%' + spec.search + '%')
		wheres.append(_or_wheres(or_wheres))

	return await fetchall(dbc, (f"select * from {resource_spec.table} " + _join(joins) + _where(wheres) + f" order by {resource_spec.order_by}", args))

async def _get_exre_resources(dbc, spec, resource_spec):
	spec.table = resource_spec.table # i.e., resource_use... not really a "subject"-specific table like in grammar, but, none-the-less, serves as the defined pivot table for the likes of _filter_cycle_week
	joins = [
		f'resource on {spec.table}.resource = resource.id',
		#'subject on {spec.table}.subject = subject.id', # really needed?!!!
		f'grade_resource_use on grade_resource_use.resource_use = {spec.table}.id',
	]
	if resource_spec.extra_joins:
		joins.extend(resource_spec.extra_joins)
	wheres, args = [f'{spec.table}.subject = ?',], [k_subject_ids[resource_spec.subject_title], ]
	_filter_cycle_week_range(spec, joins, wheres, args, True)
	_filter_program(spec, joins, wheres, args) # TODO: change to specific grade-filtering (or variably...?  NO: **add** grade filtering; then, one can see the whole program, which is united, but drill in (e.g., by virtue of being logged in as a student) to the specific grade treatment; also note that resource_use.program is NOT redundant, here, with grade_resource_use.grade_first (or grade_last) via grade_program table beause that table may have two programs associated with a grade level, and we need to specify the program to which the resource_use really belongs
	if spec.grade != 0:
		wheres.append('grade_resource_use.grade_first <= ? and grade_resource_use.grade_last >= ?')
		args.extend((spec.grade, spec.grade))
	if spec.shop:
		group_by = f' group by {spec.table}.resource' # separate records spanning several weeks are not useful for shopping - just want the fact that there is a resource_use record, indicating that a resource is needed, so that a shopper can shop for the resource
		detail_fields = f'sum(case when grade_resource_use.optional = 1 then 1 else 0 end) as optional, sum(case when grade_resource_use.optional = 0 then 1 else 0 end) as required'
	else:
		group_by = ''
		detail_fields = 'pages, chapters, instructions, grade_resource_use.optional, (case when grade_resource_use.optional = 0 then 1 else 0 end) as required'
	return await fetchall(dbc, (f'select resource.id as resource_id, resource.name as resource_name, cw.cycle as cycle, cw.week as week, grade_resource_use.grade_first, grade_resource_use.grade_last, {detail_fields} from {spec.table}' \
		+ _join(joins) + _where(wheres) + group_by + f' order by {resource_spec.order_by}', args))

async def _get_assignments(dbc, spec, resource_spec):
	spec.table = resource_spec.table # i.e., assignment... not really a "subject"-specific table like in grammar, but, none-the-less, serves as the defined pivot table for the likes of _filter_cycle_week
	joins = [f'resource on {spec.table}.resource = resource.id', ]
	if resource_spec.extra_joins:
		joins.extend(resource_spec.extra_joins)
	wheres, args = [f'{spec.table}.subject = ?',], [k_subject_ids[resource_spec.subject_title], ]
	_filter_cycle_week_range(spec, joins, wheres, args, True)
	_filter_program(spec, joins, wheres, args) # TODO: change to specific grade-filtering (or variably...?  NO: **add** grade filtering; then, one can see the whole program, which is united, but drill in (e.g., by virtue of being logged in as a student) to the specific grade treatment; also note that resource_use.program is NOT redundant, here, with grade_resource_use.grade_first (or grade_last) via grade_program table beause that table may have two programs associated with a grade level, and we need to specify the program to which the resource_use really belongs
	if spec.grade != 0:
		wheres.append('(assignment.grade_first is NULL or assignment.grade_first <= ?) and (assignment.grade_last is NULL or assignment.grade_last >= ?)')
		args.extend((spec.grade, spec.grade))

	if spec.shop:
		# If shopping, we don't actually want all the assignment records, we only want the collection of resources to which those assignments collectively refer.  We still need to query the assignment records, to get this information, as there's no better way to know that a resource needs to be bought than to know that an assignment has referenced it.
		group_by = f' group by {spec.table}.resource' # separate records spanning several weeks are not useful for shopping - just want the fact that there is a resource_use record, indicating that a resource is needed, so that a shopper can shop for the resource
		detail_fields = f' sum(case when {spec.table}.optional = 0 then 1 else 0 end) as required, sum({spec.table}.grade_first) as grade_first, sum({spec.table}.grade_last) as grade_last'
	else:
		# Get the motherload...
		group_by = ''
		joins.append(f'instructions on {spec.table}.instruction = instructions.id')
		detail_fields = 'instructions.text as instruction, program.grade_first as program_grade_first, program.grade_last as program_grade_last, assignment.grade_first, assignment.grade_last, pages, chapters, items, skips, optional, "order"'

	return await fetchall(dbc, (f'select resource.id as resource_id, resource.name as resource_name, cw.cycle as cycle, cw.week as week, {detail_fields} from {spec.table}' \
		+ _join(joins) + _where(wheres) + group_by + f' order by {resource_spec.order_by}', args))
	
async def _get_assignments_DEPRECATE(dbc, spec, resource_spec):
	if spec.shop:
		return [] # We don't want assignments while shopping
	#else...
	spec.table = resource_spec.table # i.e., assignment... not really a "subject"-specific table like in grammar, but, none-the-less, serves as the defined pivot table for the likes of _filter_cycle_week
	joins = resource_spec.extra_joins if resource_spec.extra_joins else []
	wheres, args = ['subject = ?', 'program = ?'], [k_subject_ids[resource_spec.subject_title], spec.program]
	_filter_cycle_week_range(spec, joins, wheres, args, False)

	return await fetchall(dbc, (f'select * from {spec.table}' + _join(joins) + _where(wheres) + ' order by subject, cw.cycle, cw.week, "order"', args))


async def _get_resources(dbc, spec, resource_specs):
	# Returns list of Resource_Result objects; one per subject, in the order specified in resource_specs
	result = []
	try: split_spec_subject_ids = [int(x) for x in str(spec.subject).split(',')]
	except: split_spec_subject_ids = ()
	for ss in resource_specs:
		subject_id = k_subject_ids.get(ss.subject_title, 0)
		if spec.subject == 0 or spec.subject == subject_id or subject_id in split_spec_subject_ids:
			rrs = []
			for rs in ss.resource_specs:
				rr = RR(rs.handler, await rs.getter(dbc, spec, rs))
				if rr.records:
					rrs.append(rr)
			result.append(SR(ss.subject_title, rrs))
	return result


k_general_grammar_rs = RS(_get_general_grammar, 'General', 'general', 'general', ())
k_timeline_grammar_rs = RS(_get_grammar_resources, 'Timeline', 'timeline', 'event', ('name', 'keywords'), ('primary_sentence', 'secondary_sentence'), None, 'cw.cycle, cw.week, event.seq')
k_history_grammar_rs = RS(_get_grammar_resources, 'History', 'history_grammar', 'history', ('name', 'keywords', 'primary_sentence'), ('secondary_sentence',), ('event on history.event = event.id',))
k_geography_grammar_rs = RS(_get_geography_grammar, 'Geography', 'geography', 'location', ())
k_science_grammar_rs = RS(_get_grammar_resources, 'Science', 'science_grammar', 'science', ('prompt', 'answer'), ('note',))
k_multiplication_fact_grammar_rs = RS(_get_grammar_resources, 'Math', 'multiplication_facts', 'multiplication_facts', ('operand1', 'products'),)
k_math_vocabulary_rs = RS(_get_grammar_resources, 'Math', 'math_vocabulary', 'math_vocabulary', ('word', 'equivalent'), (), None, 'cw.cycle, cw.week, position')
k_english_vocabulary_rs = RS(_get_grammar_resources, 'English', 'english_vocabulary', 'vocabulary', ('word', 'definition'), ('root',), None, 'cw.cycle, cw.week, position')
k_english_grammar_rs = RS(_get_grammar_resources, 'English', 'english_grammar', 'english_grammar_example', ('prompt_prefix', 'prompt', 'answer'), ('example',), ('english_grammar_reference on english_grammar_example.english_grammar_reference = english_grammar_reference.id',))
k_latin_vocabulary_rs = RS(_get_grammar_resources, 'Latin', 'latin_vocabulary', 'latin_vocabulary', ('word', 'translation'), None, None, 'cw.cycle, cw.week, position')
#k_latin_grammar_rs = RS(_get_grammar_resources, 'Latin', 'latin_grammar', 'latin', ('name', 'pattern'), ('example',))
k_latin_grammar_rs = RS(_get_grammar_resources, 'Latin', 'latin_grammar', 'latin_grammar_example', ('name', 'pattern'), ('worked', 'translated'), ('latin_grammar_reference on latin_grammar_example.latin_grammar_reference = latin_grammar_reference.id',))

k_grammar_resources = [
	SS('Timeline', (k_timeline_grammar_rs, )),
	SS('History', (k_history_grammar_rs, )),
	SS('Geography', (k_geography_grammar_rs, )),
	SS('Math', (k_multiplication_fact_grammar_rs, k_math_vocabulary_rs )),
	SS('Science', (k_science_grammar_rs, )),
	SS('English', (k_english_grammar_rs, k_english_vocabulary_rs, )),
	SS('Latin', (k_latin_grammar_rs, k_latin_vocabulary_rs, )),
	SS('Extra', (k_general_grammar_rs, )),
]


_make_exre_resource_spec = lambda subject_title, handler: RS(_get_exre_resources, subject_title, handler, 'resource_use', ('resource.name',), ('resource.note',), order_by = 'cw.cycle, cw.week, resource_use.optional, resource_name')

k_history_exre_rs = _make_exre_resource_spec('History', 'history_resources')
# Geog?
k_science_exre_rs = _make_exre_resource_spec('Science', 'science_resources')
k_literature_exre_rs = _make_exre_resource_spec('Literature', 'literature_resources')
k_poetry_exre_rs = _make_exre_resource_spec('Poetry', 'poetry_resources')
k_computer_exre_rs = _make_exre_resource_spec('Computer', 'computer_resources')
k_spanish_exre_rs = _make_exre_resource_spec('Spanish', 'spanish_resources')
k_logic_exre_rs = _make_exre_resource_spec('Logic', 'logic_resources')
k_shakespeare_exre_rs = _make_exre_resource_spec('Shakespeare', 'shakespeare_resources')
k_math_exre_rs = _make_exre_resource_spec('Math', 'math_resources')
k_latin_exre_rs = _make_exre_resource_spec('Latin', 'latin_resources')



_make_assignment_spec = lambda subject_title, handler: RS(_get_assignments, subject_title, handler, 'assignment', ('instruction', ), order_by = 'cw.cycle, cw.week, "order", resource, assignment.grade_first')

k_history_assignment_rs = _make_assignment_spec('History', 'history_assignments')
k_literature_assignment_rs = _make_assignment_spec('Literature', 'literature_assignments')
k_english_assignment_rs = _make_assignment_spec('English', 'english_assignments')
k_science_assignment_rs = _make_assignment_spec('Science', 'science_assignments')
k_poetry_assignment_rs = _make_assignment_spec('Poetry', 'poetry_assignments')
k_computer_assignment_rs = _make_assignment_spec('Computer', 'computer_assignments')
k_spanish_assignment_rs = _make_assignment_spec('Spanish', 'spanish_assignments')
k_logic_assignment_rs = _make_assignment_spec('Logic', 'logic_assignments')
k_shakespeare_assignment_rs = _make_assignment_spec('Shakespeare', 'shakespeare_assignments')
k_math_assignment_rs = _make_assignment_spec('Math', 'math_assignments')
k_latin_assignment_rs = _make_assignment_spec('Latin', 'latin_assignments')

k_middle_resources = [
	SS('Timeline', (k_timeline_grammar_rs, )),
	SS('History', (k_history_assignment_rs, k_history_grammar_rs, )),
	SS('Geography', (k_geography_grammar_rs, )),
	SS('Math', (k_multiplication_fact_grammar_rs, k_math_vocabulary_rs )),
	SS('Science', (k_science_grammar_rs, )),
	SS('English', (k_english_vocabulary_rs, k_english_grammar_rs, )),
	SS('Latin', (k_latin_vocabulary_rs, k_latin_grammar_rs, )),
	SS('Extra', (k_general_grammar_rs, )),
]

k_middle_assignments = [
	SS('History', (k_history_assignment_rs, )),
	SS('Logic', (k_logic_assignment_rs, )),
	SS('Literature', (k_literature_assignment_rs, )),
	SS('English', (k_english_assignment_rs, )),
]

k_high1_resources = [
	SS('History', (k_history_assignment_rs, k_history_grammar_rs.triplify(), k_timeline_grammar_rs.triplify(), )), # TODO: add geography?
	SS('Science', (k_science_assignment_rs, k_science_grammar_rs, )),
	SS('Literature', (k_literature_assignment_rs, k_english_vocabulary_rs, )),
	SS('Math', (k_math_assignment_rs, )),
	SS('Poetry', (k_poetry_assignment_rs, )),
	SS('Computer', (k_computer_assignment_rs, )),
	SS('Spanish', (k_spanish_assignment_rs, )),
	SS('Logic', (k_logic_assignment_rs, )),
	SS('Shakespeare', (k_shakespeare_assignment_rs, )),
	SS('Latin', (k_latin_assignment_rs, k_latin_vocabulary_rs, k_latin_grammar_rs, )),
]

k_high1_assignments = [
	SS('History', (k_history_assignment_rs, )),
	SS('Science', (k_science_assignment_rs, )),
	SS('Literature', (k_literature_assignment_rs, )),
	SS('Math', (k_math_assignment_rs, )),
	SS('Poetry', (k_poetry_assignment_rs, )),
	SS('Computer', (k_computer_assignment_rs, )),
	SS('Spanish', (k_spanish_assignment_rs, )),
	SS('Logic', (k_logic_assignment_rs, )),
	SS('Shakespeare', (k_shakespeare_assignment_rs, )),
	SS('Latin', (k_latin_assignment_rs, )),
]


async def get_grammar_resources(dbc, spec):
	return await _get_resources(dbc, spec, k_grammar_resources)

async def get_middle_resources(dbc, spec):
	resources = k_middle_resources if spec.grammar_supplement else k_middle_assignments
	return await _get_resources(dbc, spec, resources)

async def get_high1_resources(dbc, spec):
	resources = k_high1_resources if spec.grammar_supplement else k_high1_assignments
	return await _get_resources(dbc, spec, resources)

async def get_external_resource_detail(id):
	joins = _external_resource_joins + [
		'resource_acquisition on resource_acquisition.resource = resource.id',
		'resource_type on resource_acquisition.type = resource_type.id',
		'resource_source on resource_acquisition.source = resource_source.id',
	]
	return await fetchone(spec.db, ('select resource.note, resource_acquisition.note as acquisition_note, resource_type.name as resource_type_name, resource_source.name as resource_source_name, resource_source.logo as resource_source_logo, resource_acquisition.url, from resource_use' \
		+ _join(joins) + ' where resource_use.id = ? order by subject_name, optional, resource_name, acquisition_note, resource.note', (id,)))

async def get_shopping_links(dbc, resource_id):
	return await fetchall(dbc, ('select *, resource_type.name as type_name, resource_source.name as source_name, resource_source.logo as source_logo, resource.note as resource_note from resource_acquisition join resource_type on resource_acquisition.type = resource_type.id join resource_source on resource_acquisition.source = resource_source.id join resource on resource_acquisition.resource = resource.id where resource.id = ? order by resource_acquisition.source', (resource_id, )))

async def get_detail(dbc, key):
	for table in ('event', 'science', ): # TODO: the rest of the tables with a qr_code field...
		result = await fetchone(dbc, (await _get_detail_sql_start(table) + f'''
			join qr_key on {table}.qr_key = qr_key.id
			join cycle_week as cw on {table}.cw = cw.id
			where qr_key.key = ?''', (key,)))
		if result:
			details = await _get_detail(dbc, table, result['id'])
			signs = await _get_sign_language_detail(dbc, table, result['id'])
			return (table, result, details, signs)
		#else continue trying other tables
	#else return None

async def get_detail_by_id(dbc, table, id):
	result = await fetchone(dbc, (await _get_detail_sql_start(table) + f'''
		join cycle_week as cw on {table}.cw = cw.id
		where {table}.id = ?''', (id,)))
	if result:
		details = await _get_detail(dbc, table, id)
		signs = await _get_sign_language_detail(dbc, table, result['id'])
		return (result, details, signs)
	#else return None

async def _get_detail_sql_start(table):
	if table == 'event': # event records expect joined location detail; should probably separate this off more elegantly... at least like _get_sign_language_detail...?
		return f'select {table}.*, location.name as location, cw.cycle, cw.week from {table} join location on {table}.region = location.id '
	else:
		return f'select {table}.*, cw.cycle, cw.week from {table} '

async def _get_detail(dbc, table, id):
	return await fetchall(dbc, (f'''
		select detail.*, detail_title.title as detail_title from detail
		join detail_title on detail.title = detail_title.id
		join {table}_detail on {table}_detail.detail = detail.id
		join {table} on {table}.id = {table}_detail.{table}
		where {table}.id = ?
		order by detail_title.sequence, detail.sequence
		''', (id,)))

async def _get_sign_language_detail(dbc, table, id):
	return await fetchall(dbc, (f'''
		select {table}_sign_language.* from {table}_sign_language
		join {table} on {table}.id = {table}_sign_language.{table}
		where {table}.id = ?
		order by {table}_sign_language.sequence
		''', (id,)))


async def get_random_audio_url_DEPRECATED(dbc, spec):
	async def fetch(**args):
		args['rat'] = spec.random_audio_type
		head = "select {at}.url as url, {at}.{f} as id from {at} join {t} on {at}.{f} = {t}.id where {at}.grammar_audio_type "
		prompt = head + " = 1 order by random()" # TODO: fix hard-coded grammar_audio_type = 1 ("prompt")
		prompt_audio = await fetchone_(dbc, prompt.format(**args), [])
		target_audio = None
		if prompt_audio:
			target = head + " <= {rat} and {at}.grammar_audio_type > 1 and {t}.id = ? order by {at}.grammar_audio_type desc" # this fetches the requested random_audio_type and anything "simpler" as a fallback, then sorts (see tail) reverse, by grammar_audio_type, to give preferrential treatment to the right audio-type target; only the top hit is returned.
			target_audio = await fetchone_(dbc, target.format(**args), (prompt_audio['id'],))
			if not target_audio:
				return None
		else:
			return None
		return (prompt_audio, target_audio) # only return when we have both values; caller should always check for None!
	
	subject_fetch_args = {
		#1: dict(at = 'timeline_audio', t = 'event', f = 'event'),
		2: dict(at = 'history_audio', t = 'history', f = 'history'),
		5: dict(at = 'science_audio', t = 'science', f = 'science'),
	}
	if spec.subject == 0:
		# Fetch an audio-pair (prompt and target) for each subject:
		result = []
		for args in subject_fetch_args.values():
			r = await fetch(**args)
			if r:
				result.append(r)
		return random.choice(result)
	else:
		# Fetch an audio-pair for only the specified subject:
		return fetch(subject_fetch_args[spec.subject])


async def get_programs(dbc):
	return await fetchall(dbc, ('select * from program', ()))

async def get_program(dbc, id):
	return await fetchone(dbc, ('select * from program where id = ? order by grade_first', (id,)))

async def get_subjects(dbc):
	return await fetchall(dbc, ('select * from subject', []))

async def get_cycles(dbc):
	return await fetchall(dbc, ('select * from cycle', []))

async def get_new_user_invitation(dbc, code):
	return await fetchone(dbc, ('select * from new_user_invitation where code = ?', (code,)))

async def get_enrollments(dbc, person_id):
	return await fetchall(dbc, ('select enrollment.*, program.name as program_name from enrollment join program on enrollment.program = program.id where student = ?', (person_id,)))

async def get_user_enrollment(dbc, user_id):
	return await fetchone(dbc, ('select * from enrollment join person on enrollment.student = person.id join user on person.user = user.id where user.id = ?', (user_id,)))

async def get_person(dbc, id):
	return await fetchone(dbc, ('select * from person where id = ?', (id,)))

async def get_person_user(dbc, person_id):
	return await fetchone(dbc, ('select person.*, user.* from person join user where user.person = person.id', (id,)))
async def get_person_phones(dbc, person_id):
	return await fetchall(dbc, ('select phone.* from phone join person_phone on phone.id = person_phone.phone join person on person_phone.person = person.id where person.id = ?', (person_id,)))

async def get_person_emails(dbc, person_id):
	return await fetchall(dbc, ('select email.* from email join person_email on email.id = person_email.email join person on person_email.person = person.id where person.id = ?', (person_id,)))

async def get_person_addresses(dbc, person_id):
	return await fetchall(dbc, ('select address.* from address join person_address on address.id = person_address.address join person on person_address.person = person.id where person.id = ?', (person_id,)))

# NOTE: that enrollment.grade and enrollment.program are not redundant!  Even though you could get to program via grade, through the grade_program join table, a student may or MAY NOT actually be enrolled in multiple programs associated with a given grade!
_children_programs = '''select c.*, program.name as program_name, program.schedule as program_schedule, program.id as program_id from child_guardian 
	join person as c on child_guardian.child = c.id
	join person as g on child_guardian.guardian = g.id
	join enrollment on enrollment.student = c.id
	join academic_year on enrollment.academic_year = academic_year.id
	join program on program.id = enrollment.program
	'''

_order_group_children = ' order by c.birthdate desc, enrollment.program'

async def get_family(dbc, person_id, academic_year_id):
	guardians = await fetchall(dbc, ('select g.* from child_guardian join person as g on child_guardian.guardian = g.id join person as c on child_guardian.child = c.id where c.id = ?', (person_id,)))
	if guardians:
		# person_id is a child, and we just got the guardians; now get the other children:
		ids = [g['id'] for g in guardians]
		children = await fetchall(dbc, (_children_programs + ' where g.id in ({seq}) and academic_year.id = ?'.format(seq = ','.join(['?']*len(ids))) + _order_group_children, ids + [academic_year_id,]))
	else:
		# person_id is a guardian, get children, and other guardians:
		children = await fetchall(dbc, (_children_programs + ' where g.id = ? and academic_year.id = ?' + _order_group_children, (person_id, academic_year_id))) # TODO: factor out HARDCODE academic_year.id = 2!
		ids = [c['id'] for c in children]
		guardians = await fetchall(dbc, ('select g.* from child_guardian join person as g on child_guardian.guardian = g.id join person as c on child_guardian.child = c.id where c.id in ({seq}) group by g.id'.format(seq= ','.join(['?']*len(ids))), ids))

	return util.Struct(
		children = children,
		guardians = guardians,
	)

async def get_heads_of_households(dbc):
	return await fetchall(dbc, ('select * from person where head_of_household = 1', ()))

async def get_family_children_DEPRECATED(dbc, parent_id): # TODO: remove; now just fetched as a part of get_family()
	return await fetchall(dbc, (_children_programs + ' where g.id = ?' + _order_group_children, (parent_id,)))

async def get_costs(dbc, academic_year_id):
	return await fetchall(dbc, ('''select * from cost 
		join academic_year on cost.academic_year = academic_year.id
		where academic_year.id = ?
		''', (academic_year_id,))) # TODO: change this to just where academic_year = ? -- no need for the join, in this case!

async def get_cost_offset(dbc, parent_id, academic_year_id):
	return await fetchall(dbc, ('select * from cost_offset where academic_year = ? and parent = ?', (academic_year_id, parent_id)))


async def get_payments(dbc, guardian_ids, academic_year_id):
	return await fetchall(dbc, ('select * from payment where person in ({seq}) and academic_year = ?'.format(seq = ','.join(['?']*len(guardian_ids))), guardian_ids + [academic_year_id,]))

async def get_leader(dbc, person_id, academic_year_id):
	#TODO: Add logic for filtering records for the CURRENT/coming academic year only
	return await fetchall(dbc, ('''
			select leader.*, leadership_role.name as role, program.name as program_name, subject.name as subject_name from leader
			join leadership_role on leader.leadership_role = leadership_role.id
			join program on leader.program = program.id
			left join subject on leader.subject = subject.id
			where person = ? and academic_year = ?
		''', (person_id, academic_year_id)))
	
# -----------------------------------------------------------------------------
# Implementation utilities:

def _join(joins):
	if joins:
		return ' join ' + ', '.join(joins) + ' '
	#else:
	return ''

def _or_wheres(wheres):
	if wheres:
		return ' (%s) ' % ' or '.join(wheres)
	#else:
	return ''

def _where(wheres): # "AND"-joined wheres (i.e., intersection, not union)
	if wheres:
		return ' where ' + ' and '.join(wheres) + ' '
	#else:
	return ''

 
def _no_broaden(first_week, last_week):
	return first_week, last_week

def _unitify(weeks, first_week, last_week = None, offset = 1):
	# TODO: make 'offset' an arg to _filter_cycle_week_range, so that various users of this service can specify the offset; for now, History/Timeline is our only triplicate, and that needs offset=1 (so that, on week 3, grammar for weeks 4-6 should be shown; i.e., high-schoolers are always 1 week ahead of the next three week block -- they read from SotW chapters for the coming triplicate 1 week in advance of that three-week period)
	if first_week < 1: first_week = 1
	if last_week < 1: last_week = 1
	base = int((first_week - 1 + offset) / weeks) * weeks
	first, last = base + 1, base + weeks
	if last_week and last_week != first_week:
		last_base = int(last_week / weeks) * weeks
		first = min(first, last_base + 1)
		last = max(last, last_base + weeks)
	return first, last

def _triplify(first_week, last_week = None):
	return _unitify(3, first_week, last_week)

def _filter_cycle_week_range(spec, joins, wheres, args, cw_week_range = False, broaden = _no_broaden):
	if spec.first_week or spec.last_week or spec.cycles:
		# Joins:
		if cw_week_range:
			joins.append(f"cycle_week as cw on {spec.table}.cw_first = cw.id")
			joins.append(f"cycle_week as cw_last on {spec.table}.cw_last = cw_last.id")
		else:
			joins.append(f"cycle_week as cw on {spec.table}.cw = cw.id")
		if spec.first_week != None or spec.last_week != None:
			# Wheres:
			# Massage if necessary (NOTE: this modification to the spec is actually used by upper layers of code - this alters an invalid week range to make it valid):
			if spec.first_week == None:
				spec.first_week = 0
			if spec.last_week == None:
				spec.last_week = spec.first_week
			if spec.last_week < spec.first_week:
				spec.last_week = spec.first_week
			# Now set up the WHEREs:
			if cw_week_range:
				#wheres.append("(cw.week = 0 or (? <= cw_last.week and cw.week <= ?))") # we're no longer calling week 0 "all weeks" -- now it means: summer / prior to week-1
				wheres.append("(? <= cw_last.week and cw.week <= ?)")
			else:
				wheres.append("(? <= cw.week and cw.week <= ?)")
			args.extend(broaden(spec.first_week, spec.last_week))
		if spec.cycles:
			wheres.append("cw.cycle in (%s)" % ', '.join([str(int(i)) for i in spec.cycles + (4,)])) # add "cycle 4", which is just an "all cycles" indicator
	#else, no-op

def _filter_program(spec, joins, wheres, args):
	joins.append(f'program on {spec.table}.program = program.id')
	wheres.append('program.id = ?')
	args.append(spec.program if spec.program else 1) # default to "grammar" program (TODO: hardish code!)

def _filter_date_range(spec, wheres, args):
	if spec.date_range:
		wheres.append(f"{spec.table}.start >= ? and {spec.table}.start <= ?")
		args.extend(spec.date_range)
	#else, no-op

def _filter_exclude_ids(spec, wheres, exclude_ids):
	if exclude_ids:
		wheres.append(f"{spec.table}.id not in (%s)" % ', '.join([str(e) for e in exclude_ids]))
	#else, no-op

def _random_select(spec, joins, wheres, count):
	return f"select * from {spec.table} " + _join(joins) + _where(wheres) + " order by random() limit %d" % count

def _get_keyword_similar_events(spec, count, event, exids, joins, wheres):
	keywords = list(map(str.strip, event['keywords'].split(','))) if event['keywords'] else []  # listify the comma-separated-list string
	keywords.extend(re.findall('([A-Z][a-z]+)', event['name']))  # add all capitalized words within event's name
	or_wheres = [f"{spec.table}.name like '%%%s%%' or {spec.table}.primary_sentence like '%%%s%%' or {spec.table}.keywords like '%%%s%%'" % (word, word, word) for word in keywords]  # injection-safe b/c keywords are safe; not derived from user input
	return f'select * from {spec.table} %(joins)s %(wheres)s and {spec.table}.id not in (%(exids)s) and (%(orwheres)s) order by random() limit %(count)d' % {
			'joins': _join(joins),
			'wheres': _where(wheres),
			'exids': ', '.join([str(e) for e in exids]),
			'orwheres': ' or '.join(or_wheres),
			'count': count} # consider (postgre)sql functions instead of this giant SQL

def _get_temporal_random_events(spec, count, event, exids, joins, wheres):
	k_years_away = 500 # limit to 500 year span in either direction, from event; note that date_range may provide a different scope, but who cares: the tightest scope will win
	return f'select * from {spec.table} %(joins)s %(wheres)s and {spec.table}.id not in (%(exids)s) and event.start >= %(bottom)d and event.start <= %(top)d order by random() limit %(count)d' % {
			'joins': _join(joins),
			'wheres': _where(wheres),
			'exids': ', '.join([str(e) for e in exids]),
			'bottom': (event['start'] if event['start'] else event['fake_start_date']) - k_years_away,
			'top': (event['start'] if event['start'] else event['fake_start_date']) + k_years_away,
			'count': count} # consider (postgre)sql functions instead of this giant SQL

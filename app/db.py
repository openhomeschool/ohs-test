__author__ = 'J. Michael Caine'
__copyright__ = '2020'
__version__ = '0.1'
__license__ = 'MIT'

import hashlib
import re

from os import urandom
from random import shuffle

import logging
l = logging.getLogger(__name__)

from . import sql

# -----------------------------------------------------------------------------
# User stuff

_hash = lambda password, salt: hashlib.pbkdf2_hmac('sha256', bytes(password, 'UTF-8'), salt, 100000)

async def add_user(db, username, password, email):
	salt = urandom(32)
	c = await db.cursor() # need cursor because we need lastrowid, only available via cursor
	r = await c.execute('insert into user (username, password, salt, email) values (?, ?, ?, ?)', (username, _hash(password, salt), salt, email))
	user_id = c.lastrowid
	r = await c.execute('insert into user_role (user, role) values (?, 1)', (user_id,)) #TODO: hard-coded to "role #1, student" -- parameterize!
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
	The result is, for the above:
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

# -----------------------------------------------------------------------------
# Question transactions

_question_transactions = dict()
def qt(cls):
	_question_transactions[cls.__name__] = cls
	return cls

async def get_handler(class_name, db, user_id):
	# Construct and return an object of the specified handler class:
	return await _question_transactions[class_name].create(db, user_id) # TODO: optional args.....

	
class Question_Transaction: # Abstract base class; see actual functional implementations below
	table = None
	
	def __init__(self, db, user_id, week_range = None, answer_option_count = 5):
		self._db = db
		self._user_id = user_id
		self._week_range = week_range # constrain to records only within week_range; expected to be two-tuple of week numbers, as integers, like (3, 10) for weeks 3-10
		self._cycles = None
		self._answer_option_count = answer_option_count
		# Subclasses expected to set self._question and self._options here

	@property
	def db(self):
		return self._db

	@property
	def user_id(self):
		return self._user_id

	@property
	def week_range(self):
		return self._week_range

	@property
	def cycles(self):
		return self._cycles

	@property
	def question(self):
		return self._question

	@property
	def options(self):
		return self._options

	@property
	def answer_id(self):
		return self._answer_id

	@property
	def answer_option_count(self):
		return self._answer_option_count

	def log_user_answer(self, answer_id):
		raise Exception("Must be implemented by subclass")


class Basic_Grammar_QT(Question_Transaction):
	@classmethod # need to use factory pattern creation scheme b/c can't await in __init__
	async def create(cls, db, user_id, week_range = None):
		self = cls(db, user_id, week_range)
		self._question = await sql.fetchone(db, sql.get_random_records(self, 1))
		self._options = await sql.fetchall(db, sql.get_random_records(self, self.answer_option_count - 1, [self._question['id'],]))
		self._options.append(self._question)
		shuffle(self._options)
		self._answer_id = self._question['id']
		return self

	def log_user_answer(self, answer_id):
		l.debug('Basic_Grammar_QT.log_user_answer(%s)' % answer_id)


@qt
class English_Vocabulary_QT(Basic_Grammar_QT):
	table = 'vocabulary'

@qt
class English_Grammar_QT(Basic_Grammar_QT):
	table = 'english'

@qt
class Latin_Vocabulary_QT(Basic_Grammar_QT):
	table = 'latin_vocabulary'

@qt
class Science_Grammar_QT(Basic_Grammar_QT):
	table = 'science'

@qt
class History_Sequence_QT(Question_Transaction):
	table = 'event'
	@classmethod # need to use factory pattern creation scheme b/c can't await in __init__
	async def create(cls, db, user_id, week_range = None, date_range = None):
		self = History_Sequence_QT(db, user_id, week_range)
		self._date_range = date_range # constrain to history events only within date_range; expected to be two-tuple of years, as integers, like (1500, 1750); BC dates are simply negative integers
		self._question = await sql.fetchone(db, sql.get_random_event_records(self, 1))
		self._options, self._answer_id = await sql.get_surrounding_event_records(self, self.answer_option_count, self._question)
		return self

	@property
	def exclude_people_groups(self):
		return True # always exclude people_group records (events) for history-sequence questions

	@property
	def date_range(self):
		return self._date_range

	def log_user_answer(self, answer_id):
		l.debug('History_Sequence_QT.log_user_answer(%s)' % answer_id)

# TODO!!!
# db.execute('insert into test_event_sequence_target (user, event, correct_option) values (?, ?, ?)', (user_id, event_id, correct_event_id)
# db.executemany('insert into test_event_sequence_incorrect_option (target, incorrect_option

# -----------------------------------------------------------------------------
# Resource handlers

async def get_resources(spec):
	return await sql.get_resources(spec)


# -----------------------------------------------------------------------------
# Sundry

async def get_contexts(dbc):
	return await sql.get_contexts(dbc)

async def get_new_user_invitation(dbc, code):
	return await sql.get_new_user_invitation(dbc, code)


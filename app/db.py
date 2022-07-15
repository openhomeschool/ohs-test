__author__ = 'J. Michael Caine'
__copyright__ = '2020'
__version__ = '0.1'
__license__ = 'MIT'


from os import urandom
from random import shuffle

import logging
l = logging.getLogger(__name__)

from . import sql
from . import util

k_subject_ids = sql.k_subject_ids


# -----------------------------------------------------------------------------

async def login(dbc, username, password):
	return await sql.login(dbc, username, password)

async def forget_login(dbc, uuid):
	return await sql.forget_login(dbc, uuid)

async def authenticated(dbc, uuid):
	return await sql.authenticated(dbc, uuid)

async def authorized(dbc, uuid, roles):
	return await sql.authorized(dbc, uuid, roles)

async def get_username(dbc, uuid):
	return await sql.get_username(dbc, uuid)

async def get_user_id(dbc, username):
	return await sql.get_user_id(dbc, username)

async def username_exists(dbc, username):
	return await sql.username_exists(dbc, username)

async def get_usernames(dbc, user_ids):
	return await get_usernames(dbc, user_ids)

async def suggest_username(dbc, person):
	return await sql.suggest_username(dbc, person)

async def add_user_switch_allows(dbc, from_user_ids, user_id = None, without_password = True, commit = True):
	return await sql.add_user_switch_allows(dbc, from_user_ids, user_id, without_password, commit)

async def get_switch_users(dbc, uuid):
	return await sql.get_switch_users(dbc, uuid)

async def switch_user(dbc, from_uuid, to_username):
	return await sql.switch_user(dbc, from_uuid, to_username)

async def is_user_teacher(dbc, uid):
	return await sql.is_user_teacher(dbc, uid)

async def is_person_teacher(dbc, pid):
	return await sql.is_person_teacher(dbc, pid)

async def is_a_guardian(dbc, pid):
	return await sql.is_a_guardian(dbc, pid)

async def forge_noun_passwords(dbc):
	return await sql.forge_noun_passwords(dbc)

async def create_user(dbc, username, password, person_id, commit = True):
	return await sql.create_user(dbc, username, password, person_id, commit)

async def reset_user_password(dbc, uuid, new_password):
	return await sql.reset_user_password(dbc, uuid, new_password)

async def get_user_settings(dbc, uuid):
	return await sql.get_user_settings(dbc, uuid)

async def get_person_username(dbc, person_id):
	return await sql.get_person_username(dbc, person_id)

async def add_role(dbc, uid, role, commit = True):
	return await sql.add_role(dbc, uid, role, commit)

async def add_roles(dbc, uid, roles, commit = True):
	return await sql.add_roles(dbc, uid, roles, commit)

async def set_user_bg_color(dbc, uid, avoids = None, commit = True):
	return await sql.set_user_bg_color(dbc, uid, avoids, commit)

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
	def first_week(self): # TODO: kludgy - conform to new 'spec' design!
		if not self._week_range:
			return None
		return self._week_range[0]

	@property
	def last_week(self): # TODO: kludgy - conform to new 'spec' design!
		if not self._week_range:
			return None
		return self._week_range[1]

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




# ------------------------
# Arithmetic -- old/original idea; this is all of it - didn't take very far....
@qt
class Arithmetic_QT_DEPRECATE(Question_Transaction):
	table = 'arithmetic_fact'
	@classmethod # need to use factory pattern creation scheme b/c can't await in __init__
	async def create(cls, db, user_id):
		self = Arithmetic_QT(db, user_id)
		self._question = await sql.fetchone(db, sql.get_next_arithmetic_fact(self))
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

# ------------------------
# Arithmetic -- new design....

async def get_arithmetic_facts_DEPRECATE(dbc, spec):
	return await sql.get_arithmetic_facts(dbc, spec)

async def assess_arithmetic_fact_DEPRECATE(dbc, spec): # spec contains arithmetic_fact_id, user's answer (or, more likely, 'correct' True/False, and speed_ms
	return await sql.assess_arithmetic_fact(dbc, spec)

# NEWER STILL....

async def arithmetic_new_problems(dbc, uuid, spec):
	return await sql.arithmetic_new_problems(dbc, uuid, spec)

async def arithmetic_answer(dbc, uuid, data):
	return await sql.arithmetic_answer(dbc, uuid, data)

async def arithmetic_totals(dbc, uuid, spec):
	return await sql.arithmetic_totals(dbc, uuid, spec)


# -----------------------------------------------------------------------------
# Resource handlers

async def get_grammar_resources(dbc, spec):
	return await sql.get_grammar_resources(dbc, spec)

async def get_middle_resources(dbc, spec):
	return await sql.get_middle_resources(dbc, spec)

async def get_high1_resources(dbc, spec):
	return await sql.get_high1_resources(dbc, spec)



async def get_external_resource_detail_DEPRECATE(id):
	return await sql.get_external_resource_detail_DEPRECATE(id)

async def get_shopping_links(dbc, resource_id):
	return await sql.get_shopping_links(dbc, resource_id)

async def get_shopping(dbc, spec):
	return await sql.get_shopping(dbc, spec)

async def mark_assignment(dbc, uuid, instruction_id, checked):
	return await sql.mark_assignment(dbc, uuid, instruction_id, checked)

#DEPRECATE: async def get_external_resources(spec):
#DEPRECATE: 	return await sql.get_external_resources(spec)


async def get_detail(dbc, key):
	return await sql.get_detail(dbc, key)

async def get_detail_by_id(dbc, table, id):
	return await sql.get_detail_by_id(dbc, table, id)

# -----------------------------------------------------------------------------
# Sundry

async def get_programs(dbc):
	return await sql.get_programs(dbc)

async def get_program(dbc, id):
	return await sql.get_program(dbc, id)

async def get_subjects(dbc):
	return await sql.get_subjects(dbc)

async def get_cycles(dbc):
	return await sql.get_cycles(dbc)

async def get_new_user_invitation(dbc, code):
	return await sql.get_new_user_invitation(dbc, code)

async def get_enrollments(dbc, person_id):
	return await sql.get_enrollments(dbc, person_id)

async def get_user_enrollment(dbc, user_id):
	return await sql.get_user_enrollment(dbc, user_id)

async def get_person(dbc, id):
	return await sql.get_person(dbc, id)

async def get_person_user(dbc, person_id):
	return await sql.get_person_user(dbc, person_id)

async def get_family_enrollments(dbc, id, academic_year_id):
	return await sql.get_family_enrollments(dbc, id, academic_year_id)

from dataclasses import dataclass
async def get_person_contact_info(dbc, person_id):
	return util.Struct(
		addresses = await sql.get_person_addresses(dbc, person_id),
		phones = await sql.get_person_phones(dbc, person_id),
		emails = await sql.get_person_emails(dbc, person_id),
	)

async def get_heads_of_households(dbc):
	return await sql.get_heads_of_households(dbc)

async def get_family_children_DEPRECATED(dbc, parent_id):
	return await sql.get_family_children_DEPRECATED(dbc, parent_id)

async def get_costs(dbc, academic_year_id):
	return await sql.get_costs(dbc, academic_year_id)

async def get_cost_offset(dbc, parent_id, academic_year_id):
	return await sql.get_cost_offset(dbc, parent_id, academic_year_id)

async def get_payments(dbc, guardian_ids, academic_year_id):
	return await sql.get_payments(dbc, guardian_ids, academic_year_id)

async def get_leader(dbc, person_id, academic_year_id):
	return await sql.get_leader(dbc, person_id, academic_year_id)

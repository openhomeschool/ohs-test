__author__ = 'J. Michael Caine'
__copyright__ = '2020'
__version__ = '0.1'
__license__ = 'MIT'

import re

from datetime import date, timedelta
from dataclasses import dataclass

from . import util

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
	e = await db.execute(*sql_and_args)
	return await e.fetchone()

async def fetchall(db, sql_and_args):
	e = await db.execute(*sql_and_args)
	return await e.fetchall()


# -----------------------------------------------------------------------------
'''
Main database functions
Expectation / pattern: these typically return 2-tuples: (sql, arg_list)
'''

def get_random_records(spec, count, exclude_ids = None):
	'''
	Get `count` random records from the spec table using `spec` object.
	`spec` object expected to be a English_Vocabulary_QT object.
	Any records with ids in `exclude_ids` are excluded.
	'''
	joins, wheres, args = [], [], []
	_filter_cycle_week_range(spec, joins, wheres, args)
	_exclude_ids(spec, wheres, exclude_ids)
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
	_date_range(spec, wheres, args)
	_exclude_ids(spec, wheres, exclude_ids)
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
	_date_range(spec, wheres, args)

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



# ---------------------------------------------------
# Resources

#TODO: considering renaming "resources" to "lode".... (and using other 4-letter terms: quiz, test,  case (study), gist (view), pith (probe)
async def get_lode(spec): # TODO: deprecate _get_external_resources()!
	pass


@dataclass
class Subject_Spec:
	subject: str
	subject_id: int # id value of corresponding record in subject table; "hard-code"
	table: str
	search_fields: tuple
	deep_search_fields: tuple = None
	extra_joins: tuple = None
	order_by: str = 'cw.cycle, cw.week'

@dataclass
class Resource_Result:
	subject: str
	grammar_resources: list = None
	external_resources: list = None
	assignments: list = None

k_timeline_grammar = Subject_Spec('timeline', 1, 'event', ('name', 'keywords'), ('primary_sentence', 'secondary_sentence'), None, 'cw.cycle, cw.week, event.seq')
k_history_grammar = Subject_Spec('history', 2, 'history', ('name', 'keywords', 'primary_sentence'), ('secondary_sentence',), ('event on history.event = event.id',))
k_science_grammar = Subject_Spec('science', 5, 'science', ('prompt', 'answer'), ('note',))
k_english_vocabulary = Subject_Spec('english_vocabulary', 6, 'vocabulary', ('word', 'definition'), ('root',''))
k_latin_vocabulary = Subject_Spec('latin_vocabulary', 7, 'latin_vocabulary', ('word', 'translation'))

async def get_grammar_resources(spec):
	# Returns list of Resource_Result objects; one per subject, in this specified subject order (below)
	return [Resource_Result(subject_spec.subject, await _get_grammar_resources(spec, subject_spec)) for subject_spec in [
		k_timeline_grammar,
		k_history_grammar,
		# TODO: Geography
		# TODO: Math
		k_science_grammar,
		k_english_vocabulary,
		k_latin_vocabulary,
	] if spec.subject == 0 or spec.subject == subject_spec.subject_id] # pre-filter for subject -- don't make calls to _get_grammar_resources(), above, except for subjects requested in spec.subject

async def _get_grammar_resources(spec, subject_spec):
	spec.table = subject_spec.table # some of the following functions want table in spec (only have spec)
	joins, wheres, args = [], [], []
	if subject_spec.extra_joins:
		joins.extend(subject_spec.extra_joins)
	_filter_cycle_week_range(spec, joins, wheres, args)
	if spec.search and subject_spec.search_fields:
		or_wheres = []
		for field in subject_spec.search_fields:
			or_wheres.append(f'{field} like ?')
			args.append('%' + spec.search + '%')
		wheres.append(_or_wheres(or_wheres))

	return await fetchall(spec.db, (f"select * from {subject_spec.table} " + _join(joins) + _where(wheres) + f" order by {subject_spec.order_by}", args))


_external_resource_joins = [
	'resource on resource_use.resource = resource.id',
	'subject on resource_use.subject = subject.id',
]

async def _get_exre_resources(spec, subject_spec):
	spec.table = subject_spec.table # some of the following functions want table in spec (only have spec)
	joins = _external_resource_joins
	if subject_spec.extra_joins:
		joins.extend(subject_spec.extra_joins)
	wheres, args = ['subject = ?',], [subject_spec.subject_id]
	_filter_cycle_week_range(spec, joins, wheres, args, True)
	_filter_program(spec, joins, wheres, args)
	return await fetchall(spec.db, (f'select subject.name as subject_name, resource.name as resource_name, resource_use.optional from {spec.table}' \
		+ _join(joins) + _where(wheres) + ' order by subject_name, optional, resource_name', args))
	
	return await fetchall(spec.db, ()


k_history_exre = Subject_Spec('history', 2, 'resource_use', ('resource.name',), ('resource.note',))

async def _get_assignments(spec, a_spec):
	return [] #TODO!


async def get_high1_resources(spec):
	# Returns list of Resource_Result objects; one per subject, in this specified subject order (below)
	return [Resource_Result(gr_spec.subject,
					await _get_grammar_resources(spec, gr_spec),
					await _get_exre_resources(spec, exre_spec),
					await _get_assignments(spec, a_spec)) for (gr_spec, exre_spec, a_spec)) in [
		(k_history_grammar, k_history_exre, None),
	] if spec.subject == 0 or spec.subject == subject_spec.subject_id] # pre-filter for subject -- don't make calls to _get_*_resources(), above, except for subjects requested in spec.subject


async def get_external_resources(spec):
	joins = _external_resource_joins
	spec.table = 'resource_use' # used in _filter_* calls to join
	wheres, args = [], []
	_filter_cycle_week_range(spec, joins, wheres, args, True)
	_filter_program(spec, joins, wheres, args)
	return await fetchall(spec.db, (f'select subject.name as subject_name, resource.name as resource_name, resource_use.optional from {spec.table}' \
		+ _join(joins) + _where(wheres) + ' order by subject_name, optional, resource_name', args))

async def get_external_resource_detail(id):
	joins = _external_resource_joins + [
		'resource_acquisition on resource_acquisition.resource = resource.id',
		'resource_type on resource_acquisition.type = resource_type.id',
		'resource_source on resource_acquisition.source = resource_source.id',
	]
	return await fetchone(spec.db, ('select resource.note, resource_acquisition.note as acquisition_note, resource_type.name as resource_type_name, resource_source.name as resource_source_name, resource_source.logo as resource_source_logo, resource_acquisition.url, from resource_use' \
		+ _join(joins) + ' where resource_use.id = ? order by subject_name, optional, resource_name, acquisition_note, resource.note', (id,)))

async def get_assignments(spec):
	joins = [
		'subject on resource_use.subject = subject.id',
	]
	spec.table = 'assignment'
	wheres, args = [], []
	_filter_cycle_week_range(spec, joins, wheres, args)
	_filter_program(spec, joins, wheres, args)
	return await fetchall(spec.db, (f'select subject.name as subject_name, assignment.* from {spec.table}' \
		+ _join(joins) + _where(wheres) + ' order by subject_name, cw.week, assignment.order', args))

async def get_programs(dbc):
	return await fetchall(dbc, ('select * from program', []))

async def get_subjects(dbc):
	return await fetchall(dbc, ('select * from subject', []))

async def get_cycles(dbc):
	return await fetchall(dbc, ('select * from cycle', []))

async def get_new_user_invitation(dbc, code):
	return await fetchone(dbc, ('select * from new_user_invitation where code = ?', (code,)))

async def get_person(dbc, id):
	return await fetchone(dbc, ('select * from person where id = ?', (id,)))

async def get_person_phones(dbc, person_id):
	return await fetchall(dbc, ('select phone.* from phone join person_phone on phone.id = person_phone.phone join person on person_phone.person = person.id where person.id = ?', (person_id,)))

async def get_person_emails(dbc, person_id):
	return await fetchall(dbc, ('select email.* from email join person_email on email.id = person_email.email join person on person_email.person = person.id where person.id = ?', (person_id,)))

async def get_person_addresses(dbc, person_id):
	return await fetchall(dbc, ('select address.* from address join person_address on address.id = person_address.address join person on person_address.person = person.id where person.id = ?', (person_id,)))

_children_programs = '''select c.*, program.name as program_name, program.schedule as program_schedule, program.id as program_id from child_guardian 
	join person as c on child_guardian.child = c.id
	join person as g on child_guardian.guardian = g.id
	join enrollment on enrollment.student = c.id
	join program on program.id = enrollment.program'''

_order_group_children = ' order by c.birthdate desc'

async def get_family(dbc, person_id):
	guardians = await fetchall(dbc, ('select g.* from child_guardian join person as g on child_guardian.guardian = g.id join person as c on child_guardian.child = c.id where c.id = ?', (person_id,)))
	if guardians:
		# person_id is a child, and we just got the guardians; now get the other children:
		ids = [g['id'] for g in guardians]
		children = fetchall(dbc, (_children_programs + ' where g.id in ({seq})'.format(seq = ','.join(['?']*len(ids))) + _order_group_children, ids))
	else:
		# person_id is a guardian, get children, and other guardians:
		children = await fetchall(dbc, (_children_programs + ' where g.id = ? ' + _order_group_children, (person_id,)))
		ids = [c['id'] for c in children]
		guardians = await fetchall(dbc, ('select g.* from child_guardian join person as g on child_guardian.guardian = g.id join person as c on child_guardian.child = c.id where c.id in ({seq}) group by g.id'.format(seq= ','.join(['?']*len(ids))), ids))

	return util.Struct(
		children = children,
		guardians = guardians,
	)

async def get_heads_of_households(dbc):
	return await fetchall(dbc, 'select * from person where head_of_household = 1')

async def get_family_children(dbc, parent_id):
	return await fetchall(dbc, (_children_programs + ' where g.id = ?' + _order_group_children, (parent_id,)))

async def get_costs(dbc):
	return await fetchall(dbc, ('select * from cost', ()))

async def get_payments(dbc, guardian_ids):
	return await fetchall(dbc, ('select * from payment where person in ({seq})'.format(seq = ','.join(['?']*len(guardian_ids))), guardian_ids))
	
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
 
def _filter_cycle_week_range(spec, joins, wheres, args, cw_week_range = False):
	if spec.first_week or spec.last_week or spec.cycles:
		if cw_week_range:
			joins.append(f"cycle_week as cw_first on {spec.table}.cw_first = cw_first.id")
			joins.append(f"cycle_week as cw_last on {spec.table}.cw_last = cw_last.id")
		else:
			joins.append(f"cycle_week as cw on {spec.table}.cw = cw.id")
		if spec.first_week or spec.last_week:
			# Massage if necessary:
			if not spec.first_week:
				spec.first_week = 1
			if not spec.last_week:
				spec.last_week = spec.first_week
			if spec.last_week < spec.first_week:
				spec.last_week = spec.first_week
			# Now set it up:
			if cw_week_range:
				wheres.append("cw_first.week = 0 or (? <= cw_last.week and cw_first.week <= ?)")
			else:
				wheres.append("cw.week = 0 or (? <= cw.week and cw.week <= ?)")
			args.extend((spec.first_week, spec.last_week))
		if spec.cycles:
			if cw_week_range:
				wheres.append("cw_first.cycle in (%s)" % ', '.join([str(int(i)) for i in spec.cycles]))
			else:
				wheres.append("cw.cycle in (%s)" % ', '.join([str(int(i)) for i in spec.cycles]))
	#else, no-op

def _filter_program(spec, joins, wheres, args):
	joins.append(f'program on {spec.table}.program = program.id')
	wheres.append('program.id = ?')
	args.append(spec.program if spec.program else 1) # default to "grammar" program (TODO: hardish code!)

def _date_range(spec, wheres, args):
	if spec.date_range:
		wheres.append(f"{spec.table}.start >= ? and {spec.table}.start <= ?")
		args.extend(spec.date_range)
	#else, no-op

def _exclude_ids(spec, wheres, exclude_ids):
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

__author__ = 'J. Michael Caine'
__copyright__ = '2020'
__version__ = '0.1'
__license__ = 'MIT'

import re

from dataclasses import dataclass

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
	_cycle_week_range(spec, joins, wheres, args)
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
	_cycle_week_range(spec, joins, wheres, args)
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
	_cycle_week_range(spec, joins, wheres, args)
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



async def get_resources(spec):
	# Cycle, Week, Subject, Content (subject-specific presentation, option of "more details"), "essential" resources (e.g., song audio)

	@dataclass
	class Subject_Spec:
		subject: str
		table: str
		search_fields: tuple
		deep_search_fields: tuple = None
		extra_joins: tuple = None
		order_by: str = 'cw.cycle, cw.week'
		
	subject_specs = ( # A dict would work, but we'd loose the (sequencial) order, which we might like to remain consistent; even if the order itself isn't so important (timeline first?), consistency is, for the user's expectations
		Subject_Spec('timeline', 'event', ('name', 'keywords'), ('primary_sentence', 'secondary_sentence'), None, 'cw.cycle, cw.week, event.seq'),
		Subject_Spec('history', 'history', ('name', 'keywords', 'primary_sentence'), ('secondary_sentence',), ('event on history.event = event.id',)),
		# Geography
		# Math
		Subject_Spec('science', 'science', ('prompt', 'answer'), ('note',)),
		Subject_Spec('english_vocabulary', 'vocabulary', ('word', 'definition'), ('root','')),
		Subject_Spec('latin_vocabulary', 'latin_vocabulary', ('word', 'translation')),
	)

	results = [] # list of 2-tuples: [(subject_spec, recordset), ...]]
	if spec.context <= 1: # TODO: this is a temporary hardcode to grab 'grammar' resources only if the context 'Grammar' (or 'All') is chosen, since this isn't in the database yet!
		for subject_spec in subject_specs:
			spec.table = subject_spec.table # some lower functions want table in spec
			results.append((subject_spec.subject, await _get_grammar_resources(spec, subject_spec)))
	else:
		results.append(('external_resources', await _get_external_resources(spec)))

	return results

async def _get_grammar_resources(spec, subject_spec):
	joins, wheres, args = [], [], []
	if subject_spec.extra_joins:
		joins.extend(subject_spec.extra_joins)
	_cycle_week_range(spec, joins, wheres, args)
	if spec.search_string and subject_spec.search_fields:
		or_wheres = []
		for field in subject_spec.search_fields:
			or_wheres.append(f'{field} like ?')
			args.append('%' + spec.search_string + '%')
		wheres.append(_or_wheres(or_wheres))

	return await fetchall(spec.db, (f"select * from {subject_spec.table} " + _join(joins) + _where(wheres) + f" order by {subject_spec.order_by}", args))

async def _get_external_resources(spec):
	return await fetchall(spec.db, ('select subject.name as subject_name, resource.name as resource_name, resource.note, resource_instance.note as instance_note, resource_type.name as resource_type_name, resource_source.name as resource_source_name, resource_source.logo as resource_source_logo, resource_instance.url, resource_use.optional from resource_use join resource on resource_use.resource = resource.id join subject on resource_use.subject = subject.id join resource_instance on resource_instance.resource = resource.id join resource_type on resource_instance.type = resource_type.id join resource_source on resource_instance.source = resource_source.id join context on resource_use.context = context.id where context.id = ? order by subject_name, optional, resource_name, instance_note, resource.note', (spec.context,)))

async def get_contexts(dbc):
	return await fetchall(dbc, ('select * from context', []))


# -----------------------------------------------------------------------------
# Implementation utilities:

def _join(joins):
	if joins:
		return ' join ' + ', '.join(joins)
	#else:
	return ''

def _or_wheres(wheres):
	if wheres:
		return '(%s)' % ' or '.join(wheres)
	#else:
	return ''

def _where(wheres): # "AND"-joined wheres (i.e., intersection, not union)
	if wheres:
		return ' where ' + ' and '.join(wheres)
	#else:
	return ''
 
def _cycle_week_range(spec, joins, wheres, args):
	if spec.week_range or spec.cycles:
		joins.append(f"cycle_week as cw on {spec.table}.cw = cw.id")
		if spec.week_range:
			wheres.append("? <= cw.week and cw.week <= ?")
			args.extend(spec.week_range)
		if spec.cycles:
			wheres.append("cw.cycle in (%s)" % ', '.join([str(int(i)) for i in spec.cycles]))
	#else, no-op

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

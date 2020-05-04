__author__ = 'J. Michael Caine'
__copyright__ = '2020'
__version__ = '0.1'
__license__ = 'MIT'

import hashlib
from os import urandom
import re

import logging
l = logging.getLogger(__name__)


# Handlers --------------------------------------------------------------------

async def add_user(db, *args):
	c = await db.cursor() # need cursor because we need lastrowid, only available via cursor
	r = await c.execute(*_add_user(*args))
	return r.lastrowid

_get_users_limited = lambda limit: ('select * from test_user limit ?', (limit,))
async def get_users_limited(db, limit):
	c = await db.execute(*_get_users_limited(limit))
	return await c.fetchall()
	

_find_users = lambda like: ('select * from test_user where username like ?', ('%' + like + '%',))
async def find_users(db, like):
	c = await db.execute(*_find_users(like))
	return await c.fetchall()

# ------------

async def get_question(function, db, payload):
	return await function(db, payload)

exposed = {}
def expose(func):
	exposed[func.__name__] = func
	def wrapper():
		func()

@expose
async def get_history_sequence_question(db, payload):
	primary = await get_random_event(db, week_range = (1, 12), date_range = None)
	events = await get_surrounding_events(db, primary, week_range = (1, 12), date_range = None)
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
def get_science_grammar_question(db, payload):
	pass

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


# Utils -----------------------------------------------------------------------

_hash = lambda password, salt: hashlib.pbkdf2_hmac('sha256', bytes(password, 'UTF-8'), salt, 100000)
def _add_user(username, password, email):
	salt = urandom(32)
	return ('insert into test_user(username, password, salt, email) values (?, ?, ?, ?)', (username, _hash(password, salt), salt, email))

def _week_range(week_range, joins, wheres, args):
	joins.append('join cycle_week as cw on event.cw = cw.id')
	wheres.append('? <= cw.week and cw.week <= ?')
	args.extend(week_range)

def _date_range(date_range, wheres, args):
	wheres.append('event.start >= ? and event.start <= ?')
	args.extend(date_range)

def _week_and_date_ranges(week_range = None, date_range = None, exclude_people_groups = True):
	joins = []
	wheres = ['event.people_group is not true'] if exclude_people_groups else []
	args = []
	if week_range:
		_week_range(week_range, joins, wheres, args)
	if date_range:
		_date_range(date_range, wheres, args)
	return joins, wheres, args
	
def s_get_random_event(week_range = None, date_range = None, exclude_ids = None):
	'''
	ranges are "inclusive"
	'''
	joins, wheres, args = _week_and_date_ranges(week_range, date_range)
	if exclude_ids:
		wheres.append('event.id not in (%s)' % ', '.join([str(e) for e in exclude_ids]))
	result = 'select event.* from event ' + ' '.join(joins) + (' where ' + ' and '.join(wheres) if wheres else '') + ' order by random() limit 1'
	return result, args

async def get_random_event(db, week_range = None, date_range = None, exclude_ids = None):
	e = await db.execute(*s_get_random_event(week_range, date_range, exclude_ids))
	return await e.fetchone()


def s_get_keyword_similar_events(event, week_range = None, date_range = None, limit = 5, exclude_ids = None):
	joins, wheres, args = _week_and_date_ranges(week_range, date_range)
	keywords = list(map(str.strip, event['keywords'].split(','))) if event['keywords'] else [] # listify the comma-separated-list string
	keywords.extend(re.findall('([A-Z][a-z]+)', event['name'])) # add all capitalized words within event's name
	or_wheres = ["event.name like '%%%s%%' or event.primary_sentence like '%%%s%%' or event.keywords like '%%%s%%'" % (word, word, word) for word in keywords] # injection-safe b/c keywords are safe; not derived from user input
	exids = [event['id']]
	if exclude_ids:
		exids.extend(exclude_ids)
	return ('select event.* from event %s where event.id not in (%s) %s and (%s) order by random() limit %d' %
			(' '.join(joins), ', '.join([str(e) for e in exids]), (' and ' + ' and '.join(wheres) if wheres else ''), ' or '.join(or_wheres), limit), args) # consider (postgre)sql functions instead of this giant SQL

def s_get_temporal_random_events(event, week_range = None, date_range = None, limit = 5, exclude_ids = None):
	joins, wheres, args = _week_and_date_ranges(week_range, date_range)
	k_years_away = 500 # limit to 500 year span in either direction, from event; note that date_range may provide a different scope, but who cares: the tightest scope will win
	exids = [event['id']]
	if exclude_ids:
		exids.extend(exclude_ids)
	return ('select event.* from event %s where event.id not in (%s) %s and event.start >= %d and event.start <= %d order by random() limit %d' %
			(' '.join(joins), ', '.join([str(e) for e in exids]), (' and ' + ' and '.join(wheres) if wheres else ''), (event['start'] if event['start'] else event['fake_start_date']) - k_years_away, (event['start'] if event['start'] else event['fake_start_date']) + k_years_away, limit), args)

def s_get_geography_similar_events(event, week_range = None, date_range = None, limit = 5):
	pass #TODO

def _get_surrounding_events(keyword_similars, temporal_randoms, count = 5):
	'''
	Note that `keyword_similars` and `temporal_randoms` are already randomly-sorted lists
	one or two should be anachronistic and/or truly "unrelated"
	a = keyword-(/title-) similar
	b = 3/4 of a within closest temporal proximity
	c = max(1, remainder-1): completely random few within temporal proximity
	d = 1 (or more, if necessary) totally random (caller is expected to add this, as it will require one or more than SQL calls (get_random_event())
	result = d + c + min(b, remainder-1) + remainder:a [+ more like d if necessary]
	ALSO: avoid all people_group records
	'''
	keyword_similar_count = min(round(count * 2 / 5), len(keyword_similars)) # limit the keyword records to two-fifths of `count`
	temporal_random_count = min(round(count * 2 / 5), len(temporal_randoms)) # limit the temporal/proximity records to two-fifth of `count`
	total_random_count = count - (keyword_similar_count + temporal_random_count)
	return (
		keyword_similars[:keyword_similar_count],
		temporal_randoms[:temporal_random_count],
		total_random_count
	)


async def get_surrounding_events(db, event, week_range = None, date_range = None, count = 5):
	e1 = await (await db.execute(*s_get_keyword_similar_events(event, week_range, date_range, count))).fetchall()
	exids = [e['id'] for e in e1] # ids to exclude from future search results; we only need any given event once
	e2 = await (await db.execute(*s_get_temporal_random_events(event, week_range, date_range, count, exids))).fetchall()
	exids.extend([e['id'] for e in e2])
	keyword_similars, temporal_randoms, random_count = _get_surrounding_events(e1, e2, count)
	randoms = []
	exids.append(event['id'])
	for i in range(random_count):
		e = await get_random_event(db, week_range, date_range, exids)
		if e:
			randoms.append(e)
			exids.append(e['id'])
	result = keyword_similars + temporal_randoms + randoms
	l.debug('EVENTS: %s' % [e['name'] for e in result])
	result.sort(key = lambda e: e['start'] if e['start'] else e['fake_start_date'])
	l.debug('EVENTS: %s' % [e['name'] for e in result])
	return result


# Unit testing... <fledgling start> -------------------------------------------

def _ut_get_random_event(week_range = None, date_range = None):
	event = db.execute(*s_get_random_event(week_range, date_range)).fetchone()
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
		r = c.execute(*s_get_random_event(week_range, date_range, exids)).fetchone()
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

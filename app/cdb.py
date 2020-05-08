# cdb.py

import re

import logging
l = logging.getLogger(__name__)

# SQL Utility Classes  --------------------------------------------------------------------

# SQL Utility superclass cSqlUtil
class cSqlUtil:
	def __init__(self, _tbl_name):
		self.tbl_name = _tbl_name
	def __repr__(self):
		return self
	def __str__(self):
		return self.tbl_name

	def _week_range(self, week_range, joins, wheres, args):
		joins.append(f"join cycle_week as cw on {self.tbl_name}.cw = cw.id")
		wheres.append("? <= cw.week and cw.week <= ?")
		args.extend(week_range)

	def _date_range(self, date_range, wheres, args):
		wheres.append(f"{self.tbl_name}.start >= ? and {self.tbl_name}.start <= ?")
		args.extend(date_range)

	def _week_and_date_ranges(self, week_range = None, date_range = None, exclude_people_groups = True):
		joins = []
		wheres = [self.tbl_name + ".people_group is not true"] if exclude_people_groups else []
		args = []
		if week_range:
			self._week_range(week_range, joins, wheres, args)
		if date_range:
			self._date_range(date_range, wheres, args)
		return joins, wheres, args

	def s_get_random_event(self, week_range = None, date_range = None, exclude_ids = None, exclude_people_groups = True):
		'''
		ranges are "inclusive"
		'''
		joins, wheres, args = self._week_and_date_ranges(week_range, date_range, exclude_people_groups)
		if exclude_ids:
			wheres.append(f"{self.tbl_name}.id not in (%s)" % ', '.join([str(e) for e in exclude_ids]))
		result = f"select {self.tbl_name}.* from {self.tbl_name} " + ' '.join(joins) + (" where " + " and ".join(wheres) if wheres else '') + " order by random() limit 1"
		l.debug("RESULT s_get_random_event: " + result)
		return result, args

	async def get_random_event(self, db, week_range = None, date_range = None, exclude_ids = None, exclude_people_groups = None):
		l.debug("exclude_people_groups = %s" % str(exclude_people_groups))
		e = await db.execute(*self.s_get_random_event(week_range, date_range, exclude_ids, exclude_people_groups))
		return await e.fetchone()

	def _get_surrounding_events(self, keyword_similars, temporal_randoms, count = 5):
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
		keyword_similar_count = min(round(count * 2 / 5), len(keyword_similars))  # limit the keyword records to two-fifths of `count`
		temporal_random_count = min(round(count * 2 / 5), len(temporal_randoms))  # limit the temporal/proximity records to two-fifth of `count`
		total_random_count = count - (keyword_similar_count + temporal_random_count)
		return (
			keyword_similars[:keyword_similar_count],
			temporal_randoms[:temporal_random_count],
			total_random_count
		)

# SQL Utility Events subclass cSqlUtilEvents
class cSqlUtilEvents(cSqlUtil):
	async def get_surrounding_events(self, db, event, week_range = None, date_range = None, count = 5):
		e1 = await (await db.execute(*self.s_get_keyword_similar_events(event, week_range, date_range, count))).fetchall()
		exids = [e['id'] for e in e1]  # ids to exclude from future search results; we only need any given event once
		e2 = await (await db.execute(*self.s_get_temporal_random_events(event, week_range, date_range, count, exids))).fetchall()
		exids.extend([e['id'] for e in e2])
		keyword_similars, temporal_randoms, random_count = self._get_surrounding_events(e1, e2, count)
		randoms = []
		exids.append(event['id'])
		for i in range(random_count):
			e = await self.get_random_event(db, week_range, date_range, exids)
			if e:
				randoms.append(e)
				exids.append(e['id'])
		result = keyword_similars + temporal_randoms + randoms
		l.debug('EVENTS: %s' % [e['name'] for e in result])
		result.sort(key = lambda e: e['start'] if e['start'] else e['fake_start_date'])
		l.debug('EVENTS: %s' % [e['name'] for e in result])
		return result

	def s_get_keyword_similar_events(self, event, week_range = None, date_range = None, limit = 5, exclude_ids = None):
		joins, wheres, args = self._week_and_date_ranges(week_range, date_range)
		keywords = list(map(str.strip, event['keywords'].split(','))) if event['keywords'] else []  # listify the comma-separated-list string
		keywords.extend(re.findall('([A-Z][a-z]+)', event['name']))  # add all capitalized words within event's name
		or_wheres = [f"{self.tbl_name}.name like '%%%s%%' or {self.tbl_name}.primary_sentence like '%%%s%%' or {self.tbl_name}.keywords like '%%%s%%'" % (word, word, word) for word in keywords]  # injection-safe b/c keywords are safe; not derived from user input
		exids = [event['id']]
		
		if exclude_ids:
			exids.extend(exclude_ids)
		return (f"select {self.tbl_name}.* from {self.tbl_name} %s where {self.tbl_name}.id not in (%s) %s and (%s) order by random() limit %d" %
				(' '.join(joins), ', '.join([str(e) for e in exids]), (' and ' + ' and '.join(wheres) if wheres else ''), ' or '.join(or_wheres), limit), args)  # consider (postgre)sql functions instead of this giant SQL

	def s_get_temporal_random_events(self, event, week_range = None, date_range = None, limit = 5, exclude_ids = None):
		joins, wheres, args = self._week_and_date_ranges(week_range, date_range)
		k_years_away = 500  # limit to 500 year span in either direction, from event; note that date_range may provide a different scope, but who cares: the tightest scope will win
		exids = [event['id']]
		if exclude_ids:
			exids.extend(exclude_ids)
		return (f"select {self.tbl_name}.* from {self.tbl_name} %s where {self.tbl_name}.id not in (%s) %s and {self.tbl_name}.start >= %d and {self.tbl_name}.start <= %d order by random() limit %d" % 
				(' '.join(joins), ', '.join([str(e) for e in exids]), (' and ' + ' and '.join(wheres) if wheres else ''), (event['start'] if event['start'] else event['fake_start_date']) - k_years_away, (event['start'] if event['start'] else event['fake_start_date']) + k_years_away, limit), args)

	def s_get_geography_similar_events(self, event, week_range = None, date_range = None, limit = 5):
		pass #TODO

# SQL Utility Responses subclass cSqlUtilResponses
class cSqlUtilResponses(cSqlUtil):
	async def get_surrounding_responses(self, db, event, week_range = None, date_range = None, count = 5):
		e1 = await (await db.execute(*self.s_get_keyword_similar_responses(event, week_range, date_range, count))).fetchall()
		exids = [e['id'] for e in e1]  # ids to exclude from future search results; we only need any given event once
	

		e2 = await (await db.execute(*self.s_get_temporal_random_responses(event, week_range, date_range, count, exids))).fetchall()
		exids.extend([e['id'] for e in e2])
		keyword_similars, temporal_randoms, random_count = self._get_surrounding_events(e1, e2, count)
		randoms = []
		exids.append(event['id'])
		for i in range(random_count):
			e = await self.get_random_event(db, week_range, date_range, exids)
			if e:
				randoms.append(e)
				exids.append(e['id'])
		result = keyword_similars + temporal_randoms + randoms
		return result

	def s_get_keyword_similar_responses(self, event, week_range = None, date_range = None, limit = 5, exclude_ids = None):
		joins, wheres, args = self._week_and_date_ranges(week_range, date_range, False)
		or_wheres = []
		exids = [event['id']]
		if exclude_ids:
			exids.extend(exclude_ids)
		l.debug(f"select {self.tbl_name}.* from {self.tbl_name} %s where {self.tbl_name}.id not in (%s) %s order by random() limit %d" %
				(' '.join(joins), ', '.join([str(e) for e in exids]), (' and ' + ' and '.join(wheres) if wheres else ''), limit), args)
		return (f"select {self.tbl_name}.* from {self.tbl_name} %s where {self.tbl_name}.id not in (%s) %s order by random() limit %d" %
				(' '.join(joins), ', '.join([str(e) for e in exids]), (' and ' + ' and '.join(wheres) if wheres else ''), limit), args) # consider (postgre)sql functions instead of this giant SQL

	def s_get_temporal_random_responses(self, event, week_range = None, date_range = None, limit = 5, exclude_ids = None):
		joins, wheres, args = self._week_and_date_ranges(week_range, date_range, False)
		l.debug("<< JOINS s_get_temporal_random_responses >> = %s" % list(joins))
		l.debug("<< WHERES >> = %s" % list(wheres))
		k_years_away = 500  # limit to 500 year span in either direction, from event; note that date_range may provide a different scope, but who cares: the tightest scope will win
		exids = [event['id']]
		if exclude_ids:
			exids.extend(exclude_ids)
		return (f"select {self.tbl_name}.* from {self.tbl_name} %s where {self.tbl_name}.id not in (%s) %s order by random() limit %d" %
				(' '.join(joins), ', '.join([str(e) for e in exids]), (' and ' + ' and '.join(wheres) if wheres else ''), limit), args)


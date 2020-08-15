import sqlite3

k_grammar_school_program = 1
k_tutor_role = 4

def go():
	
	db = sqlite3.connect('../ohs-test/ohs-test.db')
	db.row_factory = sqlite3.Row

	# Get total grammar tuitions:
	c = db.execute(f'select amount from cost where program={k_grammar_school_program} and name="tuition"')
	tuition = c.fetchone()['amount']
	c = db.execute(f'select count(*) from enrollment where program={k_grammar_school_program}')
	enrollment = c.fetchone()['count(*)']
	# And tutors:
	c = db.execute(f'select count(*) from leader where program={k_grammar_school_program} and leadership_role={k_tutor_role}')
	grammar_tutor_count = c.fetchone()['count(*)']
	science_coordinator_offset = art_coordinator_offset = tuition * enrollment / enrollment**0.92
	grammar_tutor_offset = int((tuition * enrollment - science_coordinator_offset - art_coordinator_offset) / grammar_tutor_count)
	c = db.execute(f'update leader set annual_offset = {grammar_tutor_offset} where program={k_grammar_school_program} and leadership_role={k_tutor_role}')
	db.commit()


if __name__ == "__main__":
	go()




	"""
	c = db.execute(f'''
			select * from leader
			join leadership_role on leader.leadership_role = leadership_role.id
			where leadership_role.name = "Tutor"
			and program = {k_grammar_school_program}
		''')
	leaders = c.fetchall()
	c = db.execute('''
			select event.*, cycle_week.cycle, cycle_week.week, location.name as location, qr_key.key as qrcode_key, history_cycle_week.cycle as history_cycle, history_cycle_week.week as history_week, history_qr_key_table.key as history_qr_key from event
			join location on region = location.id
			join cycle_week on event.cw = cycle_week.id
			join qr_key on event.qr_key = qr_key.id
			left outer join history on event.id = history.event
			left outer join cycle_week as history_cycle_week on history.cw = history_cycle_week.id
			left outer join qr_key as history_qr_key_table on history.qr_key = history_qr_key_table.id
			where event.subseq is null
			and primary_sentence is not null order by cycle_week.cycle, cycle_week.week, event.seq
		''') # and event.id=152     and event.id in (60, 58, 57, 56, 55, 53, 52, 51)
	"""

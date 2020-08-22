import sqlite3

k_grammar_school_program = 1
k_middle_school_program = 2
k_7_9_program = 3
k_tutor_role = 4

def go(program, reducer = None):
	
	db = sqlite3.connect('../ohs-test/ohs-test.db')
	db.row_factory = sqlite3.Row

	# Get total tuitions:
	c = db.execute(f'select amount from cost where program={program} and name="tuition"')
	tuition = c.fetchone()['amount']
	c = db.execute(f'select count(*) from enrollment where program={program}')
	enrollment = c.fetchone()['count(*)']
	# And tutors:
	c = db.execute(f'select sum(sections*weeks) as tutor_weeks from leader where program={program} and leadership_role={k_tutor_role}')
	tutor_weeks = c.fetchone()['tutor_weeks']
	reductions = 0
	if reducer:
		reductions = reducer(tuition, enrollment)
	tutor_offset = (tuition * enrollment - reductions) / tutor_weeks
	c = db.execute(f'update leader set annual_offset = round(sections * weeks * {tutor_offset}) where program={program} and leadership_role={k_tutor_role}')
	db.commit()

def science_art_coordinators_reducer(tuition, enrollment):
	return 2 * tuition * enrollment / enrollment**0.92 # 2* -- one for science-coordinator and one for art-coordinator

if __name__ == "__main__":
	#go(k_grammar_school_program, science_art_coordinators_reducer)
	#go(k_middle_school_program)
	go(k_7_9_program)

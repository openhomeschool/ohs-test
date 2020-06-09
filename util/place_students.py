

import sqlite3
from datetime import date


db = sqlite3.connect('ohs-test.db', detect_types=sqlite3.PARSE_DECLTYPES)
db.row_factory = sqlite3.Row

academic_year_start = 2020
academic_year_id = 1 # hardcode
graduate_record_id = 6 # hardcode
all_subject_id = 10 # hardcode

cutoff_month, cutoff_day = 10, 1 # be an age by October 1 to be in a program for students that age or older...

programs = db.execute('select * from program order by start_age desc').fetchall()
program_cutoffs = {}
for program in programs:
	program_cutoffs[program['name']] = date(academic_year_start - program['start_age'], cutoff_month, cutoff_day)

for student in db.execute('select * from person where birthdate is not null').fetchall():
	for program in programs: # these are sorted from top to bottom, so...
		if student['birthdate'] < program_cutoffs[program['name']]: # ... this checks against highest programs first; i.e., a 15-year-old won't be placed in grammarschool simply because he's "old enough"... the break, below, gets out of this loop once a student is assigned as high as possible
			#TODO: OOPS!  the above logic does not account for students enrolled in both grammar-school and afternoon middle-school!  Fix someday
			db.execute('insert into enrollment (student, program, subject, academic_year) values (?, ?, ?, ?)', (student['id'], program['id'], all_subject_id, academic_year_id))
			break # student is assigned, move on to next student
db.commit()


# NOTE
# NOTE: first I wrote place_student.py, then I decided to use grade rather than (merely) program (e.g., 7th-9th), so I wrote this to UPDATE the table, and actually removed
# the program field from the table afterward, because we now have the grade_program table in the DB for that mapping.
# For the future, we'll want to simply increment a grade, year over year, and, of course, allow overrides, but this code could still be helpful starter code for auto-handling new
# enrollees.
# NOTE

import sqlite3
from datetime import date


db = sqlite3.connect('ohs-test.db', detect_types=sqlite3.PARSE_DECLTYPES)
db.row_factory = sqlite3.Row

academic_year_start = 2020
academic_year_id = 1 # hardcode
graduate_record_id = 6 # hardcode
all_subject_id = 10 # hardcode

cutoff_month, cutoff_day = 10, 1 # be an age by October 1 to be in a program for students that age or older...
youngest_age, oldest_age = 4, 18
age_grade_map = {start_age: start_age - 5 for start_age in range(youngest_age, oldest_age)}

for student in db.execute('select * from person where birthdate is not null').fetchall():
	age_years = int((date(academic_year_start, cutoff_month, cutoff_day) - student['birthdate']).days / 365)
	print('student %s will be %s years old' % (student['first_name'], age_years))
	grade = age_grade_map.get(age_years, -1)
	print('grade: %s' % grade)
	if grade >= 0:
		print('updating...')
		db.execute('update enrollment set grade = ? where student = ?', (grade, student['id']))
db.commit()

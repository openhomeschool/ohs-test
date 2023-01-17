
import sqlite3
import subprocess

import glob
import time
import os
from os import path

#preload_command = lambda week, left_right, url: ['chromium', '--headless', f'{url}']
chromium_command = lambda pdf_filename, url: ['chromium', '--headless', '--print-to-pdf-no-header', f'--print-to-pdf={pdf_filename}.pdf', f'{url}']
	#chromium --headless --print-to-pdf-no-header --print-to-pdf="test3.pdf" "http://localhost:8000/resources?as_user_id=141&for_print=1"
url = lambda uid, week, subjects: f'http://localhost:8000/resources?as_user_id={uid}&for_print=1&week={week}&subject={subjects}&linear=1' # 'linear=1' forces a linear load; if we wait for the websockets async load of the middle content, sometimes the print happens before the content ever loads (and so we get a blank page)!  NOTE that chrome/chromium args like '--run-all-compositor-stages-before-draw', '--virtual-time-budget=10000' do NOT actually resolve this -- we'd have to figure out how to stall the DOM load completion to capitalize on those, and that's not easy; I tried hard for a long time.  It's no just like a normal "load", like an image or the completion of an inline javascript.

def main():
	db = sqlite3.connect('ohs-test.db')
	db.row_factory = sqlite3.Row
	
	start_week = 13
	end_week = 15
	c = db.execute('''
		select person.first_name, person.last_name, user.id as uid from person
		join enrollment on enrollment.student = person.id
		join user on user.person = person.id
		where enrollment.academic_year=3 and enrollment.program in (3, 4) and enrollment.subject=0
	''')
	#	and person.id = 92

	subjects = {'a': '2,8,4', 'b': '5,7,11,15'} # left-page subjects and right-page-subjects
	try:
		os.mkdir('print-syllabi')
	except:
		pass
	os.chdir('print-syllabi')
	for r in c.fetchall():
		dir_name = f"{r['first_name']}_{r['last_name']}"
		os.mkdir(dir_name)
		os.chdir(dir_name)
		pdfs = []
		for week in range(start_week, end_week+1):
			for left_right in ('a', 'b'):
				fn = f'{week:{0}{2}}{left_right}'
				#args = preload_command(week, left_right, url(r['uid'], week, subjects[left_right]))
				#subprocess.check_call(args)
				args = chromium_command(fn, url(r['uid'], week, subjects[left_right]))
				pdfs.append(fn)
				subprocess.check_call(args)
		#subprocess.check_call(['pdfunite', '*.pdf', 'all.pdf'])
		args = ['pdfunite',]
		#args.extend(glob.glob('*.pdf'))
		args.extend([f'{pdf}.pdf' for pdf in pdfs])
		args.append('all.pdf')
		print(args)
		subprocess.check_call(args)
		finalize(r['first_name'], r['last_name'])
		os.chdir("..")

	os.chdir("..")

def finalize(first_name, last_name):
	with open('../../addpages-bottom-book.tex') as template:
		tex = template.read()
	tex = tex.replace('!!!name!!!', f'{first_name} {last_name}')
	
	final_tex_filename = f'{first_name}-{last_name}.tex'
	with open(final_tex_filename + '.tex', 'w') as texf:
		texf.write(tex)
	# Finally, render the pdf:
	#time.sleep(0.2)
	subprocess.check_call(['pdflatex', final_tex_filename + '.tex', final_tex_filename + '.pdf'])


if __name__ == "__main__":
	main()

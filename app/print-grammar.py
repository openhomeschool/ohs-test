
import sqlite3
import subprocess

import glob
import time
import os
from os import path

#preload_command = lambda week, left_right, url: ['chromium', '--headless', f'{url}']
chromium_command = lambda pdf_filename, url: ['chromium', '--headless', '--print-to-pdf-no-header', f'--print-to-pdf={pdf_filename}.pdf', f'{url}']
	#chromium --headless --print-to-pdf-no-header --print-to-pdf="test3.pdf" "http://localhost:8000/resources?as_user_id=141&for_print=1"

#"normal":
url = lambda week, subjects: f'http://localhost:8000/resources?no_maps=1&for_print=1&week={week}&subject={subjects}&linear=1&secondaries=1' # 'linear=1' forces a linear load; if we wait for the websockets async load of the middle content, sometimes the print happens before the content ever loads (and so we get a blank page)!  NOTE that chrome/chromium args like '--run-all-compositor-stages-before-draw', '--virtual-time-budget=10000' do NOT actually resolve this -- we'd have to figure out how to stall the DOM load completion to capitalize on those, and that's not easy; I tried hard for a long time.  It's no just like a normal "load", like an image or the completion of an inline javascript.
#tutors:
#url = lambda week, subjects: f'http://localhost:8000/resources?no_maps=1&for_print=1&week={week}&timeline_sentences=1&subject={subjects}&linear=1' # 'linear=1' forces a linear load; if we wait for the websockets async load of the middle content, sometimes the print happens before the content ever loads (and so we get a blank page)!  NOTE that chrome/chromium args like '--run-all-compositor-stages-before-draw', '--virtual-time-budget=10000' do NOT actually resolve this -- we'd have to figure out how to stall the DOM load completion to capitalize on those, and that's not easy; I tried hard for a long time.  It's no just like a normal "load", like an image or the completion of an inline javascript.
#high-schoolers:
#url = lambda week, subjects: f'http://localhost:8000/resources?no_maps=1&for_print=1&week={week}&timeline_sentences=1&subject={subjects}&linear=1&secondaries=1' # 'linear=1' forces a linear load; if we wait for the websockets async load of the middle content, sometimes the print happens before the content ever loads (and so we get a blank page)!  NOTE that chrome/chromium args like '--run-all-compositor-stages-before-draw', '--virtual-time-budget=10000' do NOT actually resolve this -- we'd have to figure out how to stall the DOM load completion to capitalize on those, and that's not easy; I tried hard for a long time.  It's no just like a normal "load", like an image or the completion of an inline javascript.

def main():
	title = 'Grammar'
	# one-page:
	left_right_groups = ('a')
	subjects = {'a': '1,2,3,4,5,6,7'} # left-page subjects and right-page-subjects
	# two-page:
	#left_right_groups = ('a', 'b')
	#subjects = {'a': '1,2,3', 'b': '4,5,6,7'} # left-page subjects and right-page-subjects
	
	os.mkdir('print-grammar-outputs/' + title)
	os.chdir('print-grammar-outputs/' + title)

	first_week = 13
	last_week = 28
	pdfs = []
	for week in range(first_week, last_week+1):
		for left_right in left_right_groups:
			fn = f'{week:{0}{2}}{left_right}'
			args = chromium_command(fn, url(week, subjects[left_right]))
			pdfs.append(fn)
			subprocess.check_call(args)
	args = ['pdfunite',]
	args.extend([f'{pdf}.pdf' for pdf in pdfs])
	args.append('all.pdf')
	print(args)
	subprocess.check_call(args)

	with open('../../addpages-bottom-book-grammar.tex') as template:
		tex = template.read()
	tex = tex.replace('!!!name!!!', title)
	
	final_tex_filename = f'grammar.tex'
	with open(final_tex_filename + '.tex', 'w') as texf:
		texf.write(tex)
	subprocess.check_call(['pdflatex', final_tex_filename + '.tex', final_tex_filename + '.pdf'])

	os.chdir("../..")




if __name__ == "__main__":
	main()

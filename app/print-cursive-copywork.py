
import sqlite3
import subprocess

import glob
import time
import os
from os import path


def _prefix_answer(record):
	answer_prompt = record['answer_prefix'].capitalize() + ' ' + record['prompt'] if record['answer_prefix'] else record['prompt'].capitalize()
	answer = '%s %s %s.' % (answer_prompt, record['answer_verb'], record['answer'])
	return answer

def main():

	title = 't1'

	db = sqlite3.connect('../ohs-test.db')
	db.row_factory = sqlite3.Row

	root = '../print-cursive-copywork/'
	try:
		os.mkdir(root + title)
	except:
		pass
	os.chdir(root + title)

	cycle = 3
	first_week = 13
	last_week = 28
	pdfs = []
	escape = lambda s: s.replace('\\', '').replace('&', '\&')
	for week in range(first_week, last_week+1):
		with open('../../cursive-copywork-template.tex') as template:
			tex = template.read()
		tex = tex.replace('!!!title!!!', f'C3 Week {week}')

		c = db.execute(f'select name from event join cycle_week on event.cw = cycle_week.id where cycle_week.cycle = 0 and cycle_week.week = {week} order by seq')
		prefix = '..., ' if week != 0 else ''
		postfix = ', ...' if week != 28 else ''
		tex = tex.replace('!!!timeline!!!', prefix + ', '.join([escape(r['name']) for r in c.fetchall()]) + postfix)

		c = db.execute(f'select primary_sentence from event join history on history.event = event.id join cycle_week on history.cw = cycle_week.id where cycle_week.cycle = {cycle} and cycle_week.week = {week}')
		tex = tex.replace('!!!history!!!', escape(c.fetchone()['primary_sentence']))

		c = db.execute(f'select name from location join cycle_week on location.cw = cycle_week.id where cycle_week.cycle = {0 if week == 1 else cycle} and cycle_week.week = {week} order by seq')
		tex = tex.replace('!!!geography!!!', ', '.join([escape(r['name']) for r in c.fetchall()]))

		c = db.execute(f'select answer_prefix, prompt, answer_verb, answer from science join cycle_week on science.cw = cycle_week.id where cycle_week.cycle = {cycle} and cycle_week.week = {week}')
		tex = tex.replace('!!!science!!!', escape(_prefix_answer(c.fetchone())))

		c = db.execute(f'select answer from english_grammar_reference join english_grammar_example on english_grammar_example.english_grammar_reference = english_grammar_reference.id join cycle_week on english_grammar_example.cw = cycle_week.id where cycle_week.cycle = {cycle} and cycle_week.week = {week}')
		tex = tex.replace('!!!english!!!', escape(c.fetchone()['answer']))
	
		c = db.execute(f'select word, definition from vocabulary join cycle_week on vocabulary.cw = cycle_week.id where cycle_week.cycle = {cycle} and cycle_week.week = {week} order by position')
		tex = tex.replace('!!!english_vocab!!!', ' \\\\ '.join([f"{r['word']} = {r['definition']}" for r in c.fetchall()]))
	
		c = db.execute(f'select name, pattern from latin_grammar_reference join latin_grammar_example on latin_grammar_example.latin_grammar_reference = latin_grammar_reference.id join cycle_week on latin_grammar_example.cw = cycle_week.id where cycle_week.cycle = {cycle} and cycle_week.week = {week}')
		latin = c.fetchone()
		tex = tex.replace('!!!latin!!!', f"{latin['name']}: {latin['pattern']}")
	
		c = db.execute(f'select word, translation from latin_vocabulary join cycle_week on latin_vocabulary.cw = cycle_week.id where cycle_week.cycle = {cycle} and cycle_week.week = {week} order by position')
		tex = tex.replace('!!!latin_vocab!!!', ' \\\\ '.join([escape(f"{r['word']} = {r['translation']}") for r in c.fetchall()]))
	
		final_tex_filename = f'c{cycle}w{week}_grammar_copywork'
		with open(final_tex_filename + '.tex', 'w') as texf:
			texf.write(tex)
		subprocess.check_call(['xelatex', final_tex_filename + '.tex', final_tex_filename + '.pdf'])
		pdfs.append(final_tex_filename + '.pdf')

	args = ['pdfunite',]
	#args.extend(glob.glob('*.pdf'))
	args.extend([pdf for pdf in pdfs])
	args.append(f'c{cycle}w{first_week}-{last_week}_grammar_copywork.pdf')
	subprocess.check_call(args)

	os.chdir("../..")




if __name__ == "__main__":
	main()

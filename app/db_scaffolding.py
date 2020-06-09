

'''
Some sql.py functions just generate sql.  So, to test, you could simply:

	>>> import sqlite3
	>>> from app import sql # our sql.py, that is
	>>> db = sqlite3.connect('test.db')
	>>> db.row_factory = sqlite3.Row
	>>> c = db.execute(sql.get_random_science_records(...))
	
For that function and others, you may have to fabricate a "spec" argument, like this:

	>>> from dataclasses import dataclass
	>>> @dataclass
	... class Spec:
	...   table: str
	...   cycles: tuple = (0, 1)
	...   week_range: tuple = (1, 2)
	>> s = sql.get_random_science_records(Spec('science'), 1)

But some of the functions are async functions that call on the aiosqlite
interface, and the calls are not easy to tease apart to mimic a synchronous
equivalent.  The purpose of this scaffolding is to make it easier to call
individual functions to debug.  Here's how it typically works.

Write your prototype funciton in sql.py, like:

	async def foo(db, arg1, arg2):
		...
		c = await db.execute(sql, args)
		return await c.fetchall()

This is your function that is likely to become a "real" production function,
but you're just working on it, and want to debug and design.  So, after
getting it started, to try it out from a command-line, do this:

	>>> from app import db_scaffolding as dbs
	>>> tl = dbs.Test_Loop()
	>>> from app import sql
	>>> result = tl.run(sql.foo, arg1, arg2) # Note that you do NOT provide db, just the args in your foo() **after** that first db arg

In this example case, `result` holds the result of the fetchall() -- the records fetched.  You can do as you wish with them at that point.

You may call tl.run() many times, and with many different functions you've written, either in sql.py or just manually, or elsewhere
for that matter.  The main expectation is that the function wrapped in run() will take a db object as the first argument.  This is
because the db object has to be created within Test_Loop(), as initialization of the aiosqlite DB is also an async operation, so it
has to happen in the run(), or within the event loop, anyway.

You may want to explicitly delete tl, your test-loop object, because the __del__ will close() the asyncio loop properly.

'''

import asyncio
import aiosqlite

from . import main

class Test_Loop:
	
	def __init__(self):
		self.loop = asyncio.new_event_loop()
		self.db = None

	def __del__(self):
		self.loop.close()

	async def wrap(self, func, *args, **kwargs):
		if not self.db:
			self.db = await main.init_db('ohs-test.db')
		return await func(self.db, *args, **kwargs)

	def run(self, func, *args, **kwargs):
		return self.loop.run_until_complete(self.wrap(func, *args, **kwargs))


__author__ = 'J. Michael Caine'
__copyright__ = '2020'
__version__ = '0.1'
__license__ = 'MIT'


# For reference only:
def get_test1_SYNCHRONOUS(db, id):
	return db.execute('select * from test1 where id=? limit 1', (id,)).fetchone()

# The equivalent async:
_get_test1 = lambda id: ('select * from test1 where id=? limit 1', (id,))
async def get_test1(db, id):
	c = await db.execute(*_get_test1(id))
	return await c.fetchone()

_get_test1_limited = lambda limit: ('select * from test1 limit ?', (limit,))
async def get_test1_limited(db, limit):
	c = await db.execute(*_get_test1_limited(limit))
	return await c.fetchall()

_create_test1 = lambda value: ('insert into test1(name) values (?)', (value,))
async def create_test1(db, value):
	c = await db.execute(*_create_test1(value))

_update_test1 = lambda id, value: ('update test1 set name=? where id=?', (value, id))
async def update_test1(db, id, value):
	c = await db.execute(*_update_test1(id, value))

_find_test1 = lambda like: ('select * from test1 where name like ?', ('%' + like + '%',))
async def find_test1(db, like):
	c = await db.execute(*_find_test1(like))
	return await c.fetchall()

__author__ = 'J. Michael Caine'
__copyright__ = '2020'
__version__ = '0.1'
__license__ = 'MIT'

import asyncio
import logging
import aiosqlite
import re
import weakref

from aiohttp import web, WSMsgType, WSCloseCode

from . import html
from . import db

_debug = True # TODO: parameterize!

# Logging ---------------------------------------------------------------------

logging.basicConfig(format = '%(asctime)s - %(levelname)s : %(name)s:%(lineno)d -- %(message)s', level = logging.DEBUG if _debug else logging.INFO)
l = logging.getLogger(__name__)

# Utils -----------------------------------------------------------------------

r = web.RouteTableDef()
def hr(text): return web.Response(text = text, content_type = 'text/html')

# Handlers --------------------------------------------------------------------

@r.get('/test1')
async def test1(request):
	r1 = await db.get_test1(request.app['db'], 1) # test code; assumes a record with id=1 exists
	return hr(html.test1_basic(r1))


@r.view('/new_test1')
class New_Test1(web.View):
	async def get(self):
		return hr(html.test1(html.Form(self.request.path), 'New', 'Create'))
	
	async def post(self):
		r = self.request
		data = await r.post()
		await db.create_test1(r.app['db'], data['name'])
		return hr(html.success()) # lame placeholder

		# TODO: Use shield() to write regardless of an unexpected closed connection:
		# await asyncio.shield(db.insert_or_update(data['input1']))
		# Otherwise, use aiojobs.aiohttp @atomic decorator to guard entire post handler (which prevents all handler (async) code from cancellation; it doesn't lock aio into an atomic mutex like it might suggest; this is all about cancellation-protection *only*)


@r.view('/edit_test1/{id}')
class Edit_Test1(web.View):
	async def get(self):
		r = self.request
		id = r.match_info['id']
		record = await db.get_test1(r.app['db'], id)
		l.debug(record['name'])
		return hr(html.test1(html.Form(r.path, {'name': record['name']}), 'Edit', 'Save'))
	
	async def post(self):
		r = self.request
		data = await r.post()
		# TODO: validate/sanitize `data`
		await db.update_test1(r.app['db'], r.match_info['id'], data['name'])
		return hr(html.success()) # lame placeholder

	
@r.get('/select_test1')
async def select_test1(request):
	ws_url = re.sub('.*://', 'ws://', str(request.url)) # swap ws:// in for current scheme (http:// or https://, presumably)
	ws_url = re.sub('%s$' % request.rel_url, '/ws_search_test1', ws_url)
	return hr(html.select_test1(ws_url))


@r.get('/ws_search_test1')
async def ws_search_test1(request):
	ws = web.WebSocketResponse()
	await ws.prepare(request)
	request.app['websockets'].add(ws)
	edit_url = re.sub('.*://', 'http://', str(request.url)) # swap http:// in for current scheme (ws://) - note: what about HTTPs!?TODO
	edit_url = re.sub('%s$' % request.rel_url, '/edit_test1', edit_url)
	# Pre-populate list with subset of record list:
	default_list = await db.get_test1_limited(request.app['db'], 10)
	await ws.send_str(html.list_test1(default_list, edit_url))
	
	l.debug('Websocket prepared, listening for messages...')
	try:
		async for msg in ws:
			#l.debug('WS message (%s): %s' % (msg.type, msg.data))
			try:
				if msg.type == WSMsgType.text:
					#TODO: Validate each msg in ws as search string (use Schema(valid_search_string())?
					if msg.data:
						records = await db.find_test1(request.app['db'], msg.data)
					else:
						records = default_list
					await ws.send_str(html.list_test1(records, edit_url))
				elif msg.type == aiohttp.WSMsgType.ERROR:
					l.warning('websocket connection closed with exception "%s"' % ws.exception())
				else:
					l.warning('websocket message of unexpected type "%s" received' % msg.type)

			except Exception as e: # per-message exceptions:
				l.error('Exception (%s: %s) during WS message processing; continuing on...' % (str(e), type(e)))

	except Exception as e:
		l.error('Exception (%s: %s) processing WS messages; shutting down WS...' % (str(e), type(e)))
		raise

	finally:
		request.app['websockets'].discard(ws) # in finally block to ensure that this is done even if an exception propagates out of this function

	return ws


# Init / Shutdown -------------------------------------------------------------

async def init_db(app):
	db = await aiosqlite.connect('test1.db', isolation_level = None) # isolation_level: autocommit
		# non-async equivalent would have been: db = sqlite3.connect('test1.db', isolation_level = None) # isolation_level: autocommit
	db.row_factory = aiosqlite.Row
	await db.execute('pragma journal_mode = wal') # see https://charlesleifer.com/blog/going-fast-with-sqlite-and-python/ - since we're using async/await from a wsgi stack, this is appropriate
	#await db.execute('pragma case_sensitive_like = true')
	#await db.set_trace_callback(l.debug) - not needed with aiosqlite, anyway
	app['db'] = db
	l.debug('Database initialized')

async def shutdown(app):
	await app['db'].close()
	for ws in set(app['websockets']):
		await ws.close(code = WSCloseCode.GOING_AWAY, message = 'Server shutdown')
	l.debug('Shutdown complete')

# Run server like so, from cli:
#		python -m aiohttp.web -H localhost -P 8080 main:init
# Or, using adev (from parent directory!):
#		adev runserver --app-factory init --livereload --debug-toolbar test1_app
def init():
	app = web.Application()
	app.update(
		websockets = weakref.WeakSet(),
		#static_path='static/', ??
		#static_url='/static/', ??
	)
	app.add_routes(r)
	app.on_startup.append(init_db)
	app.on_shutdown.append(shutdown)
	return app

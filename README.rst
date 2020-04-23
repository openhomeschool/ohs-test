aiohttp-sqlite-dominate-stack-reference
=======================================

**aiohttp-sqlite-dominate-stack-reference** is a skeletal implementation of an
aiohttp-based web application that uses sqlite (aiosqlite_, actually) for the
database access and dominate_ for HTML generation (rather than a templating
language/tool).  The feature set is intentionally vapid, meant only to
demonstrate the basics and offer a starting-point.

Install and Configuration
-------------------------
::

	$ pip install aiohttp-sqlite-dominate-stack-reference
	$ cd aiohttp_sqlite_dominate_stack_reference
	$ pip install -r requirements.txt

Create the tiny starter reference database::

	$ cat test1.sql | sqlite3 test1.db

And run your app::

	$ python -m aiohttp.web -H localhost -P 8080 test1_app.server:init
	
(Or, with aiohttp-devtools_)::

	adev runserver --app-factory init --livereload test1_app

(Other adev options may be desirable, and additions like aiohttp_debugtoolbar_ might 
	

ohs-test
========

**ohs-test** is the practice / quiz / test server for openhome.school
grammar.

Install and Configuration
-------------------------
::

	$ pip install ohs-test
	$ cd ohs-test
	$ pip install -r requirements.txt

Create the reference database::

	$ cat seed.sql | sqlite3 main.db

And run your app::

	$ python -m aiohttp.web -H localhost -P 8080 app.main:init
	
(Or, with `aiohttp-devtools <https://github.com/aio-libs/aiohttp-devtools>`_)::

	$ adev runserver --livereload app

(Other adev options may be desirable, and additions like 
`aiohttp-debugtoolbar <https://github.com/aio-libs/aiohttp-debugtoolbar>`_
might be useful.)
	
License
-------

This project is licensed under the terms of the MIT license.

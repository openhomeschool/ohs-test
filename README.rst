ohs-test
========

**ohs-test** is the practice / quiz / test server for openhome.school
grammar.

Install and Configuration
-------------------------
::

	$ python3 -m venv ve
	$ . ve/bin/activate
	$ pip install --upgrade pip
	$ git clone https://github.com/openhomeschool/ohs-test.git
	$ cd ohs-test/
	$ pip install -r requirements.txt

(Note, the pip install may rely on apt-installs like libffi-dev, ...)

Create the database::

	$ cat ohs-test.sql | sqlite3 ohs-test.db

And run your app::

	$ python -m aiohttp.web -H localhost -P 8080 app.main:init
	
(Or, with `aiohttp-devtools <https://github.com/aio-libs/aiohttp-devtools>`_)::

	$ adev runserver -s static --livereload app

The adev server will run on port 8000 by default.  Other adev options may be
desirable, and additions like
`aiohttp-debugtoolbar <https://github.com/aio-libs/aiohttp-debugtoolbar>`_
might be useful.
	
License
-------

This project is licensed under the terms of the MIT license.

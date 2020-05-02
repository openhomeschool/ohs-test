__author__ = 'J. Michael Caine'
__copyright__ = '2020'
__version__ = '0.1'
__license__ = 'MIT'

import re

re_alphanum = re.compile(r'^[\w ]+$')
re_username = re.compile(r'^[\w\-_]{1,16}$')
re_password = re.compile(r'^.{4,32}$')
re_email = re.compile(r'(^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$)') # TODO: how can I limit overall length?
re_slug = re.compile(r'^[\w\-_]{2,32}$')

inv_username = "Username must be a single word (no spaces) made of letters and/or numbers, 16 characters or less."
inv_password = "Password can be made of letters, numbers, and/or symbols, and must be between 4 and 32 characters long."
inv_password_confirmation = "Password and password confirmation entries must be exactly the same."
inv_email = "Email address must be a valid user@domain.tld format, 64 characters or less."

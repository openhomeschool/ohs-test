__author__ = 'J. Michael Caine'
__copyright__ = '2020'
__version__ = '0.1'
__license__ = 'MIT'

import re

re_string32 = r'^.{1,32}$'
rec_string32 = re.compile(re_string32)
re_alphanum = r'^[\w ]+$'
rec_alphanum = re.compile(re_alphanum)
re_username = r'^[\w\-_]{1,16}$'
rec_username = re.compile(re_username)
re_password = r'^.{4,32}$'
rec_password = re.compile(re_password)
re_email = r'(^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$)' # TODO: how can I limit overall length?
rec_email = re.compile(re_email)
re_slug = r'^[\w\-_]{2,32}$'
rec_slug = re.compile(re_slug)

inv_username = "Username must be a single word (no spaces) made of letters and/or numbers, 16 characters or less."
inv_username_exists = "Sorry, this username is already in use by somebody else.  Please add more characters or try another."
inv_password = "Password can be made of letters, numbers, and/or symbols, and must be between 4 and 32 characters long."
inv_password_confirmation = "Password and password confirmation entries must be exactly the same."
inv_email = "Email address must be a valid user@domain.tld format, 64 characters or less."

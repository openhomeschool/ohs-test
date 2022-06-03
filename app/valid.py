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
re_invitation = r'^.{12,12}$'
rec_invitation = re.compile(re_invitation)

k_res_prefix = 'res-'
re_resource_id_div = r'^%s(\d+)$' % k_res_prefix
rec_resource_id_div = re.compile(re_resource_id_div)


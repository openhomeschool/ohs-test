import bcrypt
from getpass import getpass

# Get Password & Encrypt
master_secret_key = getpass()
salt = bcrypt.gensalt()
pw = bcrypt.hashpw(master_secret_key.encode(), salt)

## Username & Password needs to be stored somewhere

# For checking future logins
## `pw` would be retrieved from a db, I would prefer keyring APIs
password_prompt = getpass()
if bcrypt.checkpw(password_prompt.encode(), pw):
    print('success!!')

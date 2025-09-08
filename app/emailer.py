
import smtplib

from . import settings

def send_email(to, subject, body):
	server = smtplib.SMTP('localhost',25)
	if not settings.debug:
		server.starttls()
	server.sendmail('noreply@openhome.school', to, f'Subject: {subject}\n\n{body}')

'''
followed https://www.digitalocean.com/community/tutorials/how-to-install-and-configure-postfix-as-a-send-only-smtp-server-on-debian-9

had to move /etc/postfix/ off to /etc/postfix_ARCHIVE_FULLER -- as I'd done quite a bit of setup with virtual (mysql) mailboxes and such that I'd abandoned,
and was befuddled at trying to make "just work" again.

So, mail is "loopback-only" (inet_interfaces setting in main.cf), and postmaster is root and root is jmcaine@caines.us in /etc/aliases.  Simple setup.

Also, follwed https://wiki.debian.org/opendkim to set up dkim, then had to chat with support on namecheap.com to get the TXT record correct, but it worked!
gmail sees the dkim correctly and "passes" the message
'''

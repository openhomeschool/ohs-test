
import smtplib

from . import settings

def send_email(to, subject, body):
	server = smtplib.SMTP('localhost',25)
	if not settings.debug:
		server.starttls()
	server.sendmail('noreply@openhome.school', to, f'Subject: {subject}\n\n{body}')

from twisted.internet import reactor, defer
from twisted.mail.smtp import sendmail
from email.mime.base import MIMEBase
from email.encoders import encode_base64
from email.utils import COMMASPACE, formatdate
from email.mime.multipart import MIMEMultipart
from functools import wraps
import jinja2
import os

try:
	import ujson as json
except:
	import json

def EMAILattach(filename,fp, mimetype = ("application", "octet-stream")):
	at = MIMEBase(*mimetype)
	at.set_payload(fp.read())
	encode_base64(at)
	at.add_header("Content-Disposition", "attachment", filename= filename)
	return at

def render(tpl_path, context):
	path, filename = os.path.split(tpl_path)
	return jinja2.Environment(
			loader=jinja2.FileSystemLoader(path or './')
				).get_template(filename).render(context).encode('utf-8')


def safetyCall(func):
	@wraps(func)
	def decorator(*args,**kwargs):
		reactor.callFromThread(func,*args,**kwargs)
	return decorator


def saveConfigFile(cfg, path):
	with open(path, "w") as file_:
		file_.write(json.dumps(cfg,sort_keys=True, indent=4))
		
def loadConfigFile( path):
	with open(path) as data_file: 
		return json.loads(data_file.read())
	
	
def checkAndCreateDir(path):
	if not os.path.exists(path):
		os.makedirs(path)
	
def send_notify_mail(subject,attachments = []):
	me = CONFIG["email_profile"]["login"]
	to = CONFIG["email_profile"]["list_receivers"]
	
	msg = MIMEMultipart()
	msg['From'] = me
	msg['To'] = COMMASPACE.join(to)
	msg['Date'] = formatdate(localtime=True)
	msg['Subject'] = subject
	
	for attach in attachments:
		msg.attach(attach)
		
	
	
	d = sendmail(CONFIG["email_profile"]["remote_host"], me, to, msg.as_string(),
			port=CONFIG["email_profile"]["remote_port"], username=me, password=CONFIG["email_profile"]["password"],
				requireAuthentication=True,
					requireTransportSecurity=True)

	@d.addBoth
	def _print(res):
		print(res)
	return d

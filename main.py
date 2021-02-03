#coding:utf-8
from __future__ import print_function
from zope.interface import implementer
from twisted.web import error, resource
from twisted.internet import reactor, defer
from twisted.web import static, server, resource

from twisted.cred import portal, checkers, credentials, error as credError
from twisted.web.guard import HTTPAuthSessionWrapper
from twisted.web.guard import DigestCredentialFactory
from twisted.web.guard import BasicCredentialFactory
from twisted.internet.threads import deferToThread



import twisted.python.log as log

from email.mime.application import MIMEApplication

from email.mime.text import MIMEText
from email.mime.image import MIMEImage



from modules import telegram as t
from modules.camservice import CamService, StopCamera, c
from modules.utils import (EMAILattach, render, safetyCall, checkAndCreateDir,
							send_notify_mail, loadConfigFile, saveConfigFile)
from modules.streaming import MJPEGStreamProducer


import logging
import datetime
import time
import os
import sys

import traceback
import cStringIO as io

from functools import wraps


try:
	import ujson as json
except:
	import json

makeJson = lambda data : json.dumps(data)

import __builtin__


handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

_log = logging.getLogger('twisted_routes')
_log.setLevel(logging.INFO)
_log.addHandler(handler)

observer = log.PythonLoggingObserver(loggerName='twisted_routes')
observer.start()

CAMS_LIST = []

CONFIG = {}

CONF_FILE = "config.json"


CONFIG = loadConfigFile(CONF_FILE)
__builtin__.CONFIG = CONFIG

checkAndCreateDir(CONFIG["etc"])


tg = t.TelegramBot(CONFIG["telegram"]["token"],
				   proxy=CONFIG["telegram"].get("proxy", None)
				   )


def admin_access(fn):
	@wraps(fn)
	def decorator(bot, rawMsg, text):
		if rawMsg["from"]["id"] in CONFIG["telegram"]["authd_users"]:
			fn(bot, rawMsg, text)
		else:
			bot.sendMessage(rawMsg["chat"]["id"], "Not allowed")
	return decorator



















#####################################################################3





class HwStatus(resource.Resource):
	
	def render_GET(self,request):
		request.setHeader("User-Agent", "TwistedWeb")
		method = request.args.get("subject",("all",))[0]
		
		


class HttpCameraApi(resource.Resource):

	def __init__(self, cams):
		self.cams = cams
	
	def mjpg_stream(self, camera, request, framerate):
		request.setHeader("Content-Type", "multipart/x-mixed-replace; boundary=--jpgboundary")
		streamer = MJPEGStreamProducer(request, camera, framerate)
		streamer.stopHeader()
		request.registerProducer(streamer, False)
		return server.NOT_DONE_YET
	
	
	
	def render_GET(self, request):
		request.setHeader("User-Agent", "TwistedWeb")
		method = request.args.get("method",(None,))[0]
		cam_index = request.args.get("index",(None,))[0]
		
		if not (cam_index and cam_index.isdigit()):
			request.setResponseCode(404)
			return "<b>Set camers num!</b>"
		cam_index = int(cam_index)
		try:
			cam_svrs = self.cams[cam_index] 
		except IndexError:
			request.setResponseCode(404)
			return "<b>Cam index out of range</b>"
		if (cam_svrs.cam_is_run == False):
				request.setResponseCode(410)
				return "<b>Camera not worked</b>"
		
		
		
		
		if method == None: 									# method return html 
			btn_text = ""
			if cam_svrs.cam_thread.isEnabledDetect():
				btn_text = u"Выключить детектор" 
			else:
				btn_text = u"Включить детектор" 
			return render("resource/view/index.html", 
				 {"cam":cam_index,"button_state": btn_text})
		
		
		
		elif method == "stream": 								#method return mjpg stream with set fps 
			return self.mjpg_stream(cam_svrs, request, None)
		
		
		
		
		elif method == "state":#method return state from cam {rect,detectstate,???} 
			state = cam_svrs.cam_thread.getState()
			return makeJson(state)
		
		elif method == "snapshot":
			request.setHeader("Content-Type","image/jpg")
			request.setHeader("Content-Disposition", "attachment; filename=\"snapsot_{0:%m-%d-%y %H:%M:%S}.jpg\"".format(datetime.datetime.now()))
			return cam_svrs.last_frame
		
		else:
			request.setResponseCode(405)
			return "<b>Method not suported</b>"
		
	def render_POST(self, request):
		request.setHeader("User-Agent", "TwistedWeb")
		method = request.args.get("method",(None,))[0]
		cam_index = request.args.get("index",(None,))[0]
		sens = request.args.get("sens",(None,))[0]
		rectangle = request.args.get("area[]",[])
		print(rectangle) 
		if rectangle and len(rectangle) == 4:
			try:
				rectangle = map(int, rectangle)
				rectangle = c.Rect(*rectangle)
			except:
				log.err()
				rectangle = None
		else :
			rectangle = None
		
		print(rectangle)
		if not (cam_index and cam_index.isdigit()):
			request.setResponseCode(405)
			return "<b>Set camers num!</b>"
		cam_index = int(cam_index)
		try:
			cam_svrs = self.cams[cam_index] 
		except IndexError:
			request.setResponseCode(405)
			return "<b>Cam index out of range</b>"
		
		
		if method == "detection":
			type_ = request.args.get("type",("trigerred",))[0]
			
			if type_ == "trigerred":
				if cam_svrs.cam_thread.isEnabledDetect():
					cam_svrs.disableMotiomDetect()
					return makeJson({"state" : "off"})
				else:
					cam_svrs.enableMotionDetect(rect = rectangle)
					return makeJson({"state" : "on"})
					
			elif type_ == "on":
					cam_svrs.enableMotionDetect(rect = rectangle)
					return makeJson({"state" : "off"})
			elif type_ == "off" :
					cam_svrs.disableMotiomDetect()
					return makeJson({"state" : "on"})
			else:
				request.setResponseCode(405)
				return "<b>Type of method not suported</b>"
			
		elif method == "record":
			type_ = type_ = request.args.get("type",(None,))[0]
			if type_ == "start":
				path = CONFIG["etc"] + "/" + CONFIG["records"] + "/" + "record_cam_0_{0:%m-%d-%y %H:%M:%S}.mp4".format(datetime.datetime.now())
				cam_svrs.cam_thread.startRecord(path)
			
			elif type_ == "stop":
				cam_srvs.cam_thread.stopRecord()
		else:
			request.setResponseCode(405)
			return "<b>Method not suported</b>"
		
@implementer(checkers.ICredentialsChecker)
class PasswordDictChecker:
	credentialInterfaces = (credentials.IUsernamePassword,credentials.IUsernameHashedPassword)

	def __init__(self, passwords):
		self.passwords = passwords

	def requestAvatarId(self, credentials):
		username = credentials.username
		if self.passwords.has_key(username):
			if credentials.checkPassword(self.passwords[username]):
				return defer.succeed(username)
			else:
				return defer.fail(
					credError.UnauthorizedLogin("Bad password"))
		else:
			return defer.fail(
				credError.UnauthorizedLogin("No such user"))

@implementer(portal.IRealm)
class HttpPasswordRealm(object):
	

	def __init__(self, myresource):
		self.myresource = myresource
	
	def requestAvatar(self, user, mind, *interfaces):
		if resource.IResource in interfaces:
			return (resource.IResource, self.myresource, lambda: None)
		raise NotImplementedError()


def cleanup():
	for c in CAMS_LIST:
		c.cam_thread.stop()





#########################################################################


@defer.inlineCallbacks
def emailNotifyDetector(cam_service):
	
	file_name = "{:%H:%M:%S}".format(datetime.datetime.now())
	
	video_name = file_name+".mp4"
	image_name = file_name+".jpeg"
	
	path_save_video = os.path.join(CONFIG["etc"],
								str(cam_service.index),
								CONFIG["motion_video"],
								"{:%d-%m-%Y}".format(datetime.datetime.now()))
	
	path_save_image = os.path.join(CONFIG["etc"],
								str(cam_service.index),
								CONFIG["motion_screenshot"],
								"{:%d-%m-%Y}".format(datetime.datetime.now()))
	

	
	try:
		frame = yield cam_service.waitForUpdate() #get frame 
	except:
		frame = cam_service.last_frame
	
	@reactor.callInThread  
	def _save(): #save frame to history
		checkAndCreateDir(path_save_image)
		with open(path_save_image+"/"+image_name,"w") as f:
			f.write(frame)
			
	cam_service.recordVideo(60)
		
	yield cam_service.stack_frame.counter(10) #clock 10 frames
	checkAndCreateDir(path_save_video)
	yield cam_service.stack_frame.saveVideo(path_save_video+"/"+video_name) #convert stack frame to video h264
	try:
		attachments = [] #create attachments for mail
		attachments.append((yield deferToThread(EMAILattach,image_name,io.StringIO(frame)))) #attach frame to mail
		try:
			attachments.append((yield deferToThread(EMAILattach, video_name, open(path_save_video+"/"+video_name, "rb")))) #attach video from file to mail
		except:
			pass
		attachments.append(MIMEText("Обнаружено движение!")) #attach text t mail
		send_notify_mail("Уведомление системы безопасности",attachments) #send mail
	except Exception as e:
		traceback.print_exc() #TODO hack

@defer.inlineCallbacks
def telegramNotifyDetector(c):
	try:
		frame = yield c.waitForUpdate()
	except:
		frame = c.last_frame
	for user in CONFIG["telegram"]["notified_users"]:
		tg.sendPhoto(user, frame, u"Уведомление системы: Камера {} обнаружила движение!".format(c.index))
	
	

###########################################################################


		
		
def getCamsMenu(cam, level):
	kbd = t.InlineKeyboardMarkup()
	cam_srvs = CAMS_LIST[int(cam)]
	if level == "0":
		kbd.addInlineButton(u"Сделать снимок", "action{}-snapshot".format(cam))
		kbd.addInlineButton(u"Записать видео", "cammenu{}-1".format(cam))
		kbd.newLine()
		kbd.addInlineButton(u"Детектор движения", "cammenu{}-2".format(cam))
		kbd.newLine()
		if cam_srvs.cam_is_run:
			kbd.addInlineButton(u"Выключить камеру", "action{}-poweroff".format(cam))
		else:
			kbd.addInlineButton(u"Включить камеру", "action{}-poweron".format(cam))
		kbd.newLine()
		
		kbd.addInlineButton(u"<< Вернутся назад", "cammenu-3")
		return u"Список опций для камеры {}".format(cam), kbd
	
	elif level == "1":
		kbd.addInlineButton(u"10сек", "action{}-record10".format(cam))
		kbd.addInlineButton(u"30сек", "action{}-record30".format(cam))
		kbd.newLine()
		kbd.addInlineButton(u"1мин", "action{}-record60".format(cam))
		kbd.addInlineButton(u"1м30с", "action{}-record90".format(cam))
		kbd.newLine()
		kbd.addInlineButton(u"2м", "action{}-record120".format(cam))
		kbd.addInlineButton(u"3м", "action{}-record180".format(cam))
		kbd.newLine()
		kbd.addInlineButton(u"5м", "action{}-record300".format(cam))
		kbd.addInlineButton(u"7м", "action{}-record420".format(cam))
		kbd.newLine()
		kbd.addInlineButton(u"<< Назад", "cammenu{}-0".format(cam))
		return u"Записать видео длительностью...", kbd
		
	elif level == "2":
		if cam_srvs.cam_thread.isEnabledDetect():
			kbd.addInlineButton(u"Выключить детектор движения", "action{}-motionoff".format(cam))
		else:
			kbd.addInlineButton(u"Включить детектор движения", "action{}-motionon".format(cam))
		kbd.newLine()
		kbd.addInlineButton(u"<< Назад", "cammenu{}-0".format(cam))
		return u"Детктор движения камеры {}".format(cam), kbd
			

def getFilesList(from_id, path):
	pass
	

def getOptMenuByLevel(from_id, level):
	print(from_id, level)
	kbd = t.InlineKeyboardMarkup()
	if level == "0":
		kbd.addInlineButton(u"Ститистика", "cammenu-1")
		kbd.addInlineButton(u"Опции", "cammenu-2")
		kbd.newLine()
		kbd.addInlineButton(u"Просмотр файлов", "cammenu-/")
		kbd.newLine()
		kbd.addInlineButton(u"Достпные камеры", "cammenu-3")
		kbd.getKeyboard()
		return u"Список доступных опций", kbd
	
	elif level == "2":
		if from_id in CONFIG["telegram"]["notified_users"]:
			kbd.addInlineButton(u"Отключить уведомления", "action-unsubscribe")
		else:
			kbd.addInlineButton(u"Включить уведомления", "action-subscribe")
		kbd.newLine()
		kbd.addInlineButton(u"Перезпустить сервис", "action-sysreboot")
		kbd.newLine()
		kbd.addInlineButton(u"<< Вернутся в главное меню", "cammenu-0")
		
		return u"Дополнительные опции", kbd
	elif level == "3":
		step = 0
		for i,x in enumerate(CAMS_LIST):
			if (i and (i/2*2) == i):
				kbd.newLine()
			kbd.addInlineButton(u"Камера {}".format(x.camName), "cammenu{}-0".format(x.index))
		kbd.newLine()
		kbd.addInlineButton(u"<< Вернутся в главное меню", "cammenu-0")
		return u"Список доступных опций", kbd
		

@tg.command("/snapshot")
@admin_access
def telegramLastPhoto(bot, rawMsg, text):
	for c in CAMS_LIST:
		if c.last_frame:
			bot.sendPhoto(rawMsg["chat"]["id"], c.last_frame, u"Камера {}".format(c.camName))
			
@tg.command("/status")
@admin_access
def telegram_sys_statys(bot, rawMsg, text):
	pass

@tg.command("/help")
def telegram_help(bot, rawMsg, tex):
	bot.sendMessage(rawMsg["chat"]["id"],"What help!!!!")
		
		
@tg.command("/login")
def telegram_auth(bot, rawMsg, text):

	if text:
		params = text.split(" ")
		if len(params) > 1:
			password ,login = params[0:2]
			if login == CONFIG["security"]["login"] and password == CONFIG["security"]["password"]:
				if not rawMsg["from"]["id"] in CONFIG["telegram"]["authd_users"]:
					CONFIG["telegram"]["authd_users"].append(rawMsg["from"]["id"])
					bot.sendMessage(rawMsg["chat"]["id"], u"Авторизация прошла успешно")
					saveConfigFile(CONFIG, CONF_FILE)
				else:
					bot.sendMessage(rawMsg["chat"]["id"], u"Авторизация была пройдена ранее!")
				return
			else:
				bot.sendMessage(rawMsg["chat"]["id"], u"Неверный пароль\логин")
	bot.sendMessage(rawMsg["chat"]["id"], u"Необходимо ввести login password")


		
@tg.command("/menu")
@admin_access
def telegram_options_button(bot, rawMsg, text):   

	msg, kbd = getOptMenuByLevel(None,"0")
	
	bot.sendMessage(rawMsg["chat"]["id"], "Список доступных опций", reply_markup = makeJson(kbd.getKeyboard()))
	
	
@tg.callback(r"cammenu(\d*)-(\w+)")
def telegram_cammenu_click(bot, rawMsg, match):
	print(rawMsg)
	chat_id = rawMsg["message"]["chat"]["id"]
	msg_id = rawMsg["message"]["message_id"]
	from_id = rawMsg["from"]["id"]
	
	cam_index = match.group(1)
	menulevel = match.group(2)
	
	if cam_index:
		msg, kbd = getCamsMenu(cam_index, menulevel)
	else:
		msg, kbd = getOptMenuByLevel(from_id, menulevel)
	
	bot.editMessage(chat_id, msg_id, msg, reply_markup = kbd.getJsonKeyboard())
	
@tg.callback(r"files_(\w+)-(\w+)")
def telegram_file_browser_menu(bot, rawMsg, match):
	pass
	
@tg.callback(r"action(\d*)-(\w+)")
def telegram_menu_action(bot, rawMsg, match):
	chat_id = rawMsg["message"]["chat"]["id"]
	msg_id = rawMsg["message"]["message_id"]
	from_id = rawMsg["from"]["id"]
	
	cam_index = match.group(1)
	menulevel = match.group(2)
	
	def _replyDialog(msg, prev):
		k = t.InlineKeyboardMarkup()
		k.addInlineButton(u"<< Вернуться назад",prev)
		bot.editMessage(chat_id, msg_id, msg, reply_markup = k.getJsonKeyboard())
		
	try:
		if cam_index:
			try:
				cam_ = CAMS_LIST[int(cam_index)]
			except:
				_replyDialog(u"Ошибка!Такой камеры не существует!", "cammenu-0" )
				return
			if menulevel == "snapshot":
				if cam_.last_frame:
					bot.sendPhoto(chat_id, cam_.last_frame, u"Снимок с камеры {}".format(cam_.camName))
				else:
					_replyDialog(u"Ошибка!Кадр не доступен!", "cammenu{}-0".format(cam_index) )
					
					
			elif menulevel == "poweroff":
				if cam_.cam_is_run:
					cam_.stop()
					msg = u"Камера выключена"
				else:
					msg = u"Ошибка! Невозможно выключить два раза!"
				_replyDialog(msg, "cammenu{}-0".format(cam_index))
				
			elif menulevel == "poweron":
				if cam_.cam_is_run:
					msg = u"Ошибка! Невозможно в-ключить два раза!"
				else:
					msg = u"Камера включена"
					cam_.start()
				_replyDialog(msg, "cammenu{}-0".format(cam_index))
			
			elif menulevel == "motionoff":
				if cam_.cam_thread.isEnabledDetect():
					cam_.disableMotiomDetect()
					msg = "Детектор движения отключен"
				else:
					msg = "Ошибка!Детектор движения уже отключен"
				_replyDialog(msg, "cammenu{}-0".format(cam_index))
			
			elif menulevel == "motionon" :
				if cam_.cam_thread.isEnabledDetect():
					msg = "Ошибка!Детектор движения уже включен"
				else:
					msg = "Детектор движения включен"
					cam_.enableMotionDetect()
				_replyDialog(msg, "cammenu{}-0".format(cam_index))
		else:
			
			if menulevel == "subscribe":
				k = t.InlineKeyboardMarkup()
				if from_id in CONFIG["telegram"]["notified_users"]:
					msg = u"Вы уже подписаны!"
				else:
					msg = u"Подписка оформлена"
					CONFIG["telegram"]["notified_users"].append(from_id)
					saveConfigFile(CONFIG, CONF_FILE)				
				_replyDialog(msg, "cammenu-0")

				
			elif menulevel == "unsubscribe":
				k = t.InlineKeyboardMarkup()
				if not from_id in CONFIG["telegram"]["notified_users"]:
					msg = u"Вы уже отписались!"
				else:
					msg = u"Ок, всё отлично!"
					CONFIG["telegram"]["notified_users"].remove(from_id)
					saveConfigFile(CONFIG, CONF_FILE)
				_replyDialog(msg, "cammenu-0")
				
	except:
		log.err()
		k = t.InlineKeyboardMarkup()
		k.addInlineButton(u"<< Вернуться назад","cammenu{}-0".format(cam_index))
		bot.editMessage(chat_id, msg_id, u"Произошла ошибка", reply_markup = k.getJsonKeyboard())
	
	

		
@reactor.callWhenRunning
def init():
	
	for num, cam in enumerate(CONFIG.get("cams",[])):
		cam_service = CamService(num,cam["cam"],cam)
		cam_service.signal_mdetect_trig.connect(emailNotifyDetector)
		cam_service.signal_mdetect_trig.connect(telegramNotifyDetector)
		checkAndCreateDir(os.path.join(CONFIG["etc"],str(num),CONFIG["motion_screenshot"]))
		checkAndCreateDir(os.path.join(CONFIG["etc"],str(num),CONFIG["motion_video"]))
		checkAndCreateDir(os.path.join(CONFIG["etc"],str(num),CONFIG["records"]))
		CAMS_LIST.append(cam_service)
	

	
	site = resource.Resource()
	
	log_pass = {CONFIG["security"]["login"] : CONFIG["security"]["password"]}
	
	checker = PasswordDictChecker(log_pass)
	realm =HttpPasswordRealm(site)
	p = portal.Portal(realm, [checker])
	
	credentialFactory = DigestCredentialFactory("md5", "PiSecrutyCenter")
	protected_resource = HTTPAuthSessionWrapper(p, [credentialFactory])
	
	site.putChild("cam", HttpCameraApi(CAMS_LIST))
	site.putChild("resource", static.File("resource"))
	site.putChild("history" ,static.File("history"))
	
	reactor.listenTCP(CONFIG["server"]["port"], server.Site(protected_resource))
	reactor.addSystemEventTrigger('before', 'shutdown', cleanup)
	tg.run()

	for user in CONFIG["telegram"]["notified_users"]:
		tg.sendMessage(user,"Уведомление системы: WakeUp, i'm ready!For start work with me click /menu")
	
if __name__ == "__main__":

	reactor.run()

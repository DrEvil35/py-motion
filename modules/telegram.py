 #coding:utf-8
from __future__ import print_function
from zope.interface import implementer
from twisted.web.iweb import IBodyProducer
from twisted.internet import reactor, defer, endpoints
from twisted.web.client import Agent, readBody
from twisted.web.http_headers import Headers
from collections import defaultdict
import twisted.python.log as log
import mimetypes
import string
import random
import re
import time

import txsocksx.http as sock

try:
	import ujson as json
except:
	import json

import urllib

API_URL = "https://api.telegram.org"
API_TIMEOUT = 60*6
API_RETRY = 30

class InlineKeyboardMarkup(object):
	def __init__(self):
		self.inline_keyboard = []
		self.newLine()
		
	def addInlineButton(self, text, callback):
		button = {
			"type" : "InlineKeyboardButton",
			"text" : text,
			"callback_data" :  callback
			}
		self.line.append(button)
		
	def newLine(self):
		self.line = []
		self.inline_keyboard.append(self.line)
		
	def setLine(self, line):
		self.line = self.inline_keyboard[line]
		
	def getKeyboard(self):
		return {
			"type" : "InlineKeyboardMarkup",
			"inline_keyboard" : self.inline_keyboard
			}
	
	def getJsonKeyboard(self):
		return json.dumps(self.getKeyboard())
		

@implementer(IBodyProducer)
class StringProducer(object):

	def __init__(self, body):
		
		self.body = body
		self.length = len(body)

	def startProducing(self, consumer):
		consumer.write(self.body)
		return defer.succeed(None)

	def pauseProducing(self):
		pass

	def stopProducing(self):
		pass 

		
	
class MultipartEncode(object):
	def __init__(self):
		self.lines = []
		self.boundary = MultipartEncode.genBoundary()
		
	@staticmethod
	def genBoundary():
		return "".join( [random.choice(string.digits+string.letters) for i in   xrange(15)] )
		
	def append(self, key, val, filename = None):
		if type(val) != basestring:
			val = str(val)
		self.lines.append("--{}".format(self.boundary))
		part = "Content-Disposition: form-data; name=\"{}\"".format(key)
		if filename:
			part+="; filename=\"{}\"".format(filename)
		self.lines.append("Content-Type: {}".format(
				filename and mimetypes.guess_type(filename)[0] or "application/octet-stream"))
		self.lines.append(part)
		self.lines.append("")
		self.lines.append(val)
		return self
			
	def getContent(self):
		content = "\r\n".join(self.lines)
		content += "\r\n--{}--\r\n\r\n".format(self.boundary)
		return content , "multipart/form-data; boundary={}".format(self.boundary)
	

class TelegramBot(object):

	MAX_AGE_UPDATE = 5*60 #age for update massega and other entityes

	def __init__(self,token, api_timeout=API_TIMEOUT, api_retry=API_RETRY, proxy=None):
		self._token = token
		self._running = True
		self._http_agent = None
		self._api_timeout = api_timeout
		self._api_retry = api_retry
		self._offset = -2
		self._commands = defaultdict(list)
		self._callbacks = defaultdict(list)
		self._default_callback = None
		self.proxy = proxy

	def run(self):
		if self.proxy:
			end_point = endpoints.TCP4ClientEndpoint(reactor, self.proxy[0], self.proxy[1])
			self._http_agent = sock.SOCKS5Agent(reactor, proxyEndpoint=end_point)
		else:
			self._http_agent = Agent(reactor, connectTimeout = 500)
		return self._poll()

	@defer.inlineCallbacks
	def _poll(self):
		while self._running:
			try:
				upd_ = yield self.callApi("getUpdates", timeout = self._api_timeout, offset = self._offset + 1)
				self._processUpdate(upd_)
			except :
				log.err()
				log.msg("Start retry connect to telegrm server")
				sleep = defer.Deferred()
				reactor.callLater(API_RETRY, sleep.callback, None)
				yield sleep
	
	def callApi(self, method, **params):
		return self._assyncCallApi(method, params)
		
	def editMessage(self, chat_id, message_id, text, **options):
		if type(text) == unicode:
			text = text.encode("utf-8")
		return self.callApi("editMessageText", chat_id = chat_id, message_id = message_id , text = text, **options)
		
	def sendMessage(self, chat_id, text, **options):
		if type(text) == unicode:
			text = text.encode("utf-8")
		return self.callApi("sendMessage", chat_id = chat_id, text = text, **options) 

	def sendPhoto(self, chat_id, photo, caption = ""):
		data_form = (MultipartEncode()
								.append("chat_id", chat_id)
								.append("caption", caption.encode("utf-8"))
								.append("photo", photo, "cam.jpg"))
		body, content_type = data_form.getContent()
		return self._assyncCallApi("sendPhoto", body, content_type)
		
	def sendVideo(self):
		pass
		
	@defer.inlineCallbacks
	def _assyncCallApi(self, method, post_data, content_type = "application/x-www-form-urlencoded"):
		if type(post_data) == dict:
			string_param = urllib.urlencode(post_data)
		else:
			string_param = post_data
		
		params_ = StringProducer(string_param)
		d =  self._http_agent.request(
			"POST",
			"{0}/bot{1}/{2}".format(API_URL, self._token, method),
			Headers({
				"User-Agent": ["Twisted TelegramBot"],
				"Content-Type" : ["{}; charset=UTF-8".format(content_type)]}),
			params_)
		_timeout = reactor.callLater(500, d.cancel)

		def complete(a):
			if _timeout.active():
				_timeout.cancel()
			return a
		d.addBoth(complete)

		response = yield d
		if response.code == 200:
			body = yield readBody(response)
			print("ReQUEST", body, "\n")
			defer.returnValue(json.loads(body))
		else:
			print("ERROR",response.code, ( yield readBody(response)))
			raise RuntimeError(response.code)
			
	def _processUpdate(self, updates):
		if not updates.get("ok"):
			print("Not updates")
			return
		for update in updates["result"]:
			print("UPDATE",update, "\n")
			self._offset = max(self._offset, update["update_id"])
			if (update.get("date", time.time()) - time.time()) > self.MAX_AGE_UPDATE:
				print("Old update, must ignore", update, "\n")
				continue
			if update.has_key("message"):
				self._trackingExecutor(self._processMessage, update["message"])
			elif update.has_key("callback_query"):
				self._trackingExecutor(self._processCallbacks, update["callback_query"])

	def _processMessage(self, msg_):
		
		msg = msg_.get("text", "").strip()
		if not msg:
			return
		
		m = msg.split(" ", 1)
		if len(m) > 1:
			cmd, body = m 
		else:
			cmd, body = m[0], ""
		for handle in self._commands.get(cmd,[]):
			self._trackingExecutor(handle, self, msg_, body)
			
	def _processCallbacks(self, cb_):
		data = cb_.get("data","").strip()
		if not data:
			return
		
		for query, handlers in self._callbacks.iteritems():
			match = re.search(query, data, re.I)
			if match:
				for handle in handlers:
					self._trackingExecutor(handle, self, cb_, match)
				return
		if self._default_callback:
			self._trackingExecutor(self._default_callback, cb_, data)
		
	def _trackingExecutor(self, fn, *a, **kw):
		reactor.callFromThread(fn, *a, **kw)

	def addCommand(self, cmd, fn):
		self._commands[cmd].append(fn)
	
	def addCallback(self, fn, query = None):
		if query == None:
			self._default_callback = fn
		else:
			self._callbacks[query].append(fn)
		
	def command(self, cmd):
		def _wrap(fn):
			self.addCommand(cmd, fn)
			return fn
		return _wrap
	
	def callback(self, query = None):
		def _wrap(fn):
			self.addCallback(fn ,query)
			return fn
		return _wrap
			
		


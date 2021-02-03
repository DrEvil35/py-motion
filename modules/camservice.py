from twisted.internet import reactor, defer
from twisted.internet.threads import deferToThread
import twisted.python.log as log
import collections
import time
import datetime
import os
import camstream as c
from signal import Signal
from utils import safetyCall, checkAndCreateDir



CAMERA_WAKE_UP = ""


class StopCamera(Exception):
	pass

class StackFrame(object):
	def __init__(self, maxlen = 20, time_update = 0.5):
		self.ring_buffer = collections.deque(maxlen = maxlen)
		self.counters_list = []
		self.last_updated = 0
		self.time_update = time_update
		
	def __nonzero__(self):
		if time.time() - self.last_updated > self.time_update:
			return True
		return False
		
	def counter(self, clock):
		d = defer.Deferred()
		self.counters_list.append((clock, d))
		return d
	
	def append(self, image):
		self.ring_buffer.append(image)
		new_counters = []
		for c,d in self.counters_list:
			c-=1
			if c <= 0 :
				reactor.callFromThread(d.callback,self)
			else:
				new_counters.append((c,d))
		self.counters_list = new_counters
		self.last_updated = time.time()
		
	def saveVideo(self, filename):
		return deferToThread(c.make_video,filename.encode('utf-8'), list(self.ring_buffer))



class CamService(object):
	cam_workup = False
	def __init__(self, index, source, cam_config):
		self.cam_is_run = False
		self.__cam_index = index
		self.cfg = cam_config
		if type(source) == unicode:
			source = source.encode("UTF-8")
			source = source.encode("UTF-8")
		self.__source = source
		self._notify_list = []
		self.cam_thread = c.CamStream()
		self.cam_thread.onCaptureUpdate(self._onCapUpdate)
		self.cam_thread.onThreadEvent(self._onThreadEvents)
		self.cam_thread.start(source)
		self.last_triggered = 0
		self.cam_thread.schedule(3, 0)
		self.stack_frame = StackFrame(40)
		self.last_frame = None
		self._events = collections.defaultdict(set)
		
		self.signal_mdetect_trig = Signal()

	def stop(self):
		self.cam_thread.stopAssync()
		
	def start(self):
		self.cam_thread.start(self.__source)

	@property
	def camName(self):
		return "cam{}".format(self.__cam_index)

	@property
	def index(self):
		return self.__cam_index
	
	@property
	def source(self):
		return self.__source
	
	@safetyCall
	def _onThreadEvents(self, event, msg= None):
		self._callEvent("cam_event", event)
		if event == c.events.device_open_success:
			self._callEvent("cam_on")
			self.cam_is_run = True
			log.msg("Cam {0} connect success!".format(self.__source))
		elif event == c.events.device_open_error or event == c.events.device_disconnect:
			self._callEvent("cam_off")
			self.cam_is_run = False
			self._cbErr()
			log.msg("Cam {0} lost, reconnet after {1}s".format(self.__source, CONFIG["cam_reconnect_timeout"]))
			reactor.callLater(CONFIG["cam_reconnect_timeout"], self.cam_thread.start, self.__source)
		elif event == c.events.thread_stop:
			self.cam_is_run = False
	
	def _callEvent(self,event,*a, **kw):
		for handles in self._events.get(event,set()):
			reactor.callFromThread(handles, self, *a, **kw)
	
	def _cbErr(self):
		for d in self._notify_list:
			d.errback(StopCamera())
		self._notify_list = []
			
	@safetyCall
	def _onCapUpdate(self, image):
		if self.stack_frame:
			self.stack_frame.append(image)
		self.last_frame = image
		current_list = self._notify_list
		self._notify_list = []
		for d in current_list:
			d.callback(image)
			
	
	def recordVideo(self,timeout):
		
		path_video = os.path.join(CONFIG["etc"],
								str(self.index),
								CONFIG["records"],
								"{:%d-%m-%Y}".format(datetime.datetime.now()))
		checkAndCreateDir(path_video)
		path_video += "/{:%H:%M:%S}.avi".format(datetime.datetime.now())
		if self.cam_thread.startRecord(path_video.encode("utf-8"), "XVID"):
			d = defer.Deferred()
			def _stop():
				self.cam_thread.stopRecord()
				d.callback(path_video)
			reactor.callLater(timeout, _stop)
			return d
		return None
			

	
	def waitForUpdate(self):
		if self.cam_thread.isRunning:
			d = defer.Deferred()
			self._notify_list.append(d)
			return d
		
	
	def addEventListener(self,event, callback):
		self._events[event].add(callback)
		
	def removeEventListener(self, event, callback):
		self._events.get(event,set()).discard(callback)
	
	def disableMotiomDetect(self):
		self._callEvent("mdetect_disable")
		self.cam_thread.disableDetect()
	
	def enableMotionDetect(self,sens = 0.1,rect = None):
		@safetyCall
		def _cb(a):
			if time.time() - self.last_triggered > self.cfg["notify_interval"]:
				self.signal_mdetect_trig.emit(self)
				self.last_triggered = time.time()
				
		self._callEvent("mdetect_enable")
		self.cam_thread.enableDetect(_cb, rect, sens)

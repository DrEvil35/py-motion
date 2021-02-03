from zope.interface import implementer
from twisted.internet.interfaces import IProducer
from twisted.internet import reactor, defer
import time


@implementer(IProducer)
class MJPEGStreamProducer(object):
	stop = False
	def __init__(self,request, cam, framerate = None):
		self.request = request
		self.cam = cam
		self.last_resume = time.time()
		self.delay_frame = framerate and 1.0/framerate

	def sendHeader(self, key, val):
		self.request.write("{}: {}".format(key,val))
		self.stopHeader()
		
	def stopHeader(self):
		self.request.write("\r\n")
	
	@defer.inlineCallbacks
	def resumeProducing(self):
		self.request.channel.pauseProducing()
		#print("resume", dir(self.request), self.request)
		try:
			cap = yield self.cam.waitForUpdate()
			if self.stop:
				return
		except StopCamera:
			self.request.channel.stopProducing()
			return
		self.request.write("--jpgboundary")
		self.sendHeader("Content-Type","image/jpg")
		self.sendHeader("Content-Length", len(cap))
		self.stopHeader()
		self.request.write(cap)
		self.last_resume = time.time()
		self.request.channel.resumeProducing()
			
			
	def stopProducing(self):
		self.stop = True
		self.request.unregisterProducer()
		self.request.finish()

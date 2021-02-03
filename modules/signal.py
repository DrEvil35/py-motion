#coding:utf-8

from twisted.internet import reactor, defer

SIGNAL_QUEUE = 0x0
SIGNAL_DIRECT = 0x1

class Signal(object):
	def __init__(self):
		self.slots = set()
		
	def connect(self, slot):
		self.slots.add(slot)
		
	def emit(self, *a, **kw):
		for slot in self.slots:
			if type(slot) == Signal:
				reactor.callFromThread(slot.emit, *a, **kw)
			else:
				reactor.callFromThread(slot, *a, **kw)
				
	def disconnect(self, slot):
		self.slots.remove(slot)
		
	def __contains__(self, slot):
		return slot in self.slots
			



class Struct:
	def __init__(self, **kwargs):
		for name, value in kwargs.items():
			self.__setattr__(name, value)
			
	def asdict(self):
		return self.__dict__

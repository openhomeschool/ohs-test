

class Struct:
	def __init__(self, **kwargs):
		for name, value in kwargs.items():
			self.__setattr__(name, value)
			


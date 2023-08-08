from __init__ import *

class QuikLoad(object):
	"""docstring for QuikLoad"""
	def __init__(self):
		super(QuikLoad, self).__init__()
		self.files = [f'microservices/api_templates/{i}' if '.' in i else '' for i in os.listdir('microservices/api_templates')]

	def check_file_in(self,filename):
		for fileName in self.files:
			if fileName.split('/')[-1] == filename:  return True
		return False

	def get_real_name(self,filename):
		for fileName in self.files:
			if fileName.lower().split('/')[-1] == filename.lower():
				return fileName

	def load_this_file(self,filename):
		print(self.files)
		if self.check_file_in(filename):
			with open(self.get_real_name(filename),'r',encoding='UTF-8') as self.loadedFile:
				return self.loadedFile.read()
		return f'<a href="/wrong_key/<h1>Page {filename} notFound./">Error Page</a>'

	


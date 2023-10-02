from __init__.file import *
class Template(object):
	"""docstring for Template"""
	def __init__(self,file='' ,path='template'):
		super(Template, self).__init__()
		self.path = path
		self.filenamed = str(''.join([i if '.mlx' in i else '' for i in os.listdir(self.path)])).strip()
		if len(file):
			self.filenamed = file
		self.inte = '#'
		self.load_file()

	def load_file(self):
		with open((self.path if self.path[-1] == '/' else self.path + '/')+self.filenamed,'r',encoding='UTF-8') as self.mlxFile:
			self.analize()

	def analize(self):
		struct = []
		for len_ in self.mlxFile.read().split(f'{self.inte}path')[1::]:
			
			len_=len_.replace(' ','');
			try:  self.js=[i.strip() for i in len_.split(f'{self.inte}js(')[1].split(')')[0].split(',')];
			except:  self.js = []
			try:  self.css=[i.strip() for i in len_.split(f'{self.inte}styles(')[1].split(')')[0].split(',')];
			except:  self.css = []

			struct.append({
				"link":len_.split(';')[0].replace("'",'').replace('"','').replace('=',''),
				"html": len_.split(f'{self.inte}hyper=')[1].split(';')[0],
				"css": self.css,
				"js": self.js,
			})
		self.analize = struct

	def create_code(self):
		with open(f'{self.path}/'+self.choice_link["html"],'r',encoding='UTF-8') as html_file:
			code = html_file.read()
		for css_file in self.choice_link["css"]:
			with open(f'{self.path}/'+css_file,'r',encoding='UTF-8') as cssFile:
				code = code.replace('</head>',f'<style class="{css_file}">{cssFile.read()}</style></head>')
		for code_js in self.choice_link["js"]:
			if '%' in code_js:  meta = code_js.split('%')[1];code_js = code_js.split('%')[0]
			else:  meta = None 

			with open(f'{self.path}/'+code_js,'r',encoding='UTF-8') as jsFile:
				if meta:
					code = code.replace(meta,f'{meta}<script class="{code_js}">\n{jsFile.read()}</script>')
				code = code.replace('</body>',f'<script class="{code_js}">\n{jsFile.read()}</script></body>')

		return code

	def code_location(self,location,**args):
		print(self.analize)
		for i in self.analize:
			if i["link"] == location:
				self.choice_link = i;break
		code = self.create_code()
		for key,value in args.items():
			print(key,value)
			code = code.replace('{{'+key+'}}',f'{value}')
		return code

template = Template()
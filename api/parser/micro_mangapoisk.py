#from __init__.file import *
import os,requests
from bs4 import BeautifulSoup as bs
from fake_headers import Headers as Hd
import json
from fastapi import FastAPI
from typing import Annotated
from fastapi import Query
from fastapi.responses import HTMLResponse

from uvicorn import run as start

app = FastAPI()

class MangaPoisk(object):
	"""docstring for MangaPoisk"""
	def __init__(self, 
				url = 'https://mangapoisk.me',
				token="eyJpdiI6InFiTE9hd1hrWWpieFdsaUNTL2U0TVE9PSIsInZhbHVlIjoiU0NjcFlzcjB4QzBtclBSVWd0YTlxeVpsbnAzTWhjM3lIS01KOWtrSEFDLzFLNUFEMDRLSVF5V3dQNytZbnlVSDVGZ09mK3ZOZTIvWXRubEk3cWNtaGFaeVJDYWE5dzd0Z2UxVnJTeXVHY0VDN01aZWZ3SHJCb2tIQWRXWWg3TDEiLCJtYWMiOiI3YWNlNmZhMzUxMGYxZDdmODViZWYyMGU1YjVlNGQzNzlkNTVkOWRmZTRkZDMzOGNjZDRmMWZkZTM1ZGZjOTUwIiwidGFnIjoiIn0=",
				version = "945458ea26c360a4c84504fd61baae61"
			):
		super(MangaPoisk, self).__init__()
		self.url = url
		self.config = {
			"cookies": {
				'XSRF-TOKEN': 'eyJpdiI6InFiTE9hd1hrWWpieFdsaUNTL2U0TVE9PSIsInZhbHVlIjoiU0NjcFlzcjB4QzBtclBSVWd0YTlxeVpsbnAzTWhjM3lIS01KOWtrSEFDLzFLNUFEMDRLSVF5V3dQNytZbnlVSDVGZ09mK3ZOZTIvWXRubEk3cWNtaGFaeVJDYWE5dzd0Z2UxVnJTeXVHY0VDN01aZWZ3SHJCb2tIQWRXWWg3TDEiLCJtYWMiOiI3YWNlNmZhMzUxMGYxZDdmODViZWYyMGU1YjVlNGQzNzlkNTVkOWRmZTRkZDMzOGNjZDRmMWZkZTM1ZGZjOTUwIiwidGFnIjoiIn0='
			},
			"headers": {
				"X-Inertia": "true",
				"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/115.0",
				"Accept": "text/html, application/xhtml+xml",
				"Accept-Language": "en-US,en;q=0.5",
				"X-Requested-With": "XMLHttpRequest",
				"X-Inertia-Version": version,
				"Content-Type": "application/json",
				"X-XSRF-TOKEN": token,
				"Alt-Used": url.split('/')[-1]
			}	

		}

	
	def parser_with_api(self,path):
		print(self.url+f'{path}')
		self.curl = requests.get(self.url+path,headers=self.config["headers"],cookies=self.config["cookies"])

		if self.curl.status_code == 200:
			print("Успешное подключение к сайту, по адресу: {}\nНачинаю зеркалить сайт".format(self.url))
			self.mainsoup = bs(self.curl.content,'html5lib')
		elif self.curl.status_code == 400:
			return 

		self.HtmlCode = self.curl.json()
		
		return self.HtmlCode

@app.get('/hot_load')
def root(
	name: str, 
	tom: int,
	glva:int,
	url='mangapoisk.me'):
	if glva and name and tom:
		manga = MangaPoisk(url=f'https://{url}/')
		return manga.parser_with_api(
			f'manga/{name}/chapter/{tom}-{glva}'
		)

if __name__ == '__main__':
	start(app,host='0.0.0.0',port=80)

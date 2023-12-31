from __init__.file import *
from api.parser.KeyGet import load_keys
"""import os,requests
from bs4 import BeautifulSoup as bs
from fake_headers import Headers as Hd
import json"""



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

	def search(self,text):
		return requests.get(f'{self.url}/search?q={text}',headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0","Accept": "application/json, text/javascript, */*; q=0.01","Accept-Language": "ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3","X-CSRF-TOKEN": "9A4LpNW8L9dWTCSVehCfILnPdI8CoPIK6LRVcltX","X-Requested-With": "XMLHttpRequest","Sec-Fetch-Dest": "empty","Sec-Fetch-Mode": "cors","Sec-Fetch-Site": "same-origin"}).json()


	def _reduxonCount(self,c_to=[20,20,20,20]):
		start = 0;
		end = []
		for i in c_to:
			end.append(self.mangaList[start:start+i]);start+=i
		return end

	def parse_main_page(self):
		self.curl = requests.get(self.url,headers=Hd().generate())
		if self.curl.status_code == 200:
			print("Успешное подключение к сайту, по адресу: {}\nНачинаю парсить главную страничку".format(self.url))
			self.mainsoup = bs(self.curl.content,'html5lib')
		elif self.curl.status_code == 400:
			return 

		v = load_keys(self.mainsoup)

		if self.config["headers"]["X-Inertia-Version"] != v:  self.config["headers"]["X-Inertia-Version"] = v;

		self.mangaList = []

		for card in self.mainsoup.find_all('div',class_='card'):
			try:
				self.mangaList.append({
					"link": card.find('a').get('href'),
					"name": card.find('a').get('title'),
					"short_name": card.find('h5').text,
					"last_glav": card.find('a',class_='text-surface-900-50-token').text,
					"last_glavLink": card.find('a',class_='text-surface-900-50-token').get('href'),
					"ago": card.find('p',class_='text-surface-600-400-token').text,
					"img": card.find('img').get('src')
				})
			except Exception as error:
				print(f'MangaPoisk | {error}')

		return self.mangaList

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

	def parse_her_api(self,path):
		return self.parser_with_api(f'/manga/{path}')
		
		

if __name__ == '__main__':
	MangaParser = MangaPoisk()
	with open('a.html','w',encoding='UTF-8') as f:
		json.dump(MangaParser.parse_her_api(input('Manga name: ')),f,ensure_ascii=False,indent=4)
	
	
from __init__ import *

def search(text):
	return requests.get(f'https://mangapoisk.org/search?q={text}',headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0","Accept": "application/json, text/javascript, */*; q=0.01","Accept-Language": "ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3","X-CSRF-TOKEN": "9A4LpNW8L9dWTCSVehCfILnPdI8CoPIK6LRVcltX","X-Requested-With": "XMLHttpRequest","Sec-Fetch-Dest": "empty","Sec-Fetch-Mode": "cors","Sec-Fetch-Site": "same-origin"}).json()

def get_alls():
	print('Запрос на https://mangapoisk.org')
	r = requests.get('https://mangapoisk.org/',headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0","Accept": "application/json, text/javascript, */*; q=0.01","Accept-Language": "ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3","X-CSRF-TOKEN": "9A4LpNW8L9dWTCSVehCfILnPdI8CoPIK6LRVcltX","X-Requested-With": "XMLHttpRequest","Sec-Fetch-Dest": "empty","Sec-Fetch-Mode": "cors","Sec-Fetch-Site": "same-origin"}).content
	soup = bs(r,'html5lib')
	als_mangas_on = soup.find_all('article',class_='flex-item-mini mx-1 splide__slide')
	data = []
	for i in als_mangas_on:
		data.append(
				{
					"link": i.find('a').get('href'),
					"name": i.find('a').get('title'),
					"limg": i.find('img').get('data-splide-lazy'),
					"simg": i.find('img').get('src'),
					"last_link": i.find('div',class_='manga-mini-last-chapter list-group-item position-absolute p-0 border-0').find('a').get('href'),
					"last_glav": i.find('div',class_='manga-mini-last-chapter list-group-item position-absolute p-0 border-0').find('a').text.strip(),
					"last_update": i.find('div',class_='manga-mini-last-chapter list-group-item position-absolute p-0 border-0').find_all('span')[1].text.strip(),
					"short_name": i.find('h2',class_='py-1 entry-title').text.strip()
				}
			)
	print(data)
	return data
	

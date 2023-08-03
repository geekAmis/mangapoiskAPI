from __init__ import *

def read_ok(url):
	r = requests.get(url,headers=Headers().generate())
	while r.status_code != 200:
		r = requests.get(url,headers=Headers().generate())
		time.sleep(5)
	return r.content

def read_this_page(manga,chapter):
	soup = bs(read_ok('https://mangapoisk.org/manga/{}/chapter/{}#chapter-slider'.format(manga,chapter)),'html5lib')
	data = []
	for img in soup.find('div',class_='mt-1 d-flex flex-column align-items-center chapter-images').find_all('img'):
		data.append(
			{
				"width": img.get('width'),
				"height":img.get('height'),
				"page_id": img.get('id').replace('page-',''),
				#"small_img": img.get('data-small-src'),
				"img": img.get('data-src'),
				"img_placeholder": img.get('src'),
				"alt": img.get('alt')
			}
		)
	return data

def how_to_new_date_quest(url):
	soup = bs(read_ok(url),'html5lib')
	return soup.find('h2',class_='h3').text.strip()

def see_next_page_and_this(manga,chapter):
	soup = bs(read_ok('https://mangapoisk.org/manga/{}/chapter/{}#chapter-slider'.format(manga,chapter)),'html5lib')
	try:
		next_page = soup.find('a',class_='mt-2 btn btn-lg btn-primary').text.strip()
	except:
		next_url = f"https://mangapoisk.org/manga/{manga}/chapter/{chapter.split('-')[0]}-{str(int(chapter.split('-')[1])+1)}"
		next_page = how_to_new_date_quest(next_url)
	try:
		next_page_link = soup.find('a',class_='mt-2 btn btn-lg btn-primary').get('href')
	except:
		next_page_link = None

	data = {
		"at_page": soup.find('span',class_='current-chapter').text.strip(),
		"next_page": next_page,
		"next_page_link": next_page_link,
		"name_page": soup.find('div',class_='text-center').find('h1',class_='mb-2').find('a').text.strip(),
		"page_link": soup.find('div',class_='text-center').find('h1',class_='mb-2').find('a').get('href'),
		"end": True if 'время выхода главы' in next_page else False
	}
	print(data)
	return data

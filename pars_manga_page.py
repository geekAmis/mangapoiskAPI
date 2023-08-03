from __init__ import *

def MP_get_json_datas(manga):
	resp = requests.get(f'https://mangapoisk.org/manga/{manga}',headers=Headers().generate())
	soup = bs(resp.content,'html5lib')
	glav = soup.find('div',class_='card-body pb-2').find('h2',class_='h5').text.split('(')[1].split(')')[0].strip()
	firs_glava = 'https://mangapoisk.org'+soup.find('div',class_='manga-links btn-group pt-2').find('a',class_='btn btn-outline-primary').get('href')
	descrypt = soup.find('div',class_='manga-description entry').text.strip()
	info_post = soup.find('div',class_='post-info')
	rates_count = info_post.find('span',class_='ratesCount').text
	rate = info_post.find('b',class_='ratingValue ml-1').text
	all_spans_inform = [i.text for i in info_post.find_all('span')]
	try:
		count_pagination = len(soup.find('div',class_='chapters-infinite-pagination').find('ul',class_='pagination').find_all('li',class_='page-item'))-2
	except:
		count_pagination = 2
	return {
		"orig_name": manga.split('abs')[0].replace('-',' '),
		"ru-name": soup.find('span',class_='post-name').text.strip(),
		"img": soup.find('img',class_='img-fluid').get('src'),
		"first_glava": firs_glava.replace('https://mangapoisk.org',''),
		"glav": glav,
		"rate":rate,
		"feedbacks": rates_count,
		"descryption": descrypt,
		"all_spans": all_spans_inform,
		"status": all_spans_inform[6].replace('Статус:','').replace(' ',''),
		"jenres": ",".join(",".join(all_spans_inform[8].replace(' ','').split('\n')[1:]).replace(',,',',').split(',')[::-1][1:][::-1]),
		"count_pages": count_pagination
	}

def MP_get_can_see(manga):
	return requests.get(f'https://mangapoisk.org/manga/{manga}/sidebar?page=manga',headers=Headers().generate()).text

def MP_chapter_list(manga,count):
	pages = []
	for i in range(1,count+1):
		soup = bs(requests.get(f'https://mangapoisk.org/manga/{manga}/chaptersList?page={i}',headers=Headers().generate()).content,'html5lib')
		list_items = soup.find_all('li',class_='list-group-item chapter-item')
		for item in list_items:
			pages.append(
				{
					"title": item.find('span',class_='chapter-title').text.strip(),
					"link": item.find('a').get('href'),
					"date": item.find('span',class_='chapter-date').text,
					"html_code": str(item)
				}
			)
	return pages
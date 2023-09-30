from __init__.file import *

app = FastAPI(host='vaka-bit.online')

from api.engine import *
from template.mlxDecoder import template
from uvicorn import run as start

@app.get('/')
async def root(
		user_id: Annotated[ int | None, Query(min_length=1, max_length=10)] = None #, pattern="^fixedquery$"
	):

	if not user_id:
		return HTMLResponse(content=template.code_location('/'))

@app.get('/manga/{name}/')
async def main(name):
	data = MangaPoisk().parse_her_api(name)
	return HTMLResponse(content=template.code_location('/manga',
		MANGA_NAME=data["props"]["manga"]["data"]["name"],
		ENG_MANGA_NAME=data["props"]["manga"]["data"]["name_en"],
		MANGA_IMAGE=data["props"]["manga"]["data"]["poster"]["link"],
		IMG_W=data["props"]["manga"]["data"]["poster"]["width_mini"],
		IMG_H=data["props"]["manga"]["data"]["poster"]["height_mini"],
		GLAV_COUNT=data["props"]["manga"]["data"]["chapters_count"],
		CALL_BACK_COUNT=data["props"]["manga"]["data"]["comments_count"],
		STATUS=random.choice(["Крутышкино","MANGAPOISK почини сайт, лагает пиздец.","Любимое у админа","Любят маленькие девочки","Тебе точно подойдёт.","НЕ читай НЕ смотри НЕ комментируй)"]),
		NAME_ALT=data["props"]["manga"]["data"]["name_alt"],
		RATING=data["props"]["manga"]["data"]["rating"],
		RATES_COUNT=data["props"]["manga"]["data"]["ratesCount"],
		GENRES_HTML="None",
		YEAR=data["props"]["manga"]["data"]["year"],
		DESCRYPTION=data["props"]["manga"]["data"]["description"],
		PAGE_NAME="mangasearch-api.ru",
		FIRST_CHAPTER=data["props"]["manga"]["data"]["firstChapter"]["link"],
		LAST_CHAPTER=data["props"]["manga"]["data"]["lastChapter"]["link"],
		WAIT_CHAPTER='/'.join(data["props"]["manga"]["data"]["lastChapter"]["link"].split('/')[::-1][1::][::-1])+'/'+data["props"]["manga"]["data"]["lastChapter"]["link"].split('/')[-1].split('-')[0]+'-'+str(int(data["props"]["manga"]["data"]["lastChapter"]["link"].split('/')[-1].split('-')[1])+1)
	))

@app.get('/manga/{name}/chapter/{chapter}')
async def read(name,chapter):
	data = MangaPoisk().parse_her_api(f'{name}/chapter/{chapter}')
	chapter = data["props"]["chapter"]["data"]
	manga = data["props"]["manga"]["data"]
	imgs = ['<img src="{}" loading="eager" class="img-fluid page-image lazy-preload page-image preload mx-auto" data-page="{}" data-number="1" id="page-{}" alt="Манга {} - Глава {} Страница {}" title="Манга {} - Глава {} Страница {}" width="{}" height="{}">'.format(
		img["link"],img["id"],img["number"],manga["name"],chapter["number"],img["number"],manga["name"],chapter["number"],img["number"],img["width"],img["height"]) for img in chapter["pages"]]

	return HTMLResponse(content=template.code_location('/read',
		MANGA_LINK=data["url"].split('chapter')[0],
		DATE=chapter["ago"]+' '+ chapter["upcoming_date"],
		TITLE=manga["name"],
		DESCRIPTION=chapter["name"],
		GLAVA=chapter["number"],
		TOM=chapter["volume"],
		IMGS=imgs
		))

if __name__ == '__main__':
	start(app,host='localhost',port=80)
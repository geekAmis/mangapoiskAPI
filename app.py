from __init__.file import *

app = FastAPI()

from api.engine import *
from template.mlxDecoder import template

@app.get('/')
async def root(
		user_id: Annotated[ int | None, Query(min_length=1, max_length=10)] = None #, pattern="^fixedquery$"
	):

	if not user_id:
		return HTMLResponse(content=template.code_location('/'))

@app.get('/manga/{name}/')
async def main(name):
	data = MangaPoisk().parse_choisen_glav(name)
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
		WAIT_CHAPTER=
		'''



		'''
	))
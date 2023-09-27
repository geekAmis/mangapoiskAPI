from __init__.file import *
from api.parser.mangapoisk import MangaPoisk
from app import app

class API_requered(object):
	"""docstring for API_requered"""
	def __init__(self):
		super(API_requered, self).__init__()
		self.can_access = ["get_mangas","get_colliders","search_mangas","read_mangas","save_mangas","info_mangas"]
	
	def _API_acecess(self):  return self.can_access


@app.get('/api')
async def api_methods(
	version: Annotated[ str | None, Query(pattern="^v0$")] = None ,
	method: Annotated[ str | None, Query(min_length=2,max_length=64)] = None,
	manga: Annotated[ str | None, Query(min_length=0)] = None
		):

	if method not in API_requered()._API_acecess():
		return {"method": "NotFound","error_code": 404,"version":version}

	

	if method == "get_mangas":
		return {
			"method": "get_mangas",
			"version": version,
			"mangas": MangaPoisk().parse_main_page()
		}
	elif method == "get_colliders":
		mp = MangaPoisk()
		mp.parse_main_page()
		return {
			"method": "get_colliders",
			"version": version,
			"mangas": mp._reduxonCount()
		}
	elif method == "info_mangas":
		if manga:
			data = MangaPoisk().parse_choisen_glav(manga)
			data["method"] = "info_mangas"
			data["version"] = version
			return data
		return {"method": "info_mangas","error_code": 403,"version":version,"descryption": "plz, add in request 'manga' param"}

	
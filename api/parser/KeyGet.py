import requests
from bs4 import BeautifulSoup as bs 
from fake_headers import Headers as Hd
import json

def load_keys(soupec):
	soup = soupec.find('body').find('div')
	jsons = soup.get('data-page').replace('&quot;','"')
	jsons = json.loads(jsons)
	return jsons["version"]


def main():
	print(load_keys(bs(requests.get('https://mangapoisk.me',headers=Hd().generate()).text,'html5lib')))


if __name__ == '__main__':
	main()
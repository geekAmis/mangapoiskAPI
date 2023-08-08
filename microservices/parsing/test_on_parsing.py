import requests
open('a.html','w',encoding='UTF-8').write(requests.get('http://localhost/manga/finding-camellia-abs3rId').text)

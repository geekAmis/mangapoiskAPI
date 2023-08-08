from functions import *
from webbrowser import open_new_tab

ssl = False
host = 'localhost'
port = 80

url = str('https://' if ssl else 'http://')+f'{host}:{port}'

print(url)
open_new_tab(url)

if __name__ == '__main__':
	socketio.run(app,host='localhost',port=80)
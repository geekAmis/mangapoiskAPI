from functions import *

if __name__ == '__main__':
	socketio.run(app,host='localhost',port=80,allow_unsafe_werkzeug=True)

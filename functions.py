from microservices.parsing.main_page_pars import *
from microservices.parsing.pars_manga_page import *
from microservices.parsing.pars_manga_read import *
from microservices.security.keys_check import check_keys as _check_keys
from microservices.api_templates.load_this import QuikLoad

app = Flask(import_name=__name__)
app.config['SECRET_KEY'] = 'secret!'
app.debug = False
socketio = SocketIO(app,debug=app.debug,allow_unsafe_werkzeug=True )



def generic_main_page(slide_templ = """<div class="swiper-slide"><a href="{}" class="img-container"><div class="shadow-container"><img src="{}" alt="        Скоро загрузится."></div><div class="text-lazy">{}</div></a><a class="last_page_link" href="{}" style="color:#889D9D;"><div class="text-desc">{}</div></a></div>"""):
	SSS = ['','','','']
	datas = get_alls()
	for i in range(0,len(datas)):
		if datas[i]["simg"] == None:
			datas[i]["simg"] = datas[i]["limg"]
		datas[i]["simg"] = datas[i]["simg"]#.replace('https://static2.mangapoisk.org','/img')

	for s in range(0,len(datas)):
		if s <= 20:
			SSS[0] += slide_templ.format(datas[s]["link"],datas[s]["simg"],datas[s]["name"],datas[s]["last_link"],str(' 🕰 '+datas[s]["last_update"]+' '+datas[s]["last_glav"]).replace('день','day').replace('дня','day\'s'))
		elif s > 20 and s <=40:
			SSS[1] += slide_templ.format(datas[s]["link"],datas[s]["simg"],datas[s]["name"],datas[s]["last_link"],str(' 🕰 '+datas[s]["last_update"]+' '+datas[s]["last_glav"]).replace('день','day').replace('дня','day\'s'))
		elif s > 40 and s <= 60:
			SSS[2] += slide_templ.format(datas[s]["link"],datas[s]["simg"],datas[s]["name"],datas[s]["last_link"],str(' 🕰 '+datas[s]["last_update"]+' '+datas[s]["last_glav"]).replace('день','day').replace('дня','day\'s'))
		elif s > 60 and s <= 80:
			SSS[3] += slide_templ.format(datas[s]["link"],datas[s]["simg"],datas[s]["name"],datas[s]["last_link"],str(' 🕰 '+datas[s]["last_update"]+' '+datas[s]["last_glav"]).replace('день','day').replace('дня','day\'s'))

	return SSS

# class func for update app.SECRET_KEY
def update_secret_key(length=20):
	app.config['SECRET_KEY'] = ''.join(random.choices(string.ascii_letters + string.digits, k=length))
	print(' NEW: {}'.format(app.config['SECRET_KEY']))

@app.after_request
def add_cache_headers(response):
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

# load main page
@app.route('/')
def index():
	try:
		return render_template('index.html',key=app.config['SECRET_KEY'])
	finally:
		timer = threading.Timer(5, update_secret_key)
		timer.start()

# search page
@app.route('/search',methods=['GET','POST'])
def index_html():
	if request.args.get('q') != None:
		return render_template('main_page.html',q=request.args.get('q'))
	return render_template('main_page.html',key=app.config['SECRET_KEY'])



# error page
@app.route('/wrong_key/<error_text>/')
def wrong_key(error_text):
	return render_template('wet_wrong.html',wrong=Markup(str(error_text)+'<br><a href="/">Back to main page</a>'))

@app.route('/fail/api/')
def fail_api_keys():
	return jsonify([QuikLoad().load_this_file('headers.html')])

#/api/v0.0.1/${key}/?header_generate=ok
@app.route('/api/v0.0.1/<key>/',methods=['GET','POST'])
def api_hendler(key):
	if str(key) == str(app.config['SECRET_KEY']):
		if request.args.get('main_page') == 'fuck_you_stupid_coder':
			return jsonify(generic_main_page())
		elif request.args.get('header_generate') == 'ok':
			return jsonify([QuikLoad().load_this_file('header.html')])
		elif request.args.get('search_generate') == 'ok':
			return jsonify([QuikLoad().load_this_file('search.html')])
		
	else:
		#return api_hendler(app.config['SECRET_KEY'])
		update_secret_key(45)
		return redirect('/wrong_key/<h1>У вас нет доступа к API/')




# load main read page manga (all pages in one web page.)
@app.route('/manga/<manga>/chapter/<chapter>',methods=['GET'])
def manga_read(manga,chapter):
	update_secret_key(15)
	data = read_this_page(manga,chapter)
	scale = request.args.get('scale')
	if scale == None:
		scale = 0

	for i in range(0,len(data)):
		if data[i]["img"] == None:
			data[i]["img"] = data[i]["img_placeholder"]
	
	data_js = MP_get_json_datas(manga)

	user_agent = UserAgent(request.headers.get('User-Agent'))
	if 'android' in str(user_agent).lower()  or 'iphone' in str(user_agent).lower():
		series = 'phone'
	else:
		series = 'pc'
	try:
		at_page = "Том "+str(chapter).split('-')[0]+" Глава "+str(chapter).split('-')[1]
	except:
		at_page = "Глава "+str(chapter)
	READ_MANGA_PAGE = make_response(render_template('a.html',
		all_imgs=json.dumps(data,  sort_keys=True, default=str),
		link = manga,
		chapter= chapter,
		scale=scale,
		title=data_js["ru-name"],
		at_page=at_page,
		series=series,
		key = app.config['SECRET_KEY'],
		fake_key = ''.join(random.choices(string.ascii_letters + string.digits, k=35))
	))
	READ_MANGA_PAGE.set_cookie('last_viewManga', f'{manga}')
	READ_MANGA_PAGE.set_cookie('last_viewChapter',f'{chapter}')
	return READ_MANGA_PAGE


# load last view manga chapter. (Saved this from cookies)
@app.route('/lastview')
def lastview_read_page():
	update_secret_key(45)
	if request.cookies.get('last_viewManga') and request.cookies.get('last_viewChapter'):
		return manga_read(request.cookies.get('last_viewManga'),request.cookies.get('last_viewChapter'))
	else:
		return Markup('<script>alert("Not Found. May be you is new user? Please, read manga and have fun, after read first manga - this button must be active");window.location.href="/";</script>')


#page for load current manga on current page and read one page, for read next - button bext page.
@app.route('/manga/<manga>/chapter/<chapter>/<page>/xgemx')
def manga_read_at_book(manga,chapter,page):
	data = read_this_page(manga,chapter)
	page = int(page)
	for i in range(0,len(data)):
		if data[i]["img"] == None:
			data[i]["img"] = data[i]["img_placeholder"]
	
	return redirect(f'/wrong_key/В разработке./')




# Page descryption of manga
@app.route('/manga/<path>')
def manga_page(path):
	update_secret_key(30)
	data_js = MP_get_json_datas(path)
	glavses = MP_chapter_list(path,data_js["count_pages"])
	return render_template('choose_glav.html',
		ru_name= data_js["ru-name"],
		orig_name = data_js["orig_name"],
		descryption=data_js["descryption"],
		year=2023,
		first_page=data_js["first_glava"],
		img=data_js["img"],
		rate=data_js["rate"],
		rate_count=data_js["feedbacks"],
		status=data_js["status"],
		genre_list=data_js["jenres"],
		MP_can_see=MP_get_can_see(path),
		glav=int(data_js["glav"]),
		glavses=json.dumps(glavses,  sort_keys=True, default=str),
		all_datas = data_js,
		last_page=glavses[0]["link"],
		key=app.config['SECRET_KEY'],
		last_page_and_one="/".join(glavses[0]["link"].split('/')[::-1][1:][::-1]) +glavses[0]["link"].split('/')[-1].split('-')[0] + '-' + str(int(glavses[0]["link"].split('/')[-1].split('-')[1])+1)
	)




#STYLISH AND SCRIPT FILES :
	# with check keys
@app.route('/css/<key>/slide_bar.css')
def css_sleder_nav_css(key):
	return _check_keys(key_true=app.config['SECRET_KEY'],key=key,ok_func=['templates','fghjkl.css'],error_text='<h1>Неправильный ключ!')

@app.route('/css/<key>/index.css')
def css_index_file(key):
	return _check_keys(key_true=app.config['SECRET_KEY'],key=key,ok_func=['templates','dkfl4ls.css'],error_text='<h1>Неправильный ключ!')

@app.route('/slider/nav/<key>/slider.js')
def sleder_nav_js(key):
	return _check_keys(key_true=app.config['SECRET_KEY'],key=key,ok_func=['templates','slider_nav.js'],error_text='<h1>Неправильный ключ!')

@app.route('/slider/nav/<key>/bibl.js')
def slider_nav_bibl_js(key):
	return _check_keys(key_true=app.config['SECRET_KEY'],key=key,ok_func=['templates','23gffd.js'],error_text='<h1>Неправильный ключ!')

@app.route('/js/<string:key>/<string:fake_key>/read_scripts.js')
def read_functions_js(key,fake_key):
	return _check_keys(key_true=app.config['SECRET_KEY'],key=key,ok_func=['templates','read_scripts_oka.js'],error_text='<h1>Неправильный ключ!')

@app.route('/style/<key>/style_for_readilka.css')
def stylish_one(key):
	return _check_keys(key_true=app.config['SECRET_KEY'],key=key,ok_func=['templates/style', 'style.css'],error_text='<h1>Неправильный ключ!')

@app.route('/style/<key>/style_for_settings.css')
def style_settings_in_readilka(key):
	return _check_keys(key_true=app.config['SECRET_KEY'],key=key,ok_func=['templates/style', 'dop_styles.css'],error_text='<h1>Неправильный ключ!')

@app.route('/style/<key>/style_grid.css')
def style_search_panel(key):
	return _check_keys(key_true=app.config['SECRET_KEY'],key=key,ok_func=['templates/style', 'search_dop.css'],error_text='<h1>Неправильный ключ!')

@app.route('/css/<key>/choose_glav.css')
def style_coose_glav_page(key):
	return _check_keys(key_true=app.config['SECRET_KEY'],key=key,ok_func=['templates/style','glav.css'],error_text='<h1>Неправильный ключ!')


	# without check keys
@app.route('/img/window.png')
def window_png():
	return send_from_directory('templates/img','tpDl1E0pONrCBr0cKWCiXRSy10WlfOuC6SEDzYbx.webp')

@app.route('/test/img/<name>')
def img_name_parse(name):
	return send_from_directory('templates/index_files',name)

#END STYLISH AND SCRIPT FILES



#  SOCKETIO FUNCTIONS

# method for searching manga in ...
@socketio.on('searchThis')
def go_go(text):
	respons = search(text)
	emit('searchOk',respons)

# load next manga page of manga link and manga-chapter next
@socketio.on('nextView')
def gogo(data):
	emit('nextViewOk',see_next_page_and_this(data[0],data[1]))

# fake img on my web page. but get from other web page
@app.route('/img/posters/<rnd>/<name>/')
def fake_pictures(rnd,name):
	return requests.get(f'https://static2.mangapoisk.org/posters/{rnd}/{name}').content 

#method for load more manga
@socketio.on('load_more_pages')
def load_more_pages(link):
	os.system('cls')
	if '/chapter/null' not in link:
		try:
			manga = link["link"].split('/manga/')[1].split('/chapter/')[0]
		except:
			manga = link["link"].split('/manga/')[1].split('/chapter/')[0]

		chapter = link["link"].split('/chapter/')[1].split('/')[0]
		data = read_this_page(manga,chapter)
		for i in range(0,len(data)):
			if data[i]["img"] == None:
				data[i]["img"] = data[i]["img_placeholder"]
		#data[-1]["img"] = 'https://99px.ru/sstorage/86/2019/04/image_861004191324357138539.gif'

		dop_data = see_next_page_and_this(manga,chapter)
		data = [json.dumps(data,  sort_keys=True, default=str),json.dumps(dop_data,  sort_keys=True, default=str),f'last_viewManga={manga}; last_viewChapter={chapter}']
		print(data)
		emit('load_more_pagesOk',data)

# update secret token for load js and css
@socketio.on('update-secret-key')
def on_update_app_key(key):
	os.system('cls')
	if key == app.config["SECRET_KEY"]:
		update_secret_key()
		print(f'OLD: {key}',end='')
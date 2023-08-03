from main_page_pars import *
from pars_manga_page import *
from pars_manga_read import *

app = Flask(import_name=__name__)
app.config['SECRET_KEY'] = 'secret!'
app.debug = True
socketio = SocketIO(app,debug=True)


def update_secret_key(length=20):
	app.config['SECRET_KEY'] = ''.join(random.choices(string.ascii_letters + string.digits, k=length))
	print(' NEW: {}'.format(app.config['SECRET_KEY']))

@app.route('/search',methods=['GET','POST'])
def index_html():
	if request.args.get('q') != None:
		return render_template('main_page.html',q=request.args.get('q'))
	return render_template('main_page.html',key=app.config['SECRET_KEY'])

@socketio.on('searchThis')
def go_go(text):
	respons = search(text)
	emit('searchOk',respons)

@socketio.on('nextView')
def gogo(data):
	emit('nextViewOk',see_next_page_and_this(data[0],data[1]))


@app.route('/test/img/<name>')
def img_name_parse(name):
	return send_from_directory('templates/index_files',name)

@app.route('/img/posters/<rnd>/<name>/')
def fake_pictures(rnd,name):
	return requests.get(f'https://static2.mangapoisk.org/posters/{rnd}/{name}').content 



@app.route('/wrong_key/<error_text>/')
def wrong_key(error_text):
	return render_template('wet_wrong.html',wrong=Markup(str(error_text)+'<br><a href="/">Back to main page</a>'))

@socketio.on('update-secret-key')
def on_update_app_key(key):
	os.system('cls')
	if key == app.config["SECRET_KEY"]:
		update_secret_key()
		print(f'OLD: {key}',end='')


@app.route('/')
def index():
	update_secret_key()
	slide_templ = """<div class="swiper-slide">
		<a href="{}" class="img-container">
			<div class="shadow-container">
				<img src="{}">
			</div>
			<div class="text-lazy">{}</div>
		</a>
		<a class="last_page_link" href="{}" style="color:#889D9D;"><div class="text-desc">{}</div></a>
	  </div>"""
	s1 = ''
	s2 = ''
	s3 = ''
	s4 = ''

	datas = get_alls()
	for i in range(0,len(datas)):
		if datas[i]["simg"] == None:
			datas[i]["simg"] = datas[i]["limg"]
		datas[i]["simg"] = datas[i]["simg"].replace('https://static2.mangapoisk.org','/img')

	for s in range(0,len(datas)):
		if s <= 20:
			s1 += slide_templ.format(datas[s]["link"],datas[s]["simg"],datas[s]["name"],datas[s]["last_link"],str(' 🕰 '+datas[s]["last_update"]+' '+datas[s]["last_glav"]).replace('день','day').replace('дня','day\'s'))
		elif s > 20 and s <=40:
			s2 += slide_templ.format(datas[s]["link"],datas[s]["simg"],datas[s]["name"],datas[s]["last_link"],str(' 🕰 '+datas[s]["last_update"]+' '+datas[s]["last_glav"]).replace('день','day').replace('дня','day\'s'))
		elif s > 40 and s <= 60:
			s3 += slide_templ.format(datas[s]["link"],datas[s]["simg"],datas[s]["name"],datas[s]["last_link"],str(' 🕰 '+datas[s]["last_update"]+' '+datas[s]["last_glav"]).replace('день','day').replace('дня','day\'s'))
		elif s > 60 and s <= 80:
			s4 += slide_templ.format(datas[s]["link"],datas[s]["simg"],datas[s]["name"],datas[s]["last_link"],str(' 🕰 '+datas[s]["last_update"]+' '+datas[s]["last_glav"]).replace('день','day').replace('дня','day\'s'))

		
	return render_template('index.html',s1=Markup(s1),s2=Markup(s2),s3=Markup(s3),s4=Markup(s4),key=app.config['SECRET_KEY'])


@app.route('/manga/<manga>/chapter/<chapter>',methods=['GET'])
def manga_read(manga,chapter):
	update_secret_key(10)
	data = read_this_page(manga,chapter)
	scale = request.args.get('scale')
	if scale == None:
		scale = 0

	for i in range(0,len(data)):
		if data[i]["img"] == None:
			data[i]["img"] = data[i]["img_placeholder"]
	
	data_js = MP_get_json_datas(manga)

	user_agent = request.headers.get('User-Agent')
	if 'android' in str(user_agent).lower()  or 'iphone' in str(user_agent).lower():
		series = 'phone'
	else:
		series = 'pc'
	print(str(user_agent))
	try:
		at_page = "Том "+str(chapter).split('-')[0]+" Глава "+str(chapter).split('-')[1]
	except:
		at_page = "Глава "+str(chapter)
	return render_template('a.html',
		all_imgs=json.dumps(data,  sort_keys=True, default=str),
		link = manga,
		chapter= chapter,
		scale=scale,
		title=data_js["ru-name"],
		at_page=at_page,
		series=series,
		key = app.config['SECRET_KEY'],
		fake_key = ''.join(random.choices(string.ascii_letters + string.digits, k=35))
	)

@app.route('/manga/<manga>/chapter/<chapter>/<page>/xgemx')
def manga_read_at_book(manga,chapter,page):
	data = read_this_page(manga,chapter)
	page = int(page)
	for i in range(0,len(data)):
		if data[i]["img"] == None:
			data[i]["img"] = data[i]["img_placeholder"]
	
	return render_template('test_of_test.html',
		all_imgs=json.dumps(data,  sort_keys=True, default=str),
		page=page
	)
@socketio.on('load_more_pages')
def load_more_pages(link):
	os.system('cls')
	print(f'Get thread {link}')
	if '/chapter/null' not in link:
		try:
			manga = link["link"].split('/manga/')[1].split('/chapter/')[0]
		except:
			print(link["link"])
			manga = link["link"].split('/manga/')[1].split('/chapter/')[0]

		chapter = link["link"].split('/chapter/')[1].split('/')[0]
		data = read_this_page(manga,chapter)
		for i in range(0,len(data)):
			if data[i]["img"] == None:
				data[i]["img"] = data[i]["img_placeholder"]
		#data[-1]["img"] = 'https://99px.ru/sstorage/86/2019/04/image_861004191324357138539.gif'

		dop_data = see_next_page_and_this(manga,chapter)
		print(f'{dop_data}')
		data = [json.dumps(data,  sort_keys=True, default=str),json.dumps(dop_data,  sort_keys=True, default=str)]

		emit('load_more_pagesOk',data)
		print('Send Data')




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




#STYLISH AND SCRIPT FILES:
@app.route('/css/<key>/slide_bar.css')
def css_sleder_nav_css(key):
	if key == app.config['SECRET_KEY']:
		return send_from_directory('templates','fghjkl.css')
	return redirect('/wrong_key/<h1>Неправильный ключ!<h1>/')

@app.route('/css/<key>/index.css')
def css_index_file(key):
	if key == app.config['SECRET_KEY']:
		return send_from_directory('templates','dkfl4ls.css')
	return redirect('/wrong_key/<h1>Неправильный ключ!<h1>/')

@app.route('/slider/nav/<key>/slider.js')
def sleder_nav_js(key):
	if key == app.config['SECRET_KEY']:
		return send_from_directory('templates','slider_nav.js')
	return redirect('/wrong_key/<h1>Неправильный ключ!<h1>/') 

@app.route('/slider/nav/<key>/bibl.js')
def slider_nav_bibl_js(key):
	if key == app.config['SECRET_KEY']:
		return send_from_directory('templates','23gffd.js')
	return redirect('/wrong_key/<h1>Неправильный ключ!<h1>/')

@app.route('/js/<string:key>/<string:fake_key>/read_scripts.js')
def read_functions_js(key,fake_key):
	if key == app.config['SECRET_KEY']:
		return send_from_directory('templates','read_scripts_oka.js')
	return redirect('/wrong_key/<h1>Неправильный ключ!<h1>/')

@app.route('/style/<key>/style_for_readilka.css')
def stylish_one(key):
	if key == app.config['SECRET_KEY']:
		return send_from_directory('templates/style', 'style.css')

@app.route('/style/<key>/style_for_settings.css')
def style_settings_in_readilka(key):
	if key == app.config['SECRET_KEY']:
		return send_from_directory('templates/style', 'dop_styles.css')

@app.route('/style/<key>/style_grid.css')
def style_search_panel(key):
	if key == app.config['SECRET_KEY']:
		return send_from_directory('templates/style', 'search_dop.css')

@app.route('/img/window.png')
def window_png():
	return send_from_directory('templates/img','tpDl1E0pONrCBr0cKWCiXRSy10WlfOuC6SEDzYbx.webp')

#END STYLISH AND SCRIPT FILES

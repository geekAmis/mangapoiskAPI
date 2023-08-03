var socket = io();
window.i = 0;
window.auto = false;
window.end_of_manga = false;

if (window.series == 'phone') {
      document.querySelector('header').innerHTML = '';
    }

    function change_width() {
      for (var i = 0; i < document.querySelector('.chapter-images').children.length; i++) {
        try {
          document.querySelector('.chapter-images').children[i].width = document.querySelector('.range-size').value;
        } catch {
        }
        try {
          document.querySelector('.hidden-scale').value = document.querySelector('.range-size').value;
        } catch {
        }
      }
    }

    function get_all_idS() {
      var articls_idS = [];
      for (var i = 0; i < document.getElementById('result_box').children.length; i++) {
        articls_idS[i] = document.getElementById('result_box').children[i].id;
      }
      return articls_idS;
    }

    function hot_load_pages(data = false) {
      if (data == false) {
        this_data = JSON.parse(document.querySelector('.jsdocparse').innerHTML);
      } else {
        this_data = data;
      }
      for (var i = 0; i < this_data.length; i++) {
        if (window.scale == 0) {
          try {
            this_data[i]["width"] = document.querySelector('.range-size').value;
          } catch {
            window.scale = window.innerWidth;
          }
        } else {
          try {
            document.querySelector('.range-size').value = window.scale;
          } catch {
          }
          this_data[i]["width"] = window.scale;
        }
        if (window.i == 0) {
          document.querySelector('.full-image').src = this_data[i]["img"];
          document.querySelector('.full-image').alt = this_data[i]["alt"];
          document.querySelector('.full-image').title = document.querySelector('.full-image').alt;
          document.querySelector('.full-image').id = this_data[i]["page_id"];
          document.querySelector('.full-image').width = this_data[i]["width"];
          document.querySelector('.full-image').height = this_data[i]["height"];
        } else {
          img = document.createElement('img');
          img.classList.add("img-fluid");
          img.classList.add("page-image");
          img.classList.add("lazy");
          img.classList.add("lazy-preload");
          img.alt = this_data[i]["alt"];
          img.src = this_data[i]["img"];
          img.title = img.alt;
          img.id = this_data[i]["page_id"];
          img.width = this_data[i]["width"];
          img.height = this_data[i]["height"];
          document.querySelector('.chapter-images').appendChild(img);
        }
        window.i++;
      }
      try {
        document.querySelector('.hidden-scale').value = window.scale;
      } catch {
        console.log('OP OP  SKIBIDI')
      }
    }
    hot_load_pages();

    function hot_load_more() {
      try{
        hrefa = document.querySelector('.next-page').action;
        document.querySelector('.next-page').classList.add('hider');
        
      }catch{
        socket.emit('load_more_pages', {
          link: `${document.querySelector('form').action}`
        });
        window.end_of_manga = true;
      }
      
    }

    function nextView() {
      manga = "{{link}}";
      chapter = "{{chapter}}";
      socket.emit('nextView', [manga, chapter]);
    }

    function nextView_soft(manga, chapter) {
      socket.emit('nextView', [manga, chapter]);
    }
    socket.on('load_more_pagesOk', function(data) {
      console.log(data);
      console.log(document.querySelector('.god-dem-right').children[0])
      document.querySelector('.jsdocparse').innerHTML = data[0];
      hot_load_pages(JSON.parse(data[0]));
      let this_data = JSON.parse(data[1]);
      if (this_data["end"]) {
        window.end_of_manga = true;
        document.querySelector('.god-dem-right').children[0].removeChild(document.querySelector('.god-dem-right').children[0].children[document.querySelector('.god-dem-right').children[0].children.length - 1]);
        for (var i = 0; i < document.querySelector('.god-dem-right').children[0].children.length; i++) {
          if (document.querySelector('.god-dem-right').children[0].children[i].classList.contains('next-page')) {
            document.querySelector('.god-dem-right').children[0].removeChild(document.querySelector('.god-dem-right').children[0].children[i]);
          } else {
            console.log(document.querySelector('.god-dem-right').children[0].children[i]);
          }
        }
        document.body.innerHTML = document.body.innerHTML.replace('AT_PAGE', this_data["next_page"].replace('Глава', 'Новая глава')).replace('NAME_PAGE', this_data["name_page"]).replace('AT_PAGE', this_data["next_page"].replace('Глава', 'Новая глава') + `<hr><br><a href="${window.location.href.substring(0,window.location.href.lastIndexOf('/chapter'))}">Вернуться к манге</a>`);
        document.querySelector('.at-page').innerHTML = this_data["next_page"].replace('Глава', 'Новая глава');

      }
      try {
        document.querySelector('.next-page').innerHTML = '';
        document.querySelector('.next-page').action = JSON.parse(data[1])["next_page_link"];
        document.querySelector('.at-page').innerHTML = JSON.parse(data[1])["next_page"];
      } catch {
        console.log(this_data);
      }
    });
    socket.on('searchOk', function(data) {
      if (data["message"] == "ok") {
        for (var i = 0; i < data["results"].length; i++) {
          articl = document.createElement('li');
          articl.id = `${data["results"][i]["image"]}`
          articl.innerHTML = `
                                
                                <a href="${data["results"][i]["link"]}">
                                    <div class="search-container"><div class="search-image">
                                        <img src="${data["results"][i]["image"]}">
                                    </div>
                                    <div class="label">
                                        ${data["results"][i]["label"]}
                                    </div>
                                    <div class="search-year">
                                        ${data["results"][i]["year"]}
                                        <hr>
                                        ${data["results"][i]["updated"]}
                                    </div>
                                </a>
                                <div>
                                </div>
                            `;
          if (!get_all_idS().includes(articl.id)) {
            document.getElementById('result_box').appendChild(articl);
          } else {
            articl = '';
          }
          //data["results"][i]
        }
        for (var i = 0; i < document.getElementById('result_box').children.length; i++) {
          document.getElementById('result_box').removeChild(document.getElementById('result_box').children[i]);
        }
      }
    });
    async function on_type_text() {
      text = document.querySelector('.searchInput').value;
      await socket.emit('searchThis', text);
    }
    nextView();
    socket.on('nextViewOk', function(data) {
      if (!window.end_of_manga) {
        document.querySelector('.next-page').action = data["next_page_link"];
        document.querySelector('.next-page').innerHTML = document.querySelector('.next-page').innerHTML.replace('NEXT_PAGE', data["next_page"]);
        document.querySelector('.at-page').innerHTML = data["at_page"];
        document.querySelector('.at-page-title').innerHTML = data["at_page"];
        document.querySelector('.page-link-title').href = data["page_link"];
        document.querySelector('.page-link-title').innerHTML = document.querySelector('.page-link-title').innerHTML.replace('NAME_PAGE', data["name_page"]);
        if (window.scale != 0) {
          try {
            document.querySelector('.hidden-scale').value = window.scale;
          } catch {
          }
        }
      } else {
        document.body.innerHTML = document.body.innerHTML.replace('AT_PAGE', data["next_page"].replace('Глава', 'Новая глава')).replace('NAME_PAGE', data["name_page"]).replace('AT_PAGE', data["next_page"].replace('Глава', 'Новая глава') + `<hr><br><a href="${window.location.href.substring(0,window.location.href.lastIndexOf('/chapter'))}">Вернуться к манге</a>`);
      }
    });

    function load_all_pages_fast() {
      window.auto = true;
    }
    window.addEventListener('scroll', function() {
      document.body.innerHTML = document.body.innerHTML.replace('action="null"',`action="${window.location.href.substring(0,window.location.href.lastIndexOf('/chapter'))}"`);
      if (window.innerHeight + window.scrollY >= document.body.offsetHeight) {
        if (window.auto) {
          setTimeout(hot_load_more, 100);
        }
      }
    });



function update_keys(){
      socket.emit('update-secret-key', '{{key}}');
    }
update_keys();
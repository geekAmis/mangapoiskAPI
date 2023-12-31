# MangaPoiskAPI (Military IT Tech.)
Промывка мозгов среди мало-осведомлённого населения, зомбирование и доведения до состояния
Dead-inside

### Цели:

1. Предоставление API к парсингу mangapoisk.

2. Удобный и быстрый скриптинг с использованием fastapi

3. Изучение fastapi в рамках подготовки к разработке проекта под руководством кураторов 
**Эво***ленты*

4. Попытка дописать имеющийся у mangapoisk сайт так, как нужно лично мне и предоставление
необходимого инструментария для доработки их проекта.


### Требование к проекту:

1. Разработка простого парсера mangapoiskAPI 
2. Разработка привычной для меня системы templates в Flask, но с дополнением в виде mlx
config.
3. Доработка mlx до вида "html code 2000 len" => "mlx code 200 len" + config.
4. Оптимизация их кривого до жути "Нового" интерфейса от которого мой ноутбук компании 
irbis просто молит его убить.
5. Предоставление возможности закачивать требуемую мангу в формате .pdf или в виде 
html для чтения манги без доступа к сети. (соответственно, картинки будут либо у пользов.
на устройстве, либо представленными в виде svg и тому подобных медиа расширений)
6. Возможность  использовать MangaPoiskAPI как зеркало для сокрытия реального устройства
пользователя от Yandex метрики.
7. Благодаря игнору меня на почте так-же добавляется пунктик: Отсутствие рекламы на сайте
и возможность установить туда свою для каждого разработчика читающего этот код.
8. Возможность удобно листать и АВТО пролистывать мангу на страничке чтения
9. Возможность постить посты в группе телеграм о новинках у mangapoisk.

### Системы 

1. Привычная мне закачка template из flask обеспечивается ```frontend/mlxDecoder.py```
2. Парсинг mangapoisk обеспечивается ```api/parser/mangapoisk.py```
3. Сохранение прогресса пользователя на сайте происходит через ```В разработке```
4. Сохранение на устройсво пользователя оффлайн версии главы манги происходит через
```В разработке```
5. Поиск интересующей пользователя манги происходит через ```Скоро. В след. Обновлении```
6. Отображение сайта происходит через app.py при помощи ```uvicorn app:app --reload```
7. mlx to html | html to mlx ```В разработке```
### Требования к БД

1. MySQL для хранения cookies пользователя и его ip для последующей связи ip -> cookies
ради подгрузи данных зашедшему пользователю. (Соответственно: Добавление, Хранение)

2. mlxDB (Ещё не существует впринципе) - для хранения страничек html в виде цепочки блоков,
после добавления которой - пользователю будет удобнее загружать странички манги прямо из 
базы данных. (Планируется публичный к ней доступ на чтение)

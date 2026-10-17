-- Схема reference.sqlite. Только топонимы и их алиасы: никаких целых адресных строк (ТЗ, раздел 7).
-- Вся геометрия посчитана при сборке (scripts/build_reference): здесь только готовые привязки и доли.
PRAGMA journal_mode = OFF;

CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);

-- области и города республиканского значения (kind: oblast | city)
CREATE TABLE provinces (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, center_city_id INTEGER,
    source TEXT NOT NULL, osm_id INTEGER, kato TEXT
);
-- районы области (kind: oblast) и районы города (kind: city)
CREATE TABLE districts (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, province_id INTEGER, city_id INTEGER,
    source TEXT NOT NULL, osm_id INTEGER, kato TEXT
);
-- населённые пункты (kind: republican | city | town | village);
-- district_method: как найден район области (polygon | near | seed | kato)
CREATE TABLE cities (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, province_id INTEGER, district_id INTEGER,
    source TEXT NOT NULL, osm_id INTEGER, kato TEXT, lat REAL, lon REAL, population INTEGER, district_method TEXT
);
-- микрорайоны, жилые массивы, ЖК, кварталы
CREATE TABLE living_areas (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, type TEXT NOT NULL, city_id INTEGER, district_id INTEGER,
    source TEXT NOT NULL, osm_id INTEGER
);
-- улицы: одна строка на (город, название, тип). type_share: доля длины этого типа среди одноимённых улиц
-- города; dom_*: доминирующий район / мкр и его доля (по домам, если их >= 3, иначе по длине сегментов)
CREATE TABLE streets (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, type TEXT, city_id INTEGER, source TEXT NOT NULL,
    length_m REAL, houses INTEGER, type_share REAL,
    dom_district_id INTEGER, dom_district_share REAL, dom_area_id INTEGER, dom_area_share REAL
);
-- в каких районах города проходит улица: дома, длина сегментов внутри полигона, доля
CREATE TABLE street_districts (
    street_id INTEGER NOT NULL, district_id INTEGER NOT NULL, weight INTEGER NOT NULL DEFAULT 1,
    houses INTEGER, length_m REAL, share REAL,
    PRIMARY KEY (street_id, district_id)
);
-- то же для микрорайонов / ЖК
CREATE TABLE street_areas (
    street_id INTEGER NOT NULL, area_id INTEGER NOT NULL, houses INTEGER, length_m REAL, share REAL,
    PRIMARY KEY (street_id, area_id)
);
-- дома: номер как в источнике и ключ для сравнения; la_method: polygon | point (мкр по ближайшей точке),
-- la_dist_m: расстояние до точки мкр
CREATE TABLE houses (
    street_id INTEGER NOT NULL, number TEXT NOT NULL, key TEXT NOT NULL, district_id INTEGER,
    living_area_id INTEGER, source TEXT NOT NULL, la_method TEXT, la_dist_m REAL
);
-- объекты-ориентиры (школы, магазины, ТЦ, аптеки...): ищутся лениво по poi_aliases, в память не грузятся
CREATE TABLE pois (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, brand TEXT, city_id INTEGER,
    district_id INTEGER, living_area_id INTEGER, source TEXT NOT NULL
);
CREATE TABLE poi_aliases (key TEXT NOT NULL, poi_id INTEGER NOT NULL);
-- алиасы любых сущностей (etype: province | district | city | living_area | street);
-- lang: ru | kk | en | old | alt | official | short | loc (из какого тега OSM / поля ядра)
CREATE TABLE aliases (
    etype TEXT NOT NULL, eid INTEGER NOT NULL, alias TEXT NOT NULL, key TEXT NOT NULL, lang TEXT, source TEXT
);

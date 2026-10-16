-- Схема reference.sqlite. Только топонимы и их алиасы: никаких целых адресных строк (ТЗ, раздел 7).
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
-- населённые пункты (kind: republican | city | town | village)
CREATE TABLE cities (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, province_id INTEGER, district_id INTEGER,
    source TEXT NOT NULL, osm_id INTEGER, kato TEXT, lat REAL, lon REAL, population INTEGER
);
-- микрорайоны, жилые массивы, ЖК, кварталы
CREATE TABLE living_areas (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, type TEXT NOT NULL, city_id INTEGER, district_id INTEGER,
    source TEXT NOT NULL, osm_id INTEGER
);
-- улицы: одна строка на (город, название, тип)
CREATE TABLE streets (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, type TEXT, city_id INTEGER, source TEXT NOT NULL
);
-- в каких районах города проходит улица (weight = число домов/сегментов в районе)
CREATE TABLE street_districts (
    street_id INTEGER NOT NULL, district_id INTEGER NOT NULL, weight INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (street_id, district_id)
);
-- дома: номер как в источнике и ключ для сравнения
CREATE TABLE houses (
    street_id INTEGER NOT NULL, number TEXT NOT NULL, key TEXT NOT NULL, district_id INTEGER,
    living_area_id INTEGER, source TEXT NOT NULL
);
-- алиасы любых сущностей (etype: province | district | city | living_area | street)
CREATE TABLE aliases (
    etype TEXT NOT NULL, eid INTEGER NOT NULL, alias TEXT NOT NULL, key TEXT NOT NULL, lang TEXT, source TEXT
);

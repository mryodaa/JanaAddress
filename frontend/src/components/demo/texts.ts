import type { Language } from "../../i18n/types";

// тексты демо-страницы отдельно от общего словаря: их много и они нужны только здесь
export interface DemoTexts {
  nav: string;
  title: string;
  subtitle: string;
  run: string;
  running: string;
  placeholder: string;
  examples: string;
  stageOf: string;
  tool: string;
  play: string;
  pause: string;
  prev: string;
  next: string;
  speed: string;
  autoNext: string;
  autoNextHint: string;
  waitNext: string;
  skip: string;
  replay: string;
  another: string;
  demoNote: string;
  stages: Record<StageId, { title: string; lead: string; tool: string; toolDetail: string }>;
  cleanNothing: string;
  cleanRemoved: string;
  layoutFixed: string;
  tokenKinds: Record<string, string>;
  tokensCount: string;
  bilingualNone: string;
  bilingualKept: string;
  bilingualDropped: string;
  partsDropped: string;
  rulesNone: string;
  fieldSlots: string;
  taggerSweep: string;
  taggerSpans: string;
  taggerOff: string;
  noiseLabel: string;
  kzDupLabel: string;
  arbiterRules: string;
  arbiterModel: string;
  arbiterDecision: string;
  decisions: Record<string, string>;
  arbiterNone: string;
  refNone: string;
  refStats: string;
  refSources: Record<string, string>;
  confParts: Record<string, string>;
  confFinal: string;
  // отчёт
  reportTitle: string;
  reportLead: string;
  verdictHigh: string;
  verdictMid: string;
  verdictLow: string;
  envelope: string;
  envelopeEmpty: string;
  fieldsTitle: string;
  whereFrom: string;
  fromString: string;
  notFound: string;
  agreementTitle: string;
  agreeCount: string;
  disputeCount: string;
  singleCount: string;
  confTitle: string;
  timingTitle: string;
  timingNote: string;
  totalTime: string;
  unparsedTitle: string;
  unparsedNone: string;
  jsonTitle: string;
  coverageTitle: string;
  coverageParts: { fields: string; markers: string; dropped: string; unparsed: string };
  coverageFilled: string;
  coverageFromString: string;
  coverageFromRef: string;
  copy: string;
  copied: string;
  modelFacts: string;
  refFacts: string;
  facts: { streets: string; houses: string; cities: string; f1: string; size: string };
  // пояснения к значку «?»: откуда число и как считается
  hintLabel: string;
  hints: Record<HintId, string>;
}

export type HintId =
  | "confidence"
  | "verdict"
  | "envelope"
  | "agreement"
  | "modelF1"
  | "refFacts"
  | "fields"
  | "confParts"
  | "timing"
  | "unparsed"
  | "json"
  | "coverage"
  | "taggerSpans"
  | "arbiterScore";

export type StageId =
  | "clean"
  | "tokens"
  | "bilingual"
  | "rules"
  | "tagger"
  | "arbiter"
  | "reference"
  | "confidence";

const ru: DemoTexts = {
  nav: "Демо",
  title: "Как Jana Address читает адрес",
  subtitle:
    "Введите адрес как его пишут люди: с опечатками, сокращениями, на двух языках. Покажем по шагам, что происходит внутри.",
  run: "Показать разбор",
  running: "Разбираем…",
  placeholder: "Например: г.Алматы, мкр.Самал-2 д.5 кв.12 4подьезд",
  examples: "Попробуйте:",
  stageOf: "Шаг {n} из {total}",
  tool: "Инструмент",
  play: "Продолжить",
  pause: "Пауза",
  prev: "Назад",
  next: "Дальше",
  speed: "Скорость",
  autoNext: "Автопереход",
  autoNextHint: "Выключите, чтобы шаг доигрывал анимацию и ждал кнопки → (или стрелки). Клавиша A.",
  waitNext: "Шаг показан. Дальше: → или стрелка вправо",
  skip: "Сразу к результату",
  replay: "Смотреть анимацию снова",
  another: "Другой адрес",
  demoNote: "Анимация замедлена для наглядности: на самом деле весь разбор занимает миллисекунды.",
  stages: {
    clean: {
      title: "Очистка",
      lead: "Убираем невидимые символы, лишние пробелы и чиним текст, набранный в английской раскладке. Оригинал при этом не меняется.",
      tool: "Нормализация Unicode",
      toolDetail: "Карта смещений к оригиналу: каждое поле потом вырезается из исходной строки байт в байт.",
    },
    tokens: {
      title: "Токены",
      lead: "Режем строку на слова, числа и разделители. «55/6» остаётся одним числом, «4подьезд» делится на число и слово.",
      tool: "Токенизатор",
      toolDetail: "Регулярные выражения с позициями токенов в исходной строке.",
    },
    bilingual: {
      title: "Два языка и лишнее",
      lead: "Находим дубли «город Актобе/Ақтөбе қаласы» и названия организаций, которые к адресу не относятся.",
      tool: "Правила склеек",
      toolDetail: "Слэш между словами означает перевод, а между цифрами дробь номера дома.",
    },
    rules: {
      title: "Правила",
      lead: "Ищем маркеры («ул», «мкр», «кв», «подъезд»), город и район по справочнику, номера по позиции.",
      tool: "Словари маркеров + справочник",
      toolDetail: "YAML-словари: маркеры, типы улиц, ориентиры, административные единицы.",
    },
    tagger: {
      title: "Нейросеть",
      lead: "Посимвольная модель независимо размечает ту же строку. Она не знает правил и не пишет значения сама, только предлагает спаны.",
      tool: "BiLSTM-CRF, ONNX",
      toolDetail: "2 слоя × 128, 27 BIO-тегов, int8 ONNX, onnxruntime + декодер Витерби.",
    },
    arbiter: {
      title: "Арбитр",
      lead: "Сравниваем правила и модель по каждому полю. Если они спорят, кандидаты проверяются справочником и грамматикой.",
      tool: "Арбитр",
      toolDetail:
        "Проверки: город существует, улица есть в городе, дом на улице, этаж ≤ 40. Веса подобраны на dev-наборе.",
    },
    reference: {
      title: "Справочник",
      lead: "Дополняем то, чего нет в строке: область, район, жилой массив. Значения из строки справочник не перезаписывает.",
      tool: "SQLite-справочник",
      toolDetail: "OSM + КАТО, индексные запросы и нечёткий поиск rapidfuzz. Без сети.",
    },
    confidence: {
      title: "Уверенность",
      lead: "Собираем оценку из понятных слагаемых: сколько строки разобрано, что нашлось в справочнике, согласились ли правила и модель.",
      tool: "Аддитивная модель",
      toolDetail: "Веса в rules/confidence.yaml, калибровка проверяется на отложенных наборах.",
    },
  },
  cleanNothing: "Строка чистая: удалять нечего.",
  cleanRemoved: "Удалено символов: {n}",
  layoutFixed: "Английская раскладка → русская",
  tokenKinds: { w: "слово", n: "число", s: "разделитель", p: "знак" },
  tokensCount: "{n} токенов",
  bilingualNone: "Дублей на втором языке и названий организаций нет.",
  bilingualKept: "оставлено",
  bilingualDropped: "отброшено",
  partsDropped: "не адрес",
  rulesNone: "Правила ничего не нашли.",
  fieldSlots: "Поля",
  taggerSweep: "Модель читает строку по символам",
  taggerSpans: "Предложенные спаны и вероятность",
  taggerOff: "Модель в этой сборке выключена: разбор только по правилам.",
  noiseLabel: "мусор",
  kzDupLabel: "дубль на каз.",
  arbiterRules: "Правила",
  arbiterModel: "Модель",
  arbiterDecision: "Решение",
  decisions: {
    agree: "совпали",
    rules: "спор → правила",
    model: "спор → модель",
    rules_only: "только правила",
    model_only: "только модель",
  },
  arbiterNone: "Сравнивать нечего: модель выключена или полей нет.",
  refNone: "Всё нужное уже есть в строке: справочник ничего не добавил.",
  refStats: "В справочнике",
  refSources: {
    seed: "базовый справочник",
    kato: "КАТО",
    "osm:house": "OSM: найден дом",
    "osm:street": "OSM: по улице",
    "osm:polygon": "OSM: полигон",
    "osm:point": "OSM: ближайшая точка",
    "osm:poi": "OSM: по ориентиру",
  },
  confParts: {
    base: "База",
    consumed: "Разобрана вся строка",
    street_name: "Есть улица",
    house: "Есть дом",
    admin: "Есть город/область",
    unparsed: "Неразобранный остаток",
    no_street_house: "Нет ни улицы, ни дома",
    "flag:model_agree_all": "Правила и модель согласны",
    "flag:model_disagree": "Модель где-то не согласна",
    "flag:model_override": "Модель переспорила правила",
    "flag:layout_fixed": "Чинили раскладку",
    "flag:guessed_street": "Улица угадана без маркера",
    "flag:guessed_city": "Город угадан",
    "flag:extra_numbers": "Лишние числа",
    "flag:fuzzy_admin": "Город найден нечётко",
    "flag:district_ambiguous": "Улица в нескольких районах",
    "flag:ambiguous_orientation": "Неясно, к чему относятся числа",
    "flag:street_in_reference": "Улица есть в справочнике",
    "flag:house_in_reference": "Дом есть в справочнике",
    min_score: "Надёжность полей из строки",
    cap: "Ограничение 0,99",
    "flag:street_not_in_reference": "Улицы нет в справочнике",
    "flag:street_type_dominant": "Тип улицы по справочнику",
    "flag:living_area_by_point": "Мкр по ближайшей точке",
    "flag:living_area_ambiguous": "Улица в нескольких мкр",
    "flag:district_by_near_polygon": "Село у границы района",
    "flag:building_part_ignored": "Корпус без дома",
    "flag:house_like_area_number": "Дом похож на номер мкр",
    "flag:marker_without_number": "Маркер без номера",
  },
  confFinal: "Итог",
  reportTitle: "Подробный анализ",
  reportLead: "Всё, что сервис понял из строки, и откуда взялось каждое значение.",
  verdictHigh: "Уверенный разбор",
  verdictMid: "Разбор правдоподобный, но стоит взглянуть",
  verdictLow: "Нужна проверка оператором",
  envelope: "Как на конверте",
  envelopeEmpty: "Недостаточно данных, чтобы собрать адрес",
  fieldsTitle: "Поля и их происхождение",
  whereFrom: "Откуда",
  fromString: "из строки, символы {a}–{b}",
  notFound: "не найдено",
  agreementTitle: "Правила и нейросеть",
  agreeCount: "совпали",
  disputeCount: "спорили",
  singleCount: "нашёл кто-то один",
  confTitle: "Из чего сложилась уверенность",
  timingTitle: "Реальное время по шагам",
  timingNote: "Первый запрос после запуска дольше: прогреваются индексы справочника.",
  totalTime: "Всего",
  unparsedTitle: "Не разобрано",
  unparsedNone: "Каждый кусок строки попал в какое-то поле.",
  jsonTitle: "Ответ API",
  coverageTitle: "Покрытие строки",
  coverageParts: {
    fields: "в поля",
    markers: "служебные слова и знаки",
    dropped: "отброшено: дубль, организация",
    unparsed: "не разобрано",
  },
  coverageFilled: "Заполнено полей: {n} из {total}",
  coverageFromString: "из строки",
  coverageFromRef: "из справочника",
  copy: "Копировать",
  copied: "Скопировано",
  modelFacts: "Модель",
  refFacts: "Справочник",
  facts: {
    streets: "улиц",
    houses: "домов",
    cities: "населённых пунктов",
    f1: "F1 по спанам на отложенном наборе",
    size: "размер модели",
  },
  hintLabel: "Подробнее",
  hints: {
    confidence:
      "Вероятность, что все поля метрики жюри в этой записи верны. Считается логистической регрессией по признакам разбора; веса подобраны на размеченных dev-наборах (8000 синтетических и 389 живых строк), вручную не задаются. Ниже {pct}% запись попадает в «Неуверенные».",
    verdict:
      "{pct}% и выше — уверенный разбор, ниже — стоит проверить оператору. Порог подобран на dev: на живых строках на проверку уходит 13% записей, и в них 6 из 8 ошибок.",
    envelope:
      "Поля ответа в привычном виде: улица и номера, мкр и район, город и область. Это только представление, значения те же, что в JSON ниже.",
    agreement:
      "Каждое поле независимо ищут два разборщика: правила (шаги и словари YAML) и нейросеть. «Совпали» — выделили один и тот же кусок строки. «Спорили» — варианты разные, арбитр выбрал тот, что лучше подтверждён справочником и грамматикой. «Нашёл кто-то один» — поле есть только у одного; от модели такое поле берётся лишь при высоком счёте.",
    modelF1:
      "Span F1 на отложенном наборе unseen: 3000 синтетических строк с улицами и сёлами, которых модель не видела при обучении. Спан засчитывается при точном совпадении границ и метки. Это качество поиска границ полей, а не итоговая метрика жюри.",
    refFacts:
      "Справочник reference.sqlite собран нашими скриптами из OpenStreetMap (дамп Geofabrik) и классификатора КАТО. Улица — уникальное сочетание города, названия и типа; дом — с номером и привязкой к району и мкр. Числа берутся из /api/v1/health запущенного сервиса.",
    fields:
      "У каждого поля указан источник. «Из строки, символы a–b» — значение вырезано из исходной строки по этим позициям, без исправлений. Зелёная метка — поля в строке не было, оно восстановлено по справочнику (найденный дом, улица, полигон района, ближайшая точка мкр, ориентир, КАТО). Значение из строки справочник никогда не перезаписывает.",
    confParts:
      "Как сложилась вероятность: база — вероятность без признаков, дальше вклад каждого признака по порядку, в долях вероятности. Сумма вкладов равна итогу. Веса подобраны по данным (training/fit_confidence.py). «Ограничение 0,99» — итог не выше 0,99.",
    timing:
      "Реальное время каждого шага на сервере для этой строки (из trace ответа), в миллисекундах. Шкала корневая, чтобы короткие шаги тоже были видны. Анимация на сцене замедлена специально.",
    unparsed:
      "Слова и числа, которые не забрал ни один шаг и ни одно поле. Остаток учитывается в уверенности.",
    json: "Ровно то, что вернёт POST /api/v1/parse/batch: id и raw_address без изменений, 11 полей (null, если поле не определено) и confidence.",
    coverage:
      "Из чего состоит строка, по символам без пробелов. «В поля» — символы, вырезанные в значения полей. «Служебные слова» — маркеры и знаки вроде «г.», «кв», запятых: они помогли разбору, но в значение не входят. «Отброшено» — казахский дубль после слэша и названия организаций.",
    taggerSpans:
      "p — вероятность спана по модели, откалиброванная на отложенной синтетике val. Модель только показывает, где поле; значение всегда вырезается из исходной строки.",
    arbiterScore:
      "Число рядом с вариантом — счёт арбитра (логит): доверие к источнику + вероятность × вес + проверки справочником (город существует, улица есть в этом городе, дом есть на улице) и грамматикой (этаж ≤ 40, подъезд ≤ 20). Веса подобраны логистической регрессией на dev. Побеждает больший счёт.",
  },
};

const kk: DemoTexts = {
  ...ru,
  nav: "Демо",
  title: "Jana Address мекенжайды қалай оқиды",
  subtitle:
    "Мекенжайды адамдар жазғандай енгізіңіз: қателермен, қысқартулармен, екі тілде. Ішінде не болатынын қадамдап көрсетеміз.",
  run: "Талдауды көрсету",
  running: "Талдап жатырмыз…",
  placeholder: "Мысалы: г.Алматы, мкр.Самал-2 д.5 кв.12 4подьезд",
  examples: "Байқап көріңіз:",
  stageOf: "{total} қадамның {n}-і",
  tool: "Құрал",
  play: "Жалғастыру",
  pause: "Үзіліс",
  prev: "Артқа",
  next: "Әрі қарай",
  speed: "Жылдамдық",
  autoNext: "Автоауысу",
  autoNextHint: "Өшірсеңіз, қадам анимациясын аяқтап, → батырмасын (немесе көрсеткіні) күтеді. A пернесі.",
  waitNext: "Қадам көрсетілді. Әрі қарай: → немесе оң көрсеткі",
  skip: "Бірден нәтижеге",
  replay: "Анимацияны қайта көру",
  another: "Басқа мекенжай",
  demoNote: "Анимация көрнекілік үшін баяулатылған: шын мәнінде бүкіл талдау миллисекундтар алады.",
  stages: {
    clean: {
      title: "Тазалау",
      lead: "Көзге көрінбейтін таңбаларды, артық бос орындарды алып тастаймыз, ағылшын пернетақтасында терілген мәтінді түзетеміз. Түпнұсқа өзгермейді.",
      tool: "Unicode нормализациясы",
      toolDetail: "Түпнұсқаға ығысу картасы: әр өріс кейін бастапқы жолдан дәл сол күйінде қиылады.",
    },
    tokens: {
      title: "Токендер",
      lead: "Жолды сөздерге, сандарға және бөлгіштерге бөлеміз. «55/6» бір сан болып қалады, «4подьезд» сан мен сөзге бөлінеді.",
      tool: "Токенизатор",
      toolDetail: "Бастапқы жолдағы позициялары бар тұрақты өрнектер.",
    },
    bilingual: {
      title: "Екі тіл және артығы",
      lead: "«город Актобе/Ақтөбе қаласы» сияқты қайталауларды және мекенжайға қатысы жоқ ұйым атауларын табамыз.",
      tool: "Біріктіру ережелері",
      toolDetail: "Сөздер арасындағы слэш аударманы, сандар арасындағысы үй нөмірінің бөлшегін білдіреді.",
    },
    rules: {
      title: "Ережелер",
      lead: "Маркерлерді («ул», «мкр», «кв», «подъезд»), анықтамалық бойынша қала мен ауданды, позиция бойынша нөмірлерді іздейміз.",
      tool: "Маркер сөздіктері + анықтамалық",
      toolDetail: "YAML сөздіктер: маркерлер, көше түрлері, бағдарлар, әкімшілік бірліктер.",
    },
    tagger: {
      title: "Нейрожелі",
      lead: "Таңбалық модель сол жолды өз бетінше белгілейді. Ол ережелерді білмейді және мәнді өзі жазбайды, тек спандарды ұсынады.",
      tool: "BiLSTM-CRF, ONNX",
      toolDetail: "2 қабат × 128, 27 BIO тег, int8 ONNX, onnxruntime + Витерби декодері.",
    },
    arbiter: {
      title: "Төреші",
      lead: "Әр өріс бойынша ережелер мен модельді салыстырамыз. Келіспесе, үміткерлер анықтамалықпен және грамматикамен тексеріледі.",
      tool: "Төреші",
      toolDetail:
        "Тексерулер: қала бар, көше қалада бар, үй көшеде, қабат ≤ 40. Салмақтар dev жиынында таңдалған.",
    },
    reference: {
      title: "Анықтамалық",
      lead: "Жолда жоқ нәрсені толықтырамыз: облыс, аудан, тұрғын алап. Жолдағы мәндерді анықтамалық қайта жазбайды.",
      tool: "SQLite анықтамалығы",
      toolDetail: "OSM + ҚАТО, индекстік сұраулар және rapidfuzz анық емес іздеуі. Желісіз.",
    },
    confidence: {
      title: "Сенімділік",
      lead: "Бағаны түсінікті қосылғыштардан жинаймыз: жолдың қанша бөлігі талданды, анықтамалықта не табылды, ережелер мен модель келісті ме.",
      tool: "Аддитивті модель",
      toolDetail: "Салмақтар rules/confidence.yaml ішінде, калибрлеу бөлек жиындарда тексеріледі.",
    },
  },
  cleanNothing: "Жол таза: алып тастайтын ештеңе жоқ.",
  cleanRemoved: "Жойылған таңбалар: {n}",
  layoutFixed: "Ағылшын пернетақтасы → орысша",
  tokenKinds: { w: "сөз", n: "сан", s: "бөлгіш", p: "белгі" },
  tokensCount: "{n} токен",
  bilingualNone: "Екінші тілдегі қайталау және ұйым атаулары жоқ.",
  bilingualKept: "қалдырылды",
  bilingualDropped: "алынып тасталды",
  partsDropped: "мекенжай емес",
  rulesNone: "Ережелер ештеңе таппады.",
  fieldSlots: "Өрістер",
  taggerSweep: "Модель жолды таңба бойынша оқиды",
  taggerSpans: "Ұсынылған спандар және ықтималдық",
  taggerOff: "Бұл жинақта модель өшірулі: талдау тек ережелер бойынша.",
  noiseLabel: "қоқыс",
  kzDupLabel: "қаз. қайталау",
  arbiterRules: "Ережелер",
  arbiterModel: "Модель",
  arbiterDecision: "Шешім",
  decisions: {
    agree: "сәйкес",
    rules: "дау → ережелер",
    model: "дау → модель",
    rules_only: "тек ережелер",
    model_only: "тек модель",
  },
  arbiterNone: "Салыстыратын ештеңе жоқ: модель өшірулі немесе өрістер жоқ.",
  refNone: "Қажеттінің бәрі жолда бар: анықтамалық ештеңе қоспады.",
  refStats: "Анықтамалықта",
  refSources: {
    seed: "негізгі анықтамалық",
    kato: "ҚАТО",
    "osm:house": "OSM: үй табылды",
    "osm:street": "OSM: көше бойынша",
    "osm:polygon": "OSM: полигон",
    "osm:point": "OSM: ең жақын нүкте",
    "osm:poi": "OSM: бағдар бойынша",
  },
  confParts: {
    ...ru.confParts,
    base: "База",
    consumed: "Бүкіл жол талданды",
    street_name: "Көше бар",
    house: "Үй бар",
    admin: "Қала/облыс бар",
    unparsed: "Талданбаған қалдық",
    no_street_house: "Көше де, үй де жоқ",
    "flag:model_agree_all": "Ережелер мен модель келісті",
    "flag:model_disagree": "Модель бір жерде келіспеді",
    "flag:street_in_reference": "Көше анықтамалықта бар",
    "flag:house_in_reference": "Үй анықтамалықта бар",
    min_score: "Жолдан алынған өрістердің сенімділігі",
    cap: "Шектеу 0,99",
  },
  confFinal: "Қорытынды",
  reportTitle: "Толық талдау",
  reportLead: "Сервис жолдан не түсінді және әр мән қайдан алынды.",
  verdictHigh: "Сенімді талдау",
  verdictMid: "Талдау шындыққа ұқсас, бірақ қарап шыққан жөн",
  verdictLow: "Оператордың тексеруі қажет",
  envelope: "Конверттегідей",
  envelopeEmpty: "Мекенжайды құрастыруға деректер жеткіліксіз",
  fieldsTitle: "Өрістер және олардың шығу тегі",
  whereFrom: "Қайдан",
  fromString: "жолдан, {a}–{b} таңбалар",
  notFound: "табылмады",
  agreementTitle: "Ережелер және нейрожелі",
  agreeCount: "сәйкес",
  disputeCount: "дауласты",
  singleCount: "біреуі ғана тапты",
  confTitle: "Сенімділік неден құралды",
  timingTitle: "Қадамдар бойынша нақты уақыт",
  timingNote: "Іске қосылғаннан кейінгі алғашқы сұрау ұзағырақ: анықтамалық индекстері қызады.",
  totalTime: "Барлығы",
  unparsedTitle: "Талданбады",
  unparsedNone: "Жолдың әр бөлігі қандай да бір өріске түсті.",
  jsonTitle: "API жауабы",
  coverageTitle: "Жолды қамту",
  coverageParts: {
    fields: "өрістерге",
    markers: "қызметтік сөздер мен белгілер",
    dropped: "алынып тасталды: қайталау, ұйым",
    unparsed: "талданбады",
  },
  coverageFilled: "Толтырылған өрістер: {total} ішінен {n}",
  coverageFromString: "жолдан",
  coverageFromRef: "анықтамалықтан",
  copy: "Көшіру",
  copied: "Көшірілді",
  modelFacts: "Модель",
  refFacts: "Анықтамалық",
  facts: {
    streets: "көше",
    houses: "үй",
    cities: "елді мекен",
    f1: "бөлек жиындағы спандар бойынша F1",
    size: "модель көлемі",
  },
  hintLabel: "Толығырақ",
  hints: {
    confidence:
      "Осы жазбадағы жюри метрикасының барлық өрістері дұрыс болу ықтималдығы. Талдау белгілері бойынша логистикалық регрессиямен есептеледі; салмақтар белгіленген dev-жиындарда таңдалған (8000 синтетикалық және 389 нақты жол), қолмен берілмейді. {pct}%-дан төмен болса, жазба «Сенімсіздерге» түседі.",
    verdict:
      "{pct}% және жоғары — сенімді талдау, төмен болса — операторға қарап шыққан жөн. Шек dev-те таңдалған: нақты жолдарда жазбалардың 13%-ы тексеруге түседі, оларда 8 қатенің 6-уы бар.",
    envelope:
      "Жауап өрістері әдеттегі түрде: көше мен нөмірлер, шағын аудан мен аудан, қала мен облыс. Бұл тек көрініс, мәндер төмендегі JSON-дағымен бірдей.",
    agreement:
      "Әр өрісті екі талдағыш өз бетінше іздейді: ережелер (қадамдар мен YAML сөздіктері) және нейрожелі. «Келісті» — жолдың бір бөлігін белгіледі. «Дауласты» — нұсқалары әртүрлі, арбитр анықтамалық пен грамматика жақсырақ растаған нұсқаны таңдады. «Біреуі ғана тапты» — өріс тек біреуінде бар; модельден мұндай өріс жоғары ұпайда ғана алынады.",
    modelF1:
      "unseen бөлек жиынындағы span F1: модель оқуда көрмеген көшелер мен ауылдары бар 3000 синтетикалық жол. Спан шекаралары мен белгісі дәл сәйкес келсе ғана есептеледі. Бұл өріс шекараларын табу сапасы, жюридің қорытынды метрикасы емес.",
    refFacts:
      "reference.sqlite анықтамалығын біздің скрипттер OpenStreetMap (Geofabrik дампы) мен КАТО жіктеуішінен жинады. Көше — қала, атау және түрдің бірегей тіркесі; үй — нөмірі және ауданға, шағын ауданға байланысы бар. Сандар іске қосылған сервистің /api/v1/health жауабынан алынады.",
    fields:
      "Әр өрістің көзі көрсетілген. «Жолдан, a–b таңбалар» — мән бастапқы жолдан осы позициялар бойынша қиылған, түзетусіз. Жасыл белгі — өріс жолда болмаған, анықтамалық бойынша қалпына келтірілген (табылған үй, көше, аудан полигоны, шағын ауданның жақын нүктесі, бағдар, КАТО). Жолдан алынған мәнді анықтамалық ешқашан ауыстырмайды.",
    confParts:
      "Ықтималдық қалай құралды: база — белгілерсіз ықтималдық, әрі қарай әр белгінің үлесі ретімен, ықтималдық үлесінде. Үлестердің қосындысы қорытындыға тең. Салмақтар деректер бойынша таңдалған (training/fit_confidence.py). «Шектеу 0,99» — қорытынды 0,99-дан аспайды.",
    timing:
      "Осы жол үшін әр қадамның сервердегі нақты уақыты (жауаптың trace-інен), миллисекундпен. Қысқа қадамдар да көрінуі үшін шкала түбірлік. Сахнадағы анимация әдейі баяулатылған.",
    unparsed: "Ешбір қадам да, ешбір өріс те алмаған сөздер мен сандар. Қалдық сенімділікте ескеріледі.",
    json: "POST /api/v1/parse/batch қайтаратын дәл сол нәтиже: id мен raw_address өзгеріссіз, 11 өріс (анықталмаса null) және confidence.",
    coverage:
      "Жол неден тұрады, бос орынсыз таңбалар бойынша. «Өрістерге» — өріс мәндеріне қиылған таңбалар. «Қызметтік сөздер» — «г.», «кв», үтір сияқты маркерлер мен белгілер: талдауға көмектесті, бірақ мәнге кірмейді. «Алынып тасталды» — слэштен кейінгі қазақша қайталау және ұйым атаулары.",
    taggerSpans:
      "p — модель бойынша спан ықтималдығы, val бөлек синтетикасында калибрленген. Модель тек өріс қайда екенін көрсетеді; мән әрқашан бастапқы жолдан қиылады.",
    arbiterScore:
      "Нұсқаның жанындағы сан — арбитр ұпайы (логит): көзге сенім + ықтималдық × салмақ + анықтамалық тексерулері (қала бар, көше осы қалада бар, үй көшеде бар) және грамматика (қабат ≤ 40, кіреберіс ≤ 20). Салмақтар dev-те логистикалық регрессиямен таңдалған. Үлкен ұпай жеңеді.",
  },
};

const en: DemoTexts = {
  ...ru,
  nav: "Demo",
  title: "How Jana Address reads an address",
  subtitle:
    "Type an address the way people write it: typos, abbreviations, two languages. We'll show step by step what happens inside.",
  run: "Show the parse",
  running: "Parsing…",
  placeholder: "e.g. г.Алматы, мкр.Самал-2 д.5 кв.12 4подьезд",
  examples: "Try:",
  stageOf: "Step {n} of {total}",
  tool: "Tool",
  play: "Resume",
  pause: "Pause",
  prev: "Back",
  next: "Next",
  speed: "Speed",
  autoNext: "Auto-advance",
  autoNextHint: "Turn off to let each step finish its animation and wait for → (or the arrow key). Key A.",
  waitNext: "Step shown. Next: → or the right arrow",
  skip: "Skip to result",
  replay: "Watch again",
  another: "Another address",
  demoNote: "The animation is slowed down for clarity: the real parse takes milliseconds.",
  stages: {
    clean: {
      title: "Cleanup",
      lead: "Remove invisible characters and extra spaces, fix text typed in the English keyboard layout. The original is never changed.",
      tool: "Unicode normalisation",
      toolDetail:
        "An offset map back to the original: every field is later cut from the input string byte for byte.",
    },
    tokens: {
      title: "Tokens",
      lead: "Split the string into words, numbers and separators. “55/6” stays one number, “4подьезд” splits into a number and a word.",
      tool: "Tokenizer",
      toolDetail: "Regular expressions that keep token positions in the original string.",
    },
    bilingual: {
      title: "Two languages and noise",
      lead: "Find duplicates like “город Актобе/Ақтөбе қаласы” and company names that are not part of the address.",
      tool: "Merge rules",
      toolDetail: "A slash between words means a translation; between digits it's a house number fraction.",
    },
    rules: {
      title: "Rules",
      lead: "Look for markers (“ул”, “мкр”, “кв”, “подъезд”), city and district via the reference, numbers by position.",
      tool: "Marker dictionaries + reference",
      toolDetail: "YAML dictionaries: markers, street types, landmarks, administrative units.",
    },
    tagger: {
      title: "Neural network",
      lead: "A character-level model labels the same string independently. It knows no rules and never writes values itself; it only proposes spans.",
      tool: "BiLSTM-CRF, ONNX",
      toolDetail: "2 layers × 128, 27 BIO tags, int8 ONNX, onnxruntime + Viterbi decoder.",
    },
    arbiter: {
      title: "Arbiter",
      lead: "Compare rules and model field by field. When they disagree, candidates are checked against the reference and grammar.",
      tool: "Arbiter",
      toolDetail:
        "Checks: the city exists, the street is in the city, the house is on the street, floor ≤ 40. Weights fitted on dev data.",
    },
    reference: {
      title: "Reference",
      lead: "Fill in what the string lacks: region, district, residential area. Values found in the string are never overwritten.",
      tool: "SQLite reference",
      toolDetail: "OSM + KATO, index lookups and rapidfuzz fuzzy matching. No network.",
    },
    confidence: {
      title: "Confidence",
      lead: "Build the score from readable terms: how much of the string was parsed, what was found in the reference, whether rules and model agreed.",
      tool: "Additive model",
      toolDetail: "Weights in rules/confidence.yaml; calibration is checked on held-out sets.",
    },
  },
  cleanNothing: "The string is clean: nothing to remove.",
  cleanRemoved: "Characters removed: {n}",
  layoutFixed: "English layout → Russian",
  tokenKinds: { w: "word", n: "number", s: "separator", p: "punctuation" },
  tokensCount: "{n} tokens",
  bilingualNone: "No second-language duplicates or company names.",
  bilingualKept: "kept",
  bilingualDropped: "dropped",
  partsDropped: "not an address",
  rulesNone: "The rules found nothing.",
  fieldSlots: "Fields",
  taggerSweep: "The model reads the string character by character",
  taggerSpans: "Proposed spans and probability",
  taggerOff: "The model is off in this build: rules only.",
  noiseLabel: "noise",
  kzDupLabel: "Kazakh duplicate",
  arbiterRules: "Rules",
  arbiterModel: "Model",
  arbiterDecision: "Decision",
  decisions: {
    agree: "agree",
    rules: "dispute → rules",
    model: "dispute → model",
    rules_only: "rules only",
    model_only: "model only",
  },
  arbiterNone: "Nothing to compare: the model is off or there are no fields.",
  refNone: "Everything was already in the string: the reference added nothing.",
  refStats: "In the reference",
  refSources: {
    seed: "core reference",
    kato: "KATO",
    "osm:house": "OSM: house found",
    "osm:street": "OSM: by street",
    "osm:polygon": "OSM: polygon",
    "osm:point": "OSM: nearest point",
    "osm:poi": "OSM: by landmark",
  },
  confParts: {
    ...ru.confParts,
    base: "Base",
    consumed: "Whole string parsed",
    street_name: "Has a street",
    house: "Has a house",
    admin: "Has a city/region",
    unparsed: "Unparsed leftovers",
    no_street_house: "Neither street nor house",
    "flag:model_agree_all": "Rules and model agree",
    "flag:model_disagree": "Model disagrees somewhere",
    "flag:model_override": "Model overrode the rules",
    "flag:layout_fixed": "Keyboard layout was fixed",
    "flag:guessed_street": "Street guessed without a marker",
    "flag:street_in_reference": "Street is in the reference",
    "flag:house_in_reference": "House is in the reference",
    min_score: "Reliability of fields from the string",
    cap: "Capped at 0.99",
    "flag:street_not_in_reference": "Street not in the reference",
  },
  confFinal: "Total",
  reportTitle: "Detailed analysis",
  reportLead: "Everything the service understood from the string, and where each value came from.",
  verdictHigh: "Confident parse",
  verdictMid: "Plausible parse, but worth a look",
  verdictLow: "Needs operator review",
  envelope: "As on an envelope",
  envelopeEmpty: "Not enough data to assemble the address",
  fieldsTitle: "Fields and where they came from",
  whereFrom: "Source",
  fromString: "from the string, chars {a}–{b}",
  notFound: "not found",
  agreementTitle: "Rules vs neural network",
  agreeCount: "agreed",
  disputeCount: "disputed",
  singleCount: "found by one only",
  confTitle: "What the confidence is made of",
  timingTitle: "Real time per step",
  timingNote: "The first request after startup is slower: reference indexes warm up.",
  totalTime: "Total",
  unparsedTitle: "Unparsed",
  unparsedNone: "Every part of the string went into some field.",
  jsonTitle: "API response",
  coverageTitle: "String coverage",
  coverageParts: {
    fields: "into fields",
    markers: "service words and punctuation",
    dropped: "dropped: duplicate, company",
    unparsed: "unparsed",
  },
  coverageFilled: "Fields filled: {n} of {total}",
  coverageFromString: "from the string",
  coverageFromRef: "from the reference",
  copy: "Copy",
  copied: "Copied",
  modelFacts: "Model",
  refFacts: "Reference",
  facts: {
    streets: "streets",
    houses: "houses",
    cities: "settlements",
    f1: "span F1 on a held-out set",
    size: "model size",
  },
  hintLabel: "Details",
  hints: {
    confidence:
      "Probability that every jury-metric field in this record is correct. Computed by logistic regression over parse features; weights are fitted on labelled dev sets (8000 synthetic and 389 real-world lines), none are set by hand. Below {pct}% the record goes to “Uncertain”.",
    verdict:
      "{pct}% and above is a confident parse, below that an operator should take a look. The threshold was chosen on dev: on real-world lines 13% of records go to review and they contain 6 of the 8 errors.",
    envelope:
      "The output fields in the familiar order: street and numbers, microdistrict and district, city and region. This is only a view; the values are the same as in the JSON below.",
    agreement:
      "Every field is searched for independently by two parsers: the rules (steps and YAML dictionaries) and the neural network. “Agree” means both marked the same piece of the string. “Disputed” means the candidates differ and the arbiter picked the one better confirmed by the reference and by grammar. “Found by one” means only one parser has the field; such a field is taken from the model only with a high score.",
    modelF1:
      "Span F1 on the held-out unseen set: 3000 synthetic lines with streets and villages the model never saw in training. A span counts only if both its boundaries and label match exactly. This measures finding field boundaries, not the final jury metric.",
    refFacts:
      "The reference.sqlite database is built by our scripts from OpenStreetMap (Geofabrik dump) and the KATO classifier. A street is a unique combination of city, name and type; a house has a number and is linked to its district and microdistrict. The numbers come from /api/v1/health of the running service.",
    fields:
      "Every field shows its source. “From the string, chars a–b” means the value is cut from the original string at those positions, with no corrections. A green tag means the field was not in the string and was restored from the reference (matched house, street, district polygon, nearest microdistrict point, landmark, KATO). The reference never overwrites a value taken from the string.",
    confParts:
      "How the probability was built: the base is the probability with no features, then each feature adds its share in order, in probability units. The shares sum to the total. Weights are fitted on data (training/fit_confidence.py). “Capped at 0.99” means the total never exceeds 0.99.",
    timing:
      "Real server time of each step for this line (from the response trace), in milliseconds. The scale is square-root so short steps stay visible. The stage animation is slowed down on purpose.",
    unparsed:
      "Words and numbers that no step and no field took. The leftovers are taken into account in the confidence.",
    json: "Exactly what POST /api/v1/parse/batch returns: id and raw_address unchanged, 11 fields (null when a field is not found) and confidence.",
    coverage:
      "What the string is made of, by non-space characters. “Into fields” are characters cut into field values. “Service words” are markers and punctuation like “г.”, “кв”, commas: they guided the parse but are not part of any value. “Dropped” is the Kazakh duplicate after a slash and company names.",
    taggerSpans:
      "p is the model's span probability, calibrated on the held-out synthetic val set. The model only shows where a field is; the value is always cut from the original string.",
    arbiterScore:
      "The number next to a candidate is the arbiter score (logit): trust in the source + probability × weight + reference checks (the city exists, the street is in that city, the house is on the street) and grammar checks (floor ≤ 40, entrance ≤ 20). Weights are fitted by logistic regression on dev. The higher score wins.",
  },
};

export const DEMO_TEXTS: Record<Language, DemoTexts> = { ru, kk, en };

export function fmt(s: string, params: Record<string, string | number>): string {
  return s.replace(/\{(\w+)\}/g, (_, k: string) => String(params[k] ?? `{${k}}`));
}

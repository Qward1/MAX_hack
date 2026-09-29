# Согласование классов v3.0 и продукта

Источники: таксономия и правила разметки набора v3.0 (хранятся вместе с набором, вне репозитория); в продукте — `src/domsignal/core/incidents.py`, `src/domsignal/ai/resources/taxonomy.v2.yaml` и `regions/_federal/responsibility.yaml` (по коду на 26.09.2026). Машиночитаемая версия этой таблицы — [`../configs/class_mapping.yaml`](../configs/class_mapping.yaml).

Датасет содержит 33 класса проблем и not_a_problem. ambiguous есть в таксономии, но принятых примеров нет: это порог отказа от решения, а не обучаемый 35-й класс. Продукт использует пять категорий и 31 подтип. Код dataset_code нужен для сопоставимой оценки на v3.0; product_category — потенциальная категория UI/заявки. Эти поля не всегда совпадают: power_outage имеет dataset_code=other, а близкие продуктовые подтипы принадлежат lighting; yard_defect покрывает подтипы как other, так и lighting.

## Правило отображения

ML обучается предсказывать исходный класс L3 и отдельно гейт «проблема». Таблица переводит результат в продуктовую категорию/подтип только там, где смысл достаточен. product_subtype=null означает «не определять автоматически»; candidate_subtypes перечисляют варианты для уточнения по тексту, территории или ручной проверки. Нельзя подменять неопределённость other.unspecified ради видимости покрытия.

Адресат ниже — только предварительная подсказка. Реальный Responsibility Router продукта учитывает дом, период управления, регион, территорию и экстренность. Сервис не заявляет о внешней регистрации. Значения подсказок: uk_first_line/uk_review — УК или проверка оператором; uk_or_resource_supplier, uk_or_regional_operator, uk_or_municipality — нужны дополнительные условия; emergency_if_* — экстренность определяется отдельно по текущему состоянию; external_review — вне обычной заявки УК, маршрут проверяет человек; manual_review — без автоматического адресата.

## Полная таблица

| Класс датасета | Код v3 | Категория продукта | Подтип продукта | Адресат-подсказка | Соответствие |
|---|---|---|---|---|---|
| elevator_out | elevator | elevator | elevator.stopped | uk_first_line | exact |
| elevator_trapped | elevator | elevator | — (варианты: elevator.stopped, elevator.doors) | emergency_if_current | conditional |
| elevator_vandal | elevator | elevator | — | uk_review | unsupported_subtype |
| no_hot_water | water | water | water.hot_outage | uk_or_resource_supplier | exact |
| no_cold_water | water | water | water.supply_outage | uk_or_resource_supplier | exact |
| towel_rail_cold | water | water | — | uk_review | unsupported_subtype |
| water_leak | water | water | water.leak | emergency_if_active_else_uk | exact |
| water_pressure | water | water | water.pressure | uk_first_line | exact |
| water_quality | water | water | water.quality | uk_first_line | exact |
| roof_leak | water | water | roof.leak | emergency_if_active_else_uk | exact |
| sewer_blockage | water | water | — | uk_review | unsupported_subtype |
| heating_none | other | other | — (варианты: heating.cold_radiators) | uk_or_resource_supplier | conditional |
| chute_blockage | waste | waste | waste.chute | uk_first_line | exact |
| waste_not_collected | waste | waste | — (варианты: waste.container_site, waste.removal_regional) | uk_or_regional_operator | conditional |
| lighting_entrance | lighting | lighting | lighting.stairwell | uk_first_line | exact |
| power_outage | other | lighting | — (варианты: power.grid_outage, electrical.panel) | uk_or_resource_supplier | conditional |
| electrical_hazard | other | — | — (варианты: electrical.panel) | emergency_if_current | conditional |
| cleaning_entrance | other | other | — (варианты: cleaning.stairwell) | uk_review | conditional |
| snow_removal | other | other | — (варианты: snow.yard, snow.street) | uk_or_municipality | conditional |
| intercom | other | other | intercom.broken | uk_review | exact |
| door_defect | other | other | entrance_door.broken | uk_first_line | exact |
| yard_defect | other | — | — (варианты: lighting.yard, playground.damaged, landscaping.public, road.damage, structure.damage) | uk_or_municipality | conditional |
| pests | other | other | — | uk_review | unsupported_subtype |
| gas_smell | other | other | gas.smell | emergency_if_current | exact |
| fire_smoke | other | other | — | emergency_if_current | unsupported_subtype |
| fire_alarm | other | other | — | emergency_if_current_else_uk | unsupported_subtype |
| noise_neighbors | other | — | — | external_review | outside_uk_default |
| smoke_neighbors | other | — | — | external_review | outside_uk_default |
| neighbor_conduct | other | — | — | external_review | outside_uk_default |
| pets_violation | other | — | — | external_review | outside_uk_default |
| parking_violation | other | — | — | external_review | outside_uk_default |
| security_incident | other | — | — | external_review | outside_uk_default |
| other_problem | other | other | other.unspecified | manual_review | catch_all |
| ambiguous | — | — | — | manual_review | abstain_no_training_examples |
| not_a_problem | — | — | — | none | negative |

## Где классы не сходятся

- Точное соответствие есть для простых инженерных случаев: вода, течь крыши, свет в подъезде, мусоропровод, домофон, дверь, отсутствие лифта, запах газа. Даже здесь продуктовая маршрутизация зависит от территории и факта опасности.
- Один класс данных может охватывать несколько продуктовых подтипов: elevator_trapped (лифт остановился или не открываются двери), waste_not_collected (контейнеры или вывоз), power_outage (внешняя сеть или щиток), snow_removal (двор или улица), yard_defect (площадка, дорога, конструкция, фонарь и др.). heating_none также охватывает перетоп, а продуктовый heating.cold_radiators — только холодные батареи. Автоматический выбор подтипа по одной метке был бы ложным.
- В продукте нет точного подтипа для elevator_vandal, towel_rail_cold, sewer_blockage, pests, fire_smoke, fire_alarm. Опасность дыма/пожара определяется отдельным safety-полем, даже если подтип неизвестен.
- noise_neighbors, smoke_neighbors, neighbor_conduct, pets_violation, parking_violation и security_incident размечены как проблемы в L3, но имеют actionable=false по правилам датасета. Их сохраняем в задаче распознавания, а автоматически создавать заявку УК по ним не предлагаем. У security_incident возможен отдельный экстренный сценарий, который класс сам по себе не доказывает.
- Продукт имеет отдельные подтипы gas.supply_outage, elevator.button, street_lighting.failure, lighting.yard, external_network.outage и др., для которых нет самостоятельного класса L3. Из примеров broad-классов их нельзя честно оценить по отдельности. Возможный дальнейший шаг — разметить новые признаки или уточнить таксономию после ручной проверки.
- Данные L3 описывают один основной класс сообщения. Продуктовое окно может содержать несколько одновременных сигналов, разные роли и открытые элементы. Это разные единицы оценки; обучать или оценивать многосигнальный выход на одном классе L3 нельзя.

## Предлагаемое решение перед экспериментами

Сохранить 33 исходных класса как целевой fine label, отдельно измерять бинарную границу и предсказывать utterance/emergency. В консольном блоке показывать исходный класс, dataset_code, product_category/subtype только при надёжном соответствии, а recipient_hint — как предварительную подсказку. При null/conditional не угадывать исполнителя; показывать «нужна проверка». Для сравнения с продуктовой таксономией позже потребуется отдельная разметка территории и выбранного подтипа, особенно для многозначных строк таблицы.

Принятое решение (26.09.2026): оставить продуктовый вариант как предварительный результат. Консольный блок возвращает продуктовую категорию и подтип там, где есть основание, но требует проверки и подтверждения человеком. Для неоднозначных классов подтип остаётся неопределённым или перечисляет варианты. Все 33 класса L3 сохраняются для обучения и оценки без переразметки.

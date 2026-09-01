# Deye Solarman Diagnostics

## Przeznaczenie

Dodatek odczytuje lokalny logger Solarman TCP i publikuje przez MQTT Discovery tylko encje wybrane przez uzytkownika. Jest to diagnostyczny, wolniejszy kanal odczytu. Do ciaglego sterowania i szybkiej telemetrii nalezy preferowac bezposrednie RS485.

Katalog skanowania zawiera bezpieczne rejestry tylko do odczytu:

- 68 udokumentowanych wartosci biezacych dla rodziny Deye SUN-*-SG04LP3 / SG05LP3: stan falownika, PV1-PV4, bateria, siec, CT, obciazenie, wyjscie, UPS, generator, temperatury i energia.
- 14 pol diagnostycznych dla kazdego skonfigurowanego pakietu BMS: numer seryjny, napiecie, prad, temperatura, SOC, SOH, pojemnosc, napiecia cel, cykle i dane BMS.

Nie sa skanowane rejestry konfiguracji ani sterowania, wiec skan nie powinien modyfikowac ustawien falownika. "Powodzenie" skanu oznacza, ze logger zwrocil wartosc. Nie potwierdza ono jeszcze znaczenia kazdego pola BMS - wartosci oznaczone w raporcie jako `candidate` trzeba porownac z wyswietlaczem falownika lub BMS.

## Konfiguracja

Przykladowa konfiguracja w panelu dodatku:

```yaml
logger:
  host: 192.168.177.144
  port: 8899
  serial_number: 3556142832
  modbus_id: 1
  timeout: 3
  reconnect_delay: 10

mqtt:
  use_supervisor: true
  host: core-mosquitto
  port: 1883
  username: ""
  password: ""
  tls: false
  client_id: deye-solarman-diagnostics
  base_topic: deye_solarman
  discovery_prefix: homeassistant
  retain: true

inverter:
  serial_number: "2507092018"
  name: Deye Solarman Diagnostics
  manufacturer: Deye
  model: SG05LP3

profiles:
  default_profile:
    - deye_battery_packs
  overrides_file: /config/user_sensors.yaml
  state_file: /config/runtime_state.json
  scan_report_file: /share/deye_solarman_scan_report.json

polling:
  default_interval: 60
  slow_interval: 600
  read_message_spacing: 0.05
  batch_gap: 1
  max_registers_per_request: 20
  publish_unchanged_every: 900
  startup_probe_register: 10040
  startup_probe_count: 1
  allow_reconnect: true

advanced:
  emit_raw_topics: true
  emit_scan_report: true

scan:
  mode: disabled
  report_file: /share/deye_solarman_candidate_scan.json
  detected_sensors_file: /config/detected_sensors.yaml
  bms_pack_count: 4

catalog:
  refresh_on_start: true
  url: https://raw.githubusercontent.com/Wilk33/deye-solarman-ha-addon/main/deye-solarman-diagnostics/catalog-overrides.yaml
  cache_file: /config/deye_solarman_catalog.yaml
  timeout: 5
```

Parametry loggera musza wskazywac logger Solarman, nie adres IP samego falownika. `serial_number` w sekcji `logger` to numer loggera, a `inverter.serial_number` to numer seryjny falownika uzywany w nazwach MQTT.

### Katalog rejestrow z GitHub

Przy starcie dodatek pobiera plik YAML `catalog-overrides.yaml` z `catalog.url`. Od wersji `1.1.0` jest to pelna mapa `version: 2`: zawiera 68 definicji telemetrycznych oraz szablon 14 pozycji BMS, ktory jest rozwijany zgodnie z `bms_pack_count`. Pobierane sa wylacznie dane YAML - dodatek nie wykonuje zdalnego kodu. Po udanej walidacji kopia jest atomowo zapisywana w `catalog.cache_file`. Przycisk `Usun sensory` wymusza takie samo pobranie niezaleznie od opcji `refresh_on_start`.

Gdy GitHub lub Internet jest niedostepny, dodatek wykorzystuje ostatnia poprawna kopie z cache. Gdy cache takze nie istnieje albo jest bledny, uzywany jest katalog wbudowany w obraz dodatku. Nie zmienia to pliku `/config/detected_sensors.yaml` ani istniejacych wyborow MQTT.

Format katalogu jest wersjonowany. Kompletna mapa `version: 2` ma liste `sensors` i obiekt `bms_pack`. Jest autorytatywna, wiec brak wpisu w YAML usuwa go z listy kandydatow, gdy zdalny katalog albo jego cache jest dostepny. Wpisy `sensors` definiuja telemetrie falownika. `bms_pack.base_register` i `register_stride` okreslaja adres kolejnego pakietu, a kazdy wpis `bms_pack.sensors` zawiera `register_offsets` oraz symbole `{pack}` w `key`, `name` i opcjonalnym `topic_suffix`. Katalog jest walidowany przed uzyciem, a gdy siec i cache zawioda, dodatek uzywa wbudowanego fallbacku.

```yaml
version: 2
sensors:
  - key: battery_voltage
    name: Battery Voltage
    registers: [587]
    type: uint16
    multiplier: 0.01
    unit: V
bms_pack:
  base_register: 10032
  register_stride: 38
  sensors:
    - key: "battery_{pack}_voltage"
      name: "Battery {pack} Voltage"
      register_offsets: [8]
      type: uint16
      multiplier: 0.1
      unit: V
```

### MQTT i Supervisor

Domyslnie `use_supervisor: true` pobiera host, port, TLS oraz dane logowania MQTT z uslugi `mqtt` Home Assistant Supervisor. Jest to zalecany tryb dla HAOS i nie wymaga wpisywania hasla Mosquitto w konfiguracji tego dodatku. Wymaga wlaczonego i poprawnie skonfigurowanego dodatku Mosquitto. Wersja `0.3.6` obsluguje odpowiedz Supervisora opakowana w obiekt `data`.

Ustaw `use_supervisor: false` tylko wtedy, gdy broker MQTT znajduje sie poza Home Assistant lub swiadomie chcesz uzyc innych danych. W takim przypadku uzupelnij `host`, `port`, `username`, `password` oraz opcjonalnie `tls`. Hasla nie sa wyswietlane w logach.

## Panel konfiguracji Ingress

Po aktualizacji do wersji `0.3.4` Home Assistant pokazuje w panelu bocznym pozycje `Deye Solarman`. Jest to lokalny panel Ingress dodatku, dostepny bez mapowania portu na siec domowa.

Panel umozliwia:

- uruchomienie recznego skanu przyciskiem `Skanuj teraz`;
- przywrocenie katalogowych ustawien domyslnych znalezionych czujnikow przyciskiem `Reset konfiguracji`;
- usuniecie lokalnej listy wykryc i jej konfiguracji oraz odswiezenie cache katalogu z GitHub przyciskiem `Usun sensory`;
- przegladanie wartosci zdekodowanej, RAW i hex dla kazdego rejestru;
- filtrowanie wedlug statusu i wyszukiwanie po nazwie, kluczu, kategorii lub rejestrze;
- zaznaczenie encji do MQTT przeznikiem `MQTT`;
- zmiane nazwy, typu, mnoznika, offsetu, jednostki, slow order, interwalow, progu zmiany, retain i metadanych Home Assistant;
- atomowy zapis konfiguracji przyciskiem `Zapisz wybor MQTT`, z automatycznym przeladowaniem tylko petli MQTT i odczytow.

## Diagnostyka panelu

Wersja `0.3.4` zapisuje kazde zadanie panelu w logu dodatku, na przyklad `Ingress request method=GET path=/api/sensors` albo `Ingress request method=POST path=/api/scan`. Dodatkowo konsola przegladarki zapisuje wpisy zaczynajace sie od `[Deye Solarman]` z adresem Ingress, metoda zadania i kodem odpowiedzi.

Przy starcie MQTT log powinien zawierac `Using MQTT service credentials supplied by Home Assistant Supervisor`, `Sensor configuration loaded`, `MQTT connection confirmed`, `Publishing MQTT Discovery` i po jednym wpisie `MQTT discovery published` dla kazdej wybranej encji. Brak tych wpisow jednoznacznie wskazuje etap, na ktorym konfiguracja nie przechodzi do Home Assistant.

Wersja `0.4.0` rozpoznaje `Connection closed on read` i `Connection already closed` jako utrate sesji Solarman. Zamiast kontynuowac nieskuteczne odczyty, zamyka klienta i po `logger.reconnect_delay` nawiazuje nowe polaczenie. Temperatura w Discovery jest publikowana z jednostka `°C`, wymagana dla `device_class: temperature`. Wersja `0.6.0` formatuje log jako krotkie wiersze ze znacznikami `[OK]`, `[WARN]`, `[ERROR]` i `[INFO]`; odpowiednio zielonym, ciemno-zoltym, czerwonym i domyslnym kolorem terminala. Aby calkowicie wylaczyc ANSI, ustaw zmienna srodowiskowa `DEYE_LOG_COLOR=false`.

Jesli panel nie reaguje, otworz narzedzia programistyczne przegladarki, wybierz `Console`, odswiez panel i skopiuj wszystkie wpisy `[Deye Solarman]` oraz ewentualne czerwone bledy. Rownoczesnie skopiuj log dodatku z chwili otwarcia panelu i klikniecia `Skanuj teraz`.

Adresy rejestrow, klucze encji i ich lista nie sa edytowalne w panelu. Chroni to katalog przed przypadkowa zmiana definicji Modbus. `Reset konfiguracji` zachowuje ostatni wynik odczytu, przywraca domyslne definicje katalogowe i wylacza wszystkie przelaczniki `MQTT`. `Usun sensory` usuwa lokalny plik wykryc `/config/detected_sensors.yaml`; po nim uruchom nowy skan. Reset i usuniecie dopisuja wczesniej wybrane encje do lokalnej kolejki usuniecia Discovery. Dodatek automatycznie zamyka i odtwarza tylko polaczenia Solarman TCP oraz MQTT, a nastepnie publikuje retained, pusty komunikat `.../config` dla tych encji, aby Home Assistant je usunal. Restart calego dodatku nie jest wymagany.

## Skanowanie i wybor encji

Skan uruchamia sie wylacznie recznie. Nie jest wykonywany w normalnym cyklu odczytu.

1. Ustaw `scan.mode: disabled` i uruchom dodatek.
2. Otworz panel `Deye Solarman` z paska bocznego Home Assistant.
3. Wybierz `Skanuj teraz`. Dodatek wykona probe polaczenia i odczyta katalog rejestrow sekwencyjnie. Nie tworzy przy tym encji MQTT.
4. W panelu wlacz `MQTT` tylko przy pozycjach o statusie `supported`, ktore chcesz publikowac. Dostosuj parametry w `Konfiguruj dekodowanie i odpytywanie`, jesli sa potrzebne.
5. Wybierz `Zapisz wybor MQTT`. Dodatek sam zamknie i odtworzy tylko polaczenia Solarman i MQTT, wczyta nowy wybor oraz opublikuje aktualne MQTT Discovery. Od tej chwili tylko zaznaczone encje sa odpytywane oraz publikowane do MQTT. Restart calego dodatku nie jest wymagany.

Opcja `scan_and_monitor` wykonuje skan podczas startu, aktualizuje oba pliki, a nastepnie przechodzi od razu do normalnego MQTT. Uzywaj jej tylko wtedy, gdy istniejace zaznaczenia sa juz poprawne. `scan_only` wykonuje skan podczas startu, nie laczy sie z MQTT i pozostawia uruchomiony panel Ingress do wyboru encji.

## Wlasne sensory i formuly

Pulpit `Wlasne sensory` przechowuje definicje niezaleznie od wyniku skanu w `/config/custom_sensors.yaml`. Przycisk `+ Dodaj sensor` tworzy standardowy, reczny sensor Modbus. Bez zaznaczenia `Wlasna formula` dziala on jak pozostale definicje: uzywa rejestrow, typu, mnoznika, offsetu oraz kolejnosci slow z formularza.

Po zaznaczeniu `Wlasna formula` formularz pokazuje edytor skryptu. Typ widoczny jako `-` jest zapisywany wewnetrznie jako `auto`: wynik `return` jest publikowany bez drugiego dekodowania rejestrow. Pole `Powieksz` otwiera duzy edytor, a `Test` laczy sie jednorazowo z loggerem, pokazuje RAW/HEX oraz wynik bez publikowania MQTT.

Przyklad mocy pozornej pakietu baterii:

```python
voltage=sensor(R587,uint16,0.01)
current=sensor(R591,int16,0.01)

return abs(voltage*current)
```

`sensor(adres,typ,mnoznik[,offset[,kolejnosc_slow]])` odczytuje rejestr bezposrednio przez logger, dekoduje go i zwraca wartosc po przeliczeniu. `RAW(adres)` zwraca surowa, liczbowa wartosc pojedynczego rejestru `uint16`. Skrypt moze uzywac lokalnych zmiennych, `def`, `return`, `if` / `elif` / `else`, `match` / `case`, funkcji `abs`, `min`, `max`, `round`, `sqrt`, `clamp` oraz ograniczonego `for ... in range(...)`.

Nie sa dozwolone importy, `eval`, `exec`, dostep do plikow lub sieci, atrybuty obiektow, `while`, rekurencja ani dowolne funkcje Pythona. Interpreter ogranicza formule do 300 wezlow skladni, 64 iteracji petli i 128 bezposrednich odczytow rejestrow w jednym wykonaniu.

Po kolejnym skanie zachowywane sa pola `monitor` oraz wlasne ustawienia `definition` z `detected_sensors.yaml`.

Przyklad zaznaczonej i dostrojonej encji:

```yaml
available_sensors:
  - key: grid_power_total
    monitor: true
    definition:
      key: grid_power_total
      name: Grid power total
      registers:
        - 619
      type: int16
      multiplier: 1.0
      offset: 0.0
      unit: W
      word_order: high_low
      schedule: default
      read_every: 60
      report_every: 300
      change_by: 1.0
      enabled: true
      retain: true
      device_class: power
      state_class: measurement
      icon: mdi:transmission-tower
      category: grid
      topic_suffix: grid_power_total
      attributes: {}
```

Mozna zmienic miedzy innymi `type`, `multiplier`, `offset`, `unit`, `word_order`, `schedule`, `read_every`, `report_every`, `change_by`, `retain` i pola MQTT. Typ `ascii` dekoduje dwa znaki ASCII z kazdego rejestru i zastepuje znaki niedrukowalne kropkami. Jest uzyty domyslnie dla numerow seryjnych BMS. Dla wartosci BMS nie zmieniaj przelicznika ani typu przed porownaniem z realnym odczytem urzadzenia.

Domyslny profil zawiera definicje BMS, ale wszystkie sa wylaczone. W normalnym trybie MQTT publikuje wiec wylacznie pozycje z `monitor: true` w `/config/detected_sensors.yaml` albo wpisy jawnie wlaczone w `/config/user_sensors.yaml`.

## Pliki i MQTT

- `/share/deye_solarman_candidate_scan.json` - wynik recznego skanu kandydatow.
- `/config/detected_sensors.yaml` - trwala lista dostepnych encji i wybory uzytkownika.
- `/config/user_sensors.yaml` - reczne nadpisania, maja pierwszenstwo przed wyborem z `detected_sensors.yaml`.
- `/share/deye_solarman_scan_report.json` - raport biezacych odczytow podczas normalnej pracy, jesli wlaczono `advanced.emit_scan_report`.
- Discovery MQTT: `homeassistant`.
- Stany MQTT: `deye_solarman/<serial_falownika>/...`.

## Zrodla mapowania

- [Developer089 - mapa Deye SUN-3PH Hybrid](https://github.com/Developer089/deye-modbus-ha/blob/main/custom_components/deye_modbus/maps/sun_3ph_hybrid.yaml) - zrodlo katalogu 68 telemetrycznych rejestrow SG04LP3 / SG05LP3.
- [Lewa-Reka - Deye SUN-12K SG05LP3 BMS](https://gist.github.com/Lewa-Reka/9796390db54fa5b317f27bc435a2a320) - zrodlo kandydatow per-pakiet BMS, wymagajacych walidacji na konkretnym urzadzeniu.
- [Home Assistant - Add-on configuration](https://developers.home-assistant.io/docs/apps/configuration/) - ograniczenia statycznego schematu opcji dodatku Supervisor.

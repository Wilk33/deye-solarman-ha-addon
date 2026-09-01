# Deye Solarman HA Add-on

Stabilne wydanie `1.1.0` dodatku Home Assistant OS do lokalnej, diagnostycznej komunikacji z falownikiem Deye przez logger Solarman TCP. Dodatek odczytuje rejestry Modbus tylko do odczytu, pozwala zweryfikowac ich dostepnosc w panelu Ingress i publikuje w Home Assistant wybrane encje przez MQTT Discovery.

Projekt jest przeznaczony dla falownikow z rodziny Deye SUN-*-SG04LP3 / SG05LP3 oraz loggerow Solarman dostepnych lokalnie przez TCP. Moze zbierac dane biezace falownika i dane per-pakiet BMS, ale nie zastepuje bezposredniej integracji RS485, np. `Sunsynk or Deye Inverter add-on (multi)`. RS485 pozostaje lepszym kanalem dla szybkiej telemetrii i sterowania.

## Najwazniejsze funkcje

- Lokalny odczyt loggera Solarman TCP bez chmury.
- Weryfikacja polaczenia przez probe rejestru startowego `R10040`.
- Reczny, tylko-odczytowy skan katalogu rejestrow falownika oraz pakietow BMS.
- Panel Ingress z obsluga motywow jasnego i ciemnego Home Assistant.
- Wybor encji MQTT, edycja dekodowania i harmonogramu bez edycji YAML w terminalu.
- MQTT Discovery z automatycznym tworzeniem urzadzenia oraz encji w Home Assistant.
- Automatyczne usuwanie wycofanych encji MQTT Discovery.
- Odtwarzanie sesji TCP po rozlaczeniu loggera.
- Pelna, aktualizowalna mapa rejestrow YAML pobierana z GitHub z lokalnym cache i bez wykonywania zdalnego kodu.
- Reczne sensory Modbus oraz bezpieczne, lokalne formuly o ograniczonym podzbiorze Pythona.
- Diagnostyka RAW, HEX i ASCII oraz kolorowe znaczniki logow.

## Architektura i przeplyw danych

```text
Falownik Deye
    |
    | Modbus / komunikacja producenta
    v
Logger Solarman w LAN, TCP:8899
    |
    | pysolarmanv5, Modbus holding registers, tylko odczyt
    v
Deye Solarman Diagnostics (HAOS add-on)
    |
    +-> panel Ingress: skan, wybor, konfiguracja i testy
    +-> pliki /config: wybor sensorow, sensory wlasne, cache i stan
    +-> MQTT Discovery + stany + atrybuty
    v
Home Assistant MQTT integration
    |
    v
Urzadzenie i encje Home Assistant
```

Normalny cykl dodatku dziala nastepujaco:

1. Wczytuje opcje dodatku i, gdy `mqtt.use_supervisor: true`, pobiera dane brokera z uslugi MQTT Home Assistant Supervisor.
2. Odswieza katalog rejestrow z GitHub albo korzysta z ostatniej poprawnej kopii cache lub katalogu wbudowanego.
3. Scala profil domyslny, wybor po ostatnim skanie, lokalne nadpisania oraz sensory wlasne.
4. Nawiazuje polaczenie TCP z loggerem i wykonuje probe `R10040`.
5. Nawiazuje polaczenie MQTT, usuwa odznaczone encje Discovery i publikuje konfiguracje Discovery tylko dla aktywnych sensorow.
6. Grupuje bezposrednie odczyty w niewielkie zakresy rejestrow, odczytuje wartosci, dekoduje je i publikuje, gdy wartosc sie zmienila lub minal czas wymuszonej publikacji.
7. Wykonuje sensory formul oddzielnie, z lokalnym cache odczytow w jednej formule.
8. Zapisuje stan pracy i raporty. W przypadku zamknietej sesji TCP zamyka klienta, odczekuje `logger.reconnect_delay` i nawiazuje nowe polaczenie.

## Zakres i ograniczenia

Dodatek korzysta wylacznie z `read_holding_registers`. Nie zapisuje rejestrow, nie zmienia konfiguracji falownika, nie steruje bateria ani siecia i nie wymaga konta Solarman ani dostepu do chmury.

Skan potwierdza, ze logger zwrocil odpowiedz, lecz nie potwierdza semantyki kazdego rejestru. Dotyczy to szczegolnie danych BMS per-pack oznaczonych jako `candidate`. Przed wykorzystaniem ich w automatyzacji porownaj wartosci z wyswietlaczem falownika lub BMS.

## Wymagania

- Home Assistant OS na jednej z obslugiwanych architektur: `aarch64`, `amd64`, `armv7`, `armhf` lub `i386`.
- Dostep sieciowy HAOS do loggera Solarman. Domyslny port loggera to `8899`.
- Prawidlowy numer seryjny loggera Solarman i Modbus ID falownika.
- Zalecany dodatek Mosquitto Broker albo zewnetrzny broker MQTT.
- Numer seryjny falownika, ktory bedzie czescia identyfikatorow i tematow MQTT.

Adres `logger.host` wskazuje logger Solarman, a nie adres IP falownika. `logger.serial_number` to numer loggera, natomiast `inverter.serial_number` jest numerem falownika uzywanym w MQTT Discovery.

## Instalacja w Home Assistant OS

1. W Home Assistant otworz `Ustawienia -> Dodatki -> Sklep z dodatkami`.
2. Otworz menu z trzema kropkami, wybierz `Repozytoria` i dodaj adres: `https://github.com/Wilk33/deye-solarman-ha-addon`.
3. Wyszukaj `Deye Solarman Diagnostics`, zainstaluj dodatek i otworz jego zakladke `Konfiguracja`.
4. Uzupelnij sekcje `logger` oraz `inverter`.
5. Pozostaw `mqtt.use_supervisor: true`, gdy korzystasz z Mosquitto w Home Assistant OS.
6. Uruchom dodatek. Po poprawnym starcie w menu bocznym pojawi sie panel `Deye Solarman`.

Dodatek nie potrzebuje portu Ingress wystawionego na LAN. Panel otwiera Home Assistant przez bezpieczny mechanizm Ingress.

## Konfiguracja dodatku

Minimalna konfiguracja wymaga poprawnych danych loggera i falownika. Pozostale wartosci domyslne sa konserwatywne:

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
  default_profile: deye_battery_packs
  overrides_file: /config/user_sensors.yaml
  custom_sensors_file: /config/custom_sensors.yaml
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

### MQTT przez Supervisor

`mqtt.use_supervisor: true` jest zalecanym ustawieniem HAOS. Dodatek pobiera host, port, TLS, uzytkownika i haslo z uslugi `mqtt` Supervisora, dlatego pola `host`, `port`, `username`, `password` i `tls` w formularzu stanowia tylko zapasowa konfiguracje reczna.

Ustaw `mqtt.use_supervisor: false` wylacznie dla brokera zewnetrznego. Wtedy uzupelnij pola recznie. Haslo nie jest wypisywane w logach.

### Harmonogram i publikacja

- `read_every` okresla odstep odczytu pojedynczego sensora.
- `schedule: slow` korzysta z globalnego `slow_interval`.
- `change_by` okresla minimalna zmiane liczbowa wymagana do publikacji kolejnego stanu.
- `report_every` wymusza ponowna publikacje niezmienionej wartosci.
- `publish_unchanged_every` jest globalnym gornym limitem tego okresu.
- `max_registers_per_request` ogranicza rozmiar jednego zapytania do loggera.
- `batch_gap` pozwala laczyc bliskie adresy w jedno zapytanie, bez rozszerzania odczytu ponad limit.

## Pierwsze uruchomienie i skan

Po starcie log powinien zawierac komunikaty podobne do:

```text
[ OK  ] solarman     | Startup probe ok register=10040 count=1 values=[...]
[ OK  ] mqtt         | MQTT connection confirmed
```

Nastepnie otworz z menu bocznego panel `Deye Solarman` i uzyj przycisku `Skanuj teraz`. Skan nie tworzy od razu encji w Home Assistant. Najpierw zapisuje dostepne kandydaty do lokalnego pliku, aby uzytkownik sam zdecydowal, ktore dane publikuje.

W typowym przebiegu:

1. Kliknij `Skanuj teraz`.
2. Poczekaj na status `COMPLETED` i przejrzyj wartosc zdekodowana, `HEX`, `ASCII` oraz status odczytu.
3. Zaznacz `MQTT` tylko przy encjach, ktore maja trafic do Home Assistant.
4. W razie potrzeby rozwin `Konfiguruj dekodowanie i odpytywanie` i dostosuj nazwe, typ, mnoznik, offset, jednostke, kolejnosc slow, czestotliwosc i metadane Home Assistant.
5. Kliknij `Zapisz wybor MQTT`.

Zapis przeladowuje tylko petle odczytow oraz polaczenia Solarman i MQTT. Nie restartuje kontenera dodatku. Po przeladowaniu publikuje MQTT Discovery dla aktualnego wyboru.

### Przyciski panelu wykrytych sensorow

- `Skanuj teraz` - sprawdza, ktore pozycje z lokalnego katalogu odpowiadaja na odczyt. Nie zmienia konfiguracji falownika.
- `Reset konfiguracji` - przywraca katalogowe ustawienia znalezionych pozycji i odznacza ich wybor MQTT. Zachowuje ostatni wynik skanu.
- `Usun sensory` - usuwa lokalna liste znalezionych sensorow i ich konfiguracje, odswieza lokalny cache katalogu z GitHub, a nastepnie oczekuje na nowy skan.
- `Zapisz wybor MQTT` - zapisuje zaznaczenia i konfiguracje oraz wykonuje przeladowanie runtime bez restartu dodatku.

Gdy sensor zostanie odznaczony lub usuniety, dodatek publikuje retained pusty payload w jego temacie Discovery. Home Assistant usuwa wtedy przestarzala encje MQTT.

## Katalog rejestrow

Kanoniczna mapa jest w [catalog-overrides.yaml](deye-solarman-diagnostics/catalog-overrides.yaml). Mimo historycznej nazwy nie jest juz pusta nakladka: format `version: 2` zawiera pelne 68 definicji telemetrycznych oraz jeden szablon 14 pozycji BMS. Szablon wylicza adresy dla `bms_pack_count` od 1 do 10. Przy `bms_pack_count: 4` panel ma 124 kandydatow, a przy `10` - 208.

Katalog z `catalog.url` jest pobierany podczas startu. Dodatek akceptuje tylko dane YAML, waliduje je i zapisuje poprawna kopie do `catalog.cache_file`. Format `version: 2` jest autorytatywny: gdy GitHub albo cache jest dostepny, brak wpisu w YAML oznacza brak tego kandydata w skanie. Jezeli GitHub jest niedostepny, uzywa ostatniej poprawnej kopii cache. Jezeli cache nie istnieje lub jest niepoprawny, dziala na wbudowanym katalogu awaryjnym [catalog.py](deye-solarman-diagnostics/rootfs/usr/src/app/deye_solarman_diagnostics/catalog.py). Katalog awaryjny jest objety testem zgodnosci z YAML.

Aktualizuj mape przez commit do `catalog-overrides.yaml` w tym repozytorium. Nie edytuj `/config/deye_solarman_catalog.yaml`, poniewaz jest to cache nadpisywany po poprawnym pobraniu. Aktualizacja katalogu nie usuwa samodzielnie lokalnego wyniku skanu ani wyborow MQTT. Przycisk `Usun sensory` wymusza odswiezenie katalogu przy czyszczeniu listy wykryc.

Szczegolowy przeglad typow rejestrow jest w [REGISTER_TYPE_AUDIT.md](deye-solarman-diagnostics/REGISTER_TYPE_AUDIT.md).

## MQTT Discovery i tematy

Dla kazdego aktywnego sensora dodatek publikuje konfiguracje Discovery:

```text
homeassistant/sensor/deye_solarman_<serial_falownika>_<klucz>/config
```

Stan i atrybuty sa publikowane pod:

```text
deye_solarman/<serial_falownika>/<topic_suffix>
deye_solarman/<serial_falownika>/<topic_suffix>/attributes
deye_solarman/<serial_falownika>/<topic_suffix>/raw
```

Temat `/raw` jest publikowany tylko przy `advanced.emit_raw_topics: true`. Atrybuty stanu zawieraja m.in. rejestry RAW, ASCII, wartosc zdekodowana, uzyty typ, mnoznik, offset, kolejnosc slow, interwal, opoznienie odczytu i licznik timeoutow. Formula dodaje rowniez uzyty skrypt i liste bezposrednich odczytow.

`unique_id` ma postac `deye_solarman_<serial_falownika>_<klucz>`, wiec wszystkie encje trafiaja do jednego urzadzenia Home Assistant zgodnego z danymi z sekcji `inverter`.

## Wlasne sensory

Pulpit `Wlasne sensory` jest niezalezny od skanu i przechowuje definicje w `/config/custom_sensors.yaml`. Pusty plik z `sensors: []` jest prawidlowym stanem poczatkowym.

### Zwykly sensor Modbus

Kliknij `+ Dodaj sensor` i pozostaw wylaczony checkbox `Wlasna formula`. Formularz tworzy definicje jak dla znalezionego sensora:

- klucz i nazwa MQTT;
- jeden rejestr dla `uint16` lub `int16`, dwa dla `uint32` lub `int32`;
- typ, mnoznik, offset, jednostka i kolejnosc slow;
- harmonogram, prog zmiany i retained MQTT;
- opcjonalne klasy oraz ikona Home Assistant.

### Sensor z formula

Zaznaczenie `Wlasna formula` zmienia typ na `-`, przechowywany wewnetrznie jako `auto`. Wynik instrukcji `return` jest wtedy publikowany bez dodatkowego dekodowania rejestrow. Edytor ma przewijany obszar, mozliwosc powiekszenia do modalu, test jednorazowy i indywidualne usuniecie definicji.

Przyklad wyliczenia mocy pozornej pakietu baterii:

```python
voltage=sensor(R587,uint16,0.01)
current=sensor(R591,int16,0.01)

return abs(voltage*current)
```

Funkcje dostepne w formule:

- `sensor(adres,typ,mnoznik[,offset[,kolejnosc_slow]])` - odczytuje rejestr bezposrednio przez logger, dekoduje go i zwraca wartosc po przeliczeniu.
- `RAW(adres)` - zwraca liczbowy, nieprzetworzony 16-bitowy rejestr.
- `abs`, `min`, `max`, `round`, `sqrt` i `clamp` - bezpieczna biala lista funkcji matematycznych.
- Lokalne zmienne, funkcje `def`, `return`, `if` / `elif` / `else`, `match` / `case` oraz `for ... in range(...)`.

Adres rejestru mozna zapisac jako `R587` albo liczbe `587`. `uint16`, `int16`, `uint32`, `int32`, `hex`, `ascii`, `high_low` i `low_high` sa dostepnymi symbolami formula.

Nie sa dostepne importy, `eval`, `exec`, dostep do plikow lub sieci, atrybuty obiektow, `while`, rekurencja ani dowolne funkcje Pythona. Interpreter ogranicza formule do 300 wezlow skladni, do 64 iteracji petli, do 8 poziomow wywolan lokalnych funkcji i do 128 bezposrednich odczytow rejestrow. Ten sam rejestr jest buforowany w ramach jednego wykonania formuly.

`Test` wykonuje polaczenie z loggerem i pokazuje wynik, RAW, HEX, dekodowanie oraz wejscia formuly, ale nie publikuje MQTT.

## Pliki trwale

- `/config/detected_sensors.yaml` - wynik skanu, konfiguracja znalezionych sensorow i wybor `MQTT`.
- `/config/custom_sensors.yaml` - reczne sensory Modbus oraz sensory z formulami.
- `/config/user_sensors.yaml` - reczne nadpisania o najwyzszym priorytecie dla kluczy z profili i skanu.
- `/config/runtime_state.json` - ostatni stan publikacji, wartosci RAW i liczniki timeoutow.
- `/config/deye_solarman_catalog.yaml` - ostatnia poprawna kopia katalogu z GitHub.
- `/config/deye_solarman_discovery_removals.yaml` - kolejka encji MQTT Discovery przeznaczonych do usuniecia.
- `/share/deye_solarman_candidate_scan.json` - raport ostatniego skanu kandydatow.
- `/share/deye_solarman_scan_report.json` - raport biezacych odczytow, gdy wlaczono `advanced.emit_scan_report`.

## Diagnostyka

Log dodatku uzywa znacznikow `[INFO]`, `[ OK ]`, `[WARN]` i `[ERROR]`. Przy terminalu obslugujacym ANSI sa one kolorowane. Aby wylaczyc kolory, ustaw zmienna srodowiskowa `DEYE_LOG_COLOR=false`.

Najczestsze komunikaty i ich znaczenie:

- `Startup probe ok` - logger odpowiedzial na probe, wiec podstawowy transport TCP dziala.
- `MQTT connection confirmed` - broker zaakceptowal polaczenie.
- `MQTT discovery published` - konfiguracja encji zostala wyslana do brokera.
- `MQTT broker rejected the connection reason=Not authorized` - dane MQTT nie maja uprawnien. Przy HAOS ustaw `use_supervisor: true` albo skonfiguruj prawidlowe konto brokera.
- `Connection closed on read` lub `Connection already closed` - logger zamknal sesje. Dodatek wykonuje ponowne polaczenie po `reconnect_delay`.
- `Read failed` - konkretny zakres nie odpowiedzial. Sprawdz host, numer loggera, Modbus ID, timeout oraz wartosc rejestru.
- `Formula read failed` - formula albo jej odczyt zostaly odrzucone. Uzyj przycisku `Test`, aby zobaczyc wynik bez MQTT.

Gdy panel nie reaguje, otworz narzedzia programistyczne przegladarki, zakladke `Console`, odswiez panel i skopiuj wpisy zaczynajace sie od `[Deye Solarman]` razem z logiem dodatku z chwili klikniecia.

## Rozwoj i weryfikacja

Kod dodatku jest w [deye-solarman-diagnostics/rootfs/usr/src/app/deye_solarman_diagnostics](deye-solarman-diagnostics/rootfs/usr/src/app/deye_solarman_diagnostics). Testy regresji sa w [tests/test_runtime.py](tests/test_runtime.py).

Przed wydaniem uruchom:

```powershell
python -m unittest -v tests/test_runtime.py
python -W error::SyntaxWarning -m compileall -q deye-solarman-diagnostics/rootfs/usr/src/app
git diff --check
```

## Dokumentacja i zrodla

- [Szczegolowa konfiguracja dodatku](deye-solarman-diagnostics/DOCS.md)
- [Audyt typow rejestrow](deye-solarman-diagnostics/REGISTER_TYPE_AUDIT.md)
- [Mapa Deye SUN-3PH Hybrid - Developer089](https://github.com/Developer089/deye-modbus-ha/blob/main/custom_components/deye_modbus/maps/sun_3ph_hybrid.yaml)
- [Kandydaci rejestrow BMS - Lewa-Reka](https://gist.github.com/Lewa-Reka/9796390db54fa5b317f27bc435a2a320)
- [Home Assistant Add-on configuration](https://developers.home-assistant.io/docs/apps/configuration/)

Mapy zewnetrzne sa zrodlami referencyjnymi dla katalogu. Nie stanowia potwierdzenia konkretnej wersji firmware ani lokalnego znaczenia odczytu BMS.

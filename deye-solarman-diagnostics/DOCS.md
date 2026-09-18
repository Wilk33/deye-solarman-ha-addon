# SolarMan Diagnostics 2.0.2 - instrukcja użytkownika

## Przeznaczenie

`SolarMan Diagnostics` jest jednym dodatkiem Home Assistant OS i jednym procesem, który obsługuje SolarMan TCP oraz bezpośredni Modbus RTU przez USB-RS485. Dodatek może pracować w trzech trybach:

- `solarman-only` - aktywny jest tylko logger SolarMan TCP;
- `rs485-only` - aktywny jest tylko bezpośredni Modbus RTU;
- `dual` - oba transporty pracują jednocześnie.

W trybie `dual` oba transporty mają niezależne workery, połączenia, blokady i ustawienia odpytywania. Każda encja ma dokładnie jeden wybrany transport. Błąd wybranego transportu nie powoduje fallbacku odczytu ani zapisu na drugi.

Dodatek publikuje wybrane sensory i encje sterowania przez jeden klient MQTT i jedno urządzenie Home Assistant.

## Wymagania

- Home Assistant OS na obsługiwanej architekturze;
- broker MQTT dostępny przez usługę Supervisora albo zewnętrznie;
- dla SolarMan TCP: lokalny adres loggera, port i numer seryjny loggera;
- dla RS485: adapter USB-RS485 przekazany do dodatku, prawidłowe parametry portu i Modbus ID falownika;
- numer seryjny falownika używany w identyfikatorach MQTT.

Metadane dodatku zawierają `uart: true`. Samo ustawienie nie potwierdza jednak, że wybrany adapter jest widoczny w kontenerze ani że jego linie A/B są podłączone prawidłowo.

## Instalacja

1. Otwórz `Ustawienia -> Dodatki -> Sklep z dodatkami` w Home Assistant.
2. Dodaj repozytorium `https://github.com/Wilk33/deye-solarman-ha-addon`.
3. Zainstaluj jeden dodatek `SolarMan Diagnostics`.
4. Włącz panel boczny i pozostaw Ingress aktywny.
5. Skonfiguruj co najmniej jeden transport.
6. Uruchom dodatek i sprawdź statusy transportów w panelu.

Nie trzeba instalować osobnej aplikacji dla RS485.

## Pełna konfiguracja

Poniższy przykład włącza oba transporty. Adresy, numery seryjne i port szeregowy trzeba dostosować do instalacji.

```yaml
solarman:
  enabled: true
  host: 192.168.1.100
  port: 8899
  serial_number: 3556142832
  modbus_id: 1
  timeout: 3
  reconnect_delay: 10
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

rs485:
  enabled: true
  device: /dev/ttyUSB0
  baudrate: 9600
  bytesize: 8
  parity: N
  stopbits: 1
  modbus_id: 1
  timeout: 1
  reconnect_delay: 10
  polling:
    default_interval: 30
    slow_interval: 300
    read_message_spacing: 0.05
    batch_gap: 1
    max_registers_per_request: 20
    publish_unchanged_every: 900
    startup_probe_register: 10040
    startup_probe_count: 1
    allow_reconnect: true

mqtt:
  use_supervisor: true
  host: core-mosquitto
  port: 1883
  username: ""
  password: ""
  tls: false
  client_id: solarman
  base_topic: solarman_diagnostics
  discovery_prefix: homeassistant
  retain: true

inverter_serial_number: "2507092018"
inverter_name: SolarMan Diagnostics
inverter_manufacturer: Deye
inverter_model: SG05LP3

overrides_file: /config/user_sensors.yaml
custom_sensors_file: /config/custom_sensors.yaml
state_file: /config/runtime_state.json
scan_report_file: /share/deye_solarman_scan_report.json

emit_raw_topics: true
emit_scan_report: true
detailed_logs: false

scan_mode: disabled
scan_candidate_report_file: /share/deye_solarman_candidate_scan.json
detected_sensors_file: /config/detected_sensors.yaml
bms_pack_count: 4

catalog:
  refresh_on_start: true
  url: https://raw.githubusercontent.com/Wilk33/deye-solarman-ha-addon/main/deye-solarman-diagnostics/deye_sg04_sg05_3ph_lv_catalog.yaml
  cache_file: /config/deye_solarman_catalog.yaml
  control_url: https://raw.githubusercontent.com/Wilk33/deye-solarman-ha-addon/main/catalogs/models/deye_sg04_sg05_3ph_lv/control.yaml
  control_cache_file: /config/deye_solarman_control_catalog.yaml
  timeout: 5
```

### SolarMan TCP

`solarman.host` wskazuje lokalny adres loggera, a nie interfejs sieciowy falownika. `solarman.serial_number` jest numerem loggera wymaganym przez protokół SolarMan. `inverter_serial_number` jest oddzielnym numerem używanym przez MQTT Discovery.

Worker SolarMan ma własne ustawienia `polling`, timeout i `reconnect_delay`. Utrata sesji TCP nie zatrzymuje działającego workera RS485.

### Modbus RTU (RS485)

Konfiguracja domyślna `/dev/ttyUSB0`, 9600 8N1 oraz Modbus ID 1 jest wartością startową. Zweryfikuj na urządzeniu:

- właściwą nazwę portu udostępnionego dodatkowi;
- prędkość, liczbę bitów danych, parzystość i bity stopu;
- Modbus ID falownika;
- polaryzację A/B, ekranowanie i terminację magistrali;
- odstępy między zapytaniami wymagane przez konkretny falownik.

Nie włączaj RS485 przed sprawdzeniem, że port należy do właściwego adaptera.

### Interwały

Każdy transport ma osobną sekcję `polling`:

- `default_interval` - zwykły interwał odczytu;
- `slow_interval` - interwał sensorów oznaczonych jako wolne;
- `read_message_spacing` - minimalny odstęp między grupami zapytań;
- `batch_gap` - dozwolona przerwa adresów podczas grupowania;
- `max_registers_per_request` - maksymalna długość jednego odczytu;
- `publish_unchanged_every` - maksymalny czas bez ponownej publikacji tego samego stanu;
- `startup_probe_register` i `startup_probe_count` - próbny odczyt po połączeniu;
- `allow_reconnect` - zgoda na odtworzenie utraconego połączenia.

Zmiana interwału jednego transportu nie zmienia interwału drugiego.

## Migracja z wersji 1.x

Wersja 2.0.2 zachowuje slug oraz katalog instalacyjny, więc Home Assistant aktualizuje istniejący dodatek.

Starsza konfiguracja używała sekcji:

```yaml
logger:
  host: 192.168.1.100
  # pozostałe pola loggera
polling:
  default_interval: 60
  # pozostałe pola odpytywania
```

Runtime interpretuje ją jak:

```yaml
solarman:
  enabled: true
  host: 192.168.1.100
  polling:
    default_interval: 60
rs485:
  enabled: false
```

Po aktualizacji sprawdź nową sekcję `solarman`, zapisz konfigurację i dopiero wtedy opcjonalnie skonfiguruj RS485. Migracja zachowuje pliki z wykrytymi sensorami, własnymi sensorami, wyborem sterowania, stanem runtime i kolejką usuwania Discovery. Zapisany wybór `transport` nie jest wymagany w plikach 1.x - brakujące pole otrzymuje SolarMan TCP, dzięki czemu dotychczasowy wybór nie znika.

MQTT zachowuje wcześniejsze `unique_id`, urządzenie i tematy stanu. Aktualizacja nie wymaga usuwania encji ani ponownego budowania automatyzacji Home Assistant.

Od 2.0.1 pola z dawnych grup `inverter`, `profiles`, `advanced` i `scan` są bezpośrednimi opcjami formularza, aby pozostawały stale widoczne i poprawnie odtwarzały przełączniki. Wersja 2.0.2 usuwa błędną opcję `default_profile`, która w 2.0.1 blokowała zakończenie aktualizacji i ponowne uruchomienie dodatku. Profil `deye_battery_packs` jest od tej wersji zawsze aktywny. Po aktualizacji z 2.0.0 sprawdź pozostałe wartości przed uruchomieniem dodatku, szczególnie numer seryjny falownika i niestandardowe ścieżki plików. Runtime nadal potrafi odczytać dawny zagnieżdżony układ z pliku opcji.

## MQTT i Home Assistant

Domyślnie `mqtt.use_supervisor: true` pobiera host, port, TLS i dane logowania z usługi MQTT Home Assistant Supervisor. Ustaw `false` tylko dla świadomie skonfigurowanego brokera zewnętrznego.

Domyślne wartości zachowujące zgodność to:

```yaml
client_id: solarman
base_topic: solarman_diagnostics
```

Dla każdego sensora jest jeden wspólny temat stanu, niezależny od transportu:

```text
solarman_diagnostics/<serial_falownika>/<topic_suffix>
```

Dodatkowe tematy to:

```text
solarman_diagnostics/<serial_falownika>/<topic_suffix>/attributes
solarman_diagnostics/<serial_falownika>/<topic_suffix>/raw
solarman_diagnostics/<serial_falownika>/<topic_suffix>/availability
solarman_diagnostics/<serial_falownika>/availability
```

`attributes` zawiera pole `transport`. Dostępność sensora jest wyliczana ze wspólnej dostępności sesji/procesu oraz dostępności konkretnej encji. Last Will i kontrolowane zatrzymanie publikują wspólne `offline`.

Tematy sterowania mają postać:

```text
solarman_diagnostics/<serial_falownika>/controls/<klucz>/state
solarman_diagnostics/<serial_falownika>/controls/<klucz>/set
solarman_diagnostics/<serial_falownika>/controls/<klucz>/availability
```

Zapisana encja wybiera transport w konfiguracji, lecz nazwa jej tematu i `unique_id` nie zależą od transportu.

## Katalogi sensorów i sterowania

Wbudowany profil `deye_battery_packs` jest zawsze aktywny i nie jest widoczny w konfiguracji. Lista panelu pochodzi z dwóch zewnętrznych adresów:

- `catalog.url` - sensory telemetryczne i szablony BMS;
- `catalog.control_url` - definicje sterowania.

Dodatek pobiera YAML, waliduje strukturę, a następnie atomowo zapisuje poprawny cache. Kod z sieci nie jest wykonywany. Gdy pobranie nie powiedzie się, używana jest ostatnia poprawna kopia. Jeśli poprawnego źródła i cache nie ma, odpowiednia lista jest pusta.

Katalog deklaruje obsługiwane transporty. Panel pozwala wybrać transport tylko wtedy, gdy dana definicja obsługuje więcej niż jeden transport. Wybór można zapisać dopiero po wyniku `supported` dla tego transportu.

## Panel Ingress i i18n

Panel oraz formularz opcji dodatku mają kompletne tłumaczenia polskie i angielskie. Język jest wybierany na podstawie ustawień Home Assistant i przeglądarki.

Zakładki panelu:

- `Sensory` - skan telemetrii, wybór transportu i publikacji MQTT;
- `Sterowanie` - skan aktualnych ustawień i wybór encji sterowania;
- `Własne sensory` - ręczne sensory Modbus oraz formuły.

Nagłówek pokazuje aktywność SolarMan TCP oraz Modbus RTU. Wyniki skanu przechowują oddzielny status i `latency_ms` dla obu transportów. Typowe statusy to `supported`, `unsupported`, `unavailable`, `timeout` i `invalid_value`.

Wynik `supported` jest pamiętany jako potwierdzenie mapy rejestru. Bieżący stan `online` albo `offline` pochodzi z działającego workera transportu. Jeśli wcześniej sprawdzony RS485 zostanie odłączony, karta nadal pokazuje `supported`, dodaje `offline` i natychmiast usuwa RS485 z pola wyboru bez potrzeby ponownego skanu.

### Skan sensorów

1. Otwórz `Sensory`.
2. Wybierz `Skanuj teraz`.
3. Dodatek odczyta SolarMan TCP, a potem RS485.
4. Porównaj wartość, RAW, HEX, status i opóźnienie.
5. Dla obsługiwanych pozycji wybierz transport oraz MQTT.
6. Zapisz wybór.

Skan jest tylko do odczytu. Nie tworzy komend FC16.

### Skan sterowania

Zakładka `Sterowanie` używa własnej mapy, ale skan nadal tylko odczytuje bieżące ustawienia. Nie ma indywidualnego przycisku Test. Definicje nieznane, read-only albo bez potwierdzonego zakresu nie mogą zostać włączone jako encje zapisujące.

Prawdziwy zapis następuje dopiero po wysłaniu komendy do wybranej encji MQTT. Szczegółowy kontrakt opisuje [CONTROL_ENTITIES.md](CONTROL_ENTITIES.md).

### Własne sensory

`Własne sensory` przechowują definicje w `/config/custom_sensors.yaml`. Standardowy sensor określa rejestry, typ, mnożnik, offset, kolejność słów i transport. Formuła może używać ograniczonego interpretera z funkcjami `sensor(...)` i `RAW(...)`.

Typ `enum` mapuje całą wartość jednego rejestru na opis stanu. Typ `bitmask` dekoduje aktywne bity jednego lub kilku kolejnych rejestrów. Dla obu typów można podać mapę wartości lub bitów, opis zera oraz szablon nieznanego stanu. Wbudowany katalog używa tego mechanizmu dla Run State, Relay Status, Warning Flags i Fault Flags.

Test własnego sensora jest operacją read-only. Dla wyboru `oba` wykonuje kolejno SolarMan TCP, a następnie RS485 i pokazuje oddzielny wynik każdego transportu. Test nie publikuje MQTT i nie zmienia ustawień falownika.

Formuły nie mogą wykonywać importów, operacji plikowych, dostępu do sieci, `eval`, `exec`, rekurencji ani dowolnych funkcji Pythona.

## Bezpieczeństwo sterowania

Encja sterowania działa wyłącznie na zapisanym, obsługiwanym transporcie. Nie ma automatycznego przełączenia zapisu na drugi transport.

Każda komenda przechodzi walidację, read-before-write, pojedynczy FC16 i read-back. Błąd po rozpoczęciu FC16 oznacza niepewny wynik. Runtime nie ponawia takiej komendy i globalnie blokuje wszystkie dalsze zapisy na obu transportach. Odczyty pozostają aktywne. Blokadę usuwa przeładowanie konfiguracji po jej zapisaniu albo restart dodatku.

Błąd połączenia stwierdzony przed rozpoczęciem FC16 nie jest niepewnym zapisem i nie uruchamia globalnej blokady.

## Pliki trwałe

- `/config/detected_sensors.yaml` - wyniki skanu, konfiguracja sensorów, wybór MQTT i transportu;
- `/config/custom_sensors.yaml` - własne sensory i formuły;
- `/config/user_sensors.yaml` - lokalne nadpisania;
- `/config/runtime_state.json` - wartości, czasy publikacji i liczniki timeoutów;
- `/config/deye_solarman_catalog.yaml` - cache katalogu sensorów;
- `/config/deye_solarman_control_catalog.yaml` - cache katalogu sterowania;
- `/config/deye_solarman_discovery_removals.yaml` - kolejka usuwania MQTT Discovery;
- `/share/deye_solarman_candidate_scan.json` - raport ręcznego skanu;
- `/share/deye_solarman_scan_report.json` - opcjonalny raport monitorowania.

Zmiana transportu lub wyłączenie encji zachowuje jej tożsamość MQTT. Usunięcie encji publikuje pustą retained konfigurację Discovery, aby Home Assistant usunął nieaktualny wpis.

## Logowanie i diagnostyka

`detailed_logs` jest domyślnie `false`. W normalnym trybie dodatek rejestruje start, utratę połączenia, ponowne łączenie i błędy, ale ogranicza:

- pojedyncze potwierdzenia każdej publikacji MQTT;
- zakresy każdego odczytu;
- pełne tracebacki oczekiwanych rozłączeń;
- powtarzające się szczegóły połączenia.

Ustaw `detailed_logs: true` tylko na czas diagnozy. Hasło MQTT nie jest wypisywane w logu.

Jeśli jeden transport ma status `unavailable`, sprawdź jego konfigurację i log. Drugi worker powinien nadal publikować swoje encje. Jeśli wspólna dostępność MQTT jest `offline`, sprawdź broker i cały proces dodatku.

## Granice weryfikacji

Testy automatyczne i testy pakietu potwierdzają strukturę konfiguracji, import runtime, zachowanie adapterów z atrapami, kodowanie map oraz symulowany kontrakt zapisu. Nie potwierdzają:

- fizycznego portu USB widocznego w konkretnym HAOS;
- okablowania, terminacji ani timingu RS485;
- parametrów portu i Modbus ID konkretnej instalacji;
- map rejestrów konkretnego firmware;
- semantyki wszystkich wartości BMS;
- rzeczywistego FC16 falownika;
- wpływu zmienionej nastawy na lokalną instalację.

Przed włączeniem sterowania porównaj odczyty obu transportów z interfejsem falownika. Pierwsze zapisy wykonuj tylko po potwierdzeniu mapy dla konkretnego modelu i firmware.

## Źródła

- [Home Assistant - app configuration](https://developers.home-assistant.io/docs/apps/configuration/)
- [Home Assistant - app presentation](https://developers.home-assistant.io/docs/apps/presentation/)
- [PyModbus - client documentation](https://pymodbus.readthedocs.io/en/latest/source/client.html)
- [Katalog modelu i informacje o źródłach](../catalogs/models/deye_sg04_sg05_3ph_lv/README.md)

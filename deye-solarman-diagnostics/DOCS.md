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
  host: core-mosquitto
  port: 1883
  username: ""
  password: ""
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
```

Parametry loggera musza wskazywac logger Solarman, nie adres IP samego falownika. `serial_number` w sekcji `logger` to numer loggera, a `inverter.serial_number` to numer seryjny falownika uzywany w nazwach MQTT.

## Panel konfiguracji Ingress

Po aktualizacji do wersji `0.3.0` Home Assistant pokazuje w panelu bocznym pozycje `Deye Solarman`. Jest to lokalny panel Ingress dodatku, dostepny bez mapowania portu na siec domowa.

Panel umozliwia:

- uruchomienie recznego skanu przyciskiem `Skanuj teraz`;
- przegladanie wartosci zdekodowanej, RAW i hex dla kazdego rejestru;
- filtrowanie wedlug statusu i wyszukiwanie po nazwie, kluczu, kategorii lub rejestrze;
- zaznaczenie encji do MQTT przeznikiem `MQTT`;
- zmiane nazwy, typu, mnoznika, offsetu, jednostki, slow order, interwalow, progu zmiany, retain i metadanych Home Assistant;
- atomowy zapis konfiguracji przyciskiem `Zapisz wybor MQTT`.

Adresy rejestrow, klucze encji i ich lista nie sa edytowalne w panelu. Chroni to katalog przed przypadkowa zmiana definicji Modbus. Po zapisie panel wyswietla informacje o koniecznosci restartu dodatku. Restart jest wymagany, aby petla MQTT zaladowala nowy wybor.

## Skanowanie i wybor encji

Skan uruchamia sie wylacznie recznie. Nie jest wykonywany w normalnym cyklu odczytu.

1. Ustaw `scan.mode: disabled` i uruchom dodatek.
2. Otworz panel `Deye Solarman` z paska bocznego Home Assistant.
3. Wybierz `Skanuj teraz`. Dodatek wykona probe polaczenia i odczyta katalog rejestrow sekwencyjnie. Nie tworzy przy tym encji MQTT.
4. W panelu wlacz `MQTT` tylko przy pozycjach o statusie `supported`, ktore chcesz publikowac. Dostosuj parametry w `Konfiguruj dekodowanie i odpytywanie`, jesli sa potrzebne.
5. Wybierz `Zapisz wybor MQTT`, a nastepnie zrestartuj dodatek. Od tej chwili tylko zaznaczone encje sa odpytywane oraz publikowane do MQTT.

Opcja `scan_and_monitor` wykonuje skan podczas startu, aktualizuje oba pliki, a nastepnie przechodzi od razu do normalnego MQTT. Uzywaj jej tylko wtedy, gdy istniejace zaznaczenia sa juz poprawne. `scan_only` wykonuje skan podczas startu, nie laczy sie z MQTT i pozostawia uruchomiony panel Ingress do wyboru encji.

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

Mozna zmienic miedzy innymi `type`, `multiplier`, `offset`, `unit`, `word_order`, `schedule`, `read_every`, `report_every`, `change_by`, `retain` i pola MQTT. Dla wartosci BMS nie zmieniaj przelicznika ani typu przed porownaniem z realnym odczytem urzadzenia.

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

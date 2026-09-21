# SolarMan Diagnostics 2.0.5

`SolarMan Diagnostics` jest jednym instalowalnym dodatkiem Home Assistant OS do lokalnej komunikacji z falownikiem Deye. Jeden proces może jednocześnie obsługiwać dwa transporty:

- SolarMan TCP przez logger w sieci LAN;
- Modbus RTU przez bezpośredni adapter USB-RS485.

Dodatek używa jednego połączenia MQTT, jednego urządzenia Home Assistant i wspólnych identyfikatorów encji. Każda encja ma dokładnie jeden wybrany transport. Odczyt i zapis nie przełączają się samoczynnie na drugi transport.

## Tryby pracy

| Tryb | `solarman.enabled` | `rs485.enabled` | Zastosowanie |
| --- | --- | --- | --- |
| `solarman-only` | `true` | `false` | Odczyt i sterowanie przez lokalny logger SolarMan TCP. |
| `rs485-only` | `false` | `true` | Bezpośredni odczyt i sterowanie Modbus RTU. |
| `dual` | `true` | `true` | Oba transporty działają równocześnie, a transport jest wybierany osobno dla każdej encji. |

Co najmniej jeden transport musi być włączony. W trybie `dual` każdy transport ma niezależny worker, klienta, blokadę, interwały i ponowne łączenie. Awaria jednego transportu nie zatrzymuje odczytów drugiego.

## Najważniejsze funkcje

- sekwencyjny skan SolarMan TCP, a następnie RS485;
- niezależne monitorowanie i interwały obu transportów;
- panel Ingress z zakładkami `Sensory`, `Sterowanie` i `Własne sensory`;
- pełne tłumaczenia panelu i konfiguracji dodatku po polsku i angielsku;
- status oraz opóźnienie każdego transportu;
- wybór transportu tylko wtedy, gdy mapa rejestru i skan potwierdzają jego obsługę;
- MQTT Discovery dla wybranych sensorów i encji sterowania;
- zewnętrzne, walidowane katalogi sensorów i sterowania z lokalnym cache;
- odczyty RAW, HEX i atrybuty diagnostyczne;
- bezpieczne, lokalne formuły własnych sensorów;
- kontrolowany zapis ustawień przez MQTT.

## Przepływ danych

```text
Logger SolarMan TCP ----+
                        +--> jeden proces SolarMan Diagnostics --> jeden klient MQTT --> Home Assistant
USB-RS485 / Modbus RTU -+
```

Skan panelu otwiera transporty w ustalonej kolejności SolarMan TCP -> RS485. Normalne monitorowanie korzysta z osobnych workerów, dlatego interwały SolarMan i RS485 nie muszą być takie same.

Każda zapisana definicja sensora lub sterowania zawiera pole `transport` o wartości `solarman_tcp` albo `modbus_rtu`. Runtime używa wyłącznie tego transportu. Brak odpowiedzi nie uruchamia fallbacku.

## MQTT i zgodność encji

Domyślne ustawienia to:

```yaml
mqtt:
  client_id: solarman
  base_topic: solarman_diagnostics
```

Dla danej encji pozostaje jeden wspólny temat stanu niezależny od wybranego transportu:

```text
solarman_diagnostics/<serial_falownika>/<topic_suffix>
```

Zachowane są dotychczasowe identyfikatory:

```text
deye_solarman_<serial_falownika>_<klucz>
```

Komenda encji sterowania używa wspólnego tematu:

```text
solarman_diagnostics/<serial_falownika>/controls/<klucz>/set
```

Atrybut `transport` pokazuje źródło ostatniej wartości. Discovery sensora wymaga jednocześnie wspólnej dostępności procesu i dostępności konkretnej encji. Zatrzymanie procesu lub Last Will ustawia wspólną dostępność na `offline`.

## Panel Ingress

Interfejs ma pełne tłumaczenia PL/EN i trzy zakładki:

- `Sensory` - skan telemetrii, wynik obu transportów, ich opóźnienie i wybór MQTT;
- `Sterowanie` - wspólny skan aktualnych ustawień oraz wybór encji sterowania;
- `Własne sensory` - ręczne definicje Modbus i ograniczone formuły.

Skan sensorów i skan sterowania tylko odczytują rejestry. Zakładka `Sterowanie` nie ma przycisku Test, ponieważ odczyt wykonuje wspólny skan. Przycisk Test we `Własnych sensorach` wykonuje sekwencyjny odczyt wybranego transportu lub obu transportów i nie publikuje MQTT ani nie zapisuje rejestrów.

Prawdziwy zapis jest możliwy wyłącznie po wybraniu bezpiecznej encji sterowania MQTT i wysłaniu komendy do tej encji.

## Bezpieczeństwo zapisów

Ścieżka zapisu działa następująco:

1. Odrzuca komendę retained, nieaktualną, wyłączoną albo spoza katalogu.
2. Sprawdza wybrany transport, zakres, enum, ograniczenia dynamiczne i bieżący stan.
3. Wykonuje read-before-write i zachowuje sąsiednie bity rejestru.
4. Wysyła jeden zapis FC16.
5. Odczytuje wartość ponownie i wymaga zgodnego read-back.

Po rozpoczęciu FC16 timeout lub inny błąd daje niepewny wynik. Taki zapis nie jest automatycznie ponawiany, ponieważ pierwsza komenda mogła zostać przyjęta przez falownik. Runtime globalnie blokuje wszystkie dalsze zapisy na obu transportach do przeładowania konfiguracji po jej zapisaniu albo restartu dodatku. Odczyty nadal działają. Błąd wykryty przed rozpoczęciem FC16 nie uruchamia globalnej blokady.

Szczegóły są w [CONTROL_ENTITIES.md](deye-solarman-diagnostics/CONTROL_ENTITIES.md).

## Konfiguracja RS485

Metadane dodatku zawierają `uart: true`, dzięki czemu Home Assistant może przekazać urządzenie szeregowe do kontenera. Domyślna konfiguracja jest przykładem:

```yaml
rs485:
  enabled: false
  device: /dev/ttyUSB0
  baudrate: 9600
  bytesize: 8
  parity: N
  stopbits: 1
  modbus_id: 1
```

Jest to 9600 8N1 z Modbus ID 1. Nazwę urządzenia, parametry portu i adres Modbus trzeba sprawdzić na rzeczywistym adapterze i falowniku. Wyłączenie RS485 nie wpływa na SolarMan TCP.

## Instalacja

1. W Home Assistant otwórz `Ustawienia -> Dodatki -> Sklep z dodatkami`.
2. Dodaj repozytorium `https://github.com/Wilk33/deye-solarman-ha-addon`.
3. Zainstaluj jeden dodatek `SolarMan Diagnostics`.
4. Skonfiguruj co najmniej jeden transport i numer seryjny falownika.
5. Pozostaw `mqtt.use_supervisor: true`, jeśli używasz usługi MQTT Home Assistant.
6. Uruchom dodatek i otwórz panel Ingress.

Pełny opis opcji, migracji i diagnostyki znajduje się w [DOCS.md](deye-solarman-diagnostics/DOCS.md).

## Migracja z 1.x

Wersja 2.0.5 zachowuje katalog instalacyjny i slug `deye-solarman-diagnostics`, dlatego aktualizacja odbywa się w miejscu.

Starszy układ:

```yaml
logger: {...}
polling: {...}
```

jest interpretowany jako:

```yaml
solarman:
  enabled: true
  # dotychczasowe logger i polling
rs485:
  enabled: false
```

Zapisane wybory sensorów, własnych sensorów, sterowania i MQTT pozostają w dotychczasowych plikach `/config`. Użytkownik włącza RS485 dopiero po skonfigurowaniu i sprawdzeniu fizycznego portu. Migracja nie tworzy drugiego urządzenia MQTT i nie zmienia istniejących `unique_id`.

## Katalogi i ustawienia domyślne

Wbudowany profil `deye_battery_packs` jest zawsze aktywny i nie jest wystawiany w konfiguracji. Pozostałe listy są pobierane z:

- `catalog.url` - niezależny katalog telemetrii;
- `catalog.control_url` - niezależny katalog sterowania.

Każdy adres można pozostawić pusty. Pozwala to używać wyłącznie jednej listy albo łączyć telemetrię i sterowanie od różnych dostawców. Po walidacji każda lista trafia do osobnego, wewnętrznego cache. Jeśli źródło i poprawny cache są niedostępne, odpowiednia lista pozostaje pusta. Zdalny YAML jest traktowany jako dane i nie jest wykonywany jako kod.

`detailed_logs` jest domyślnie wyłączone. W tym trybie log zachowuje informacje operacyjne, ale ogranicza wpisy o pojedynczych publikacjach, zakresach połączeń i tracebackach. Tryb szczegółowy należy włączać tylko na czas diagnostyki.

## Źródła kodu i pakowanie

- `packages/deye_inverter_core/` - wspólny rdzeń, MQTT, skanowanie, panel i sterowanie;
- `apps/deye-solarman/src/deye_solarman_diagnostics/` - adaptery SolarMan TCP i Modbus RTU;
- `catalogs/models/deye_sg04_sg05_3ph_lv/` - mapy i indeks katalogu;
- `deye-solarman-diagnostics/` - jedyny instalowalny katalog dodatku HAOS.

Kopia w `deye-solarman-diagnostics/rootfs/usr/src/app` jest generowana. Po zmianie źródeł uruchom:

```powershell
.work/venv/Scripts/python.exe tools/package_addon.py
.work/venv/Scripts/python.exe tools/package_addon.py --check
.work/venv/Scripts/python.exe -m unittest discover -s tests -v
```

Pakiet 2.0.5 zawiera wspólny rdzeń, oba adaptery, i18n PL/EN oraz katalogi z sumami kontrolnymi. Zależność RTU jest przypięta jako `pymodbus==3.14.0`. Repozytorium nie zawiera drugiego instalowalnego folderu RS485.

## Granice weryfikacji

Testy automatyczne sprawdzają kod, konfigurację, import pakietu, mapy, symulowane odczyty i symulowane zapisy. Nie potwierdzają:

- fizycznego portu USB i przekazania adaptera do kontenera;
- elektrycznej warstwy RS485, polaryzacji przewodów ani timingu RS485;
- adresu Modbus i parametrów 9600 8N1 konkretnej instalacji;
- map rejestrów konkretnego modelu i firmware;
- rzeczywistego FC16 wykonanego na falowniku;
- skutków zmiany nastaw dla lokalnej instalacji.

Przed użyciem sterowania porównaj odczyty z interfejsem falownika i sprawdź zachowanie na konkretnym urządzeniu.

## Dokumentacja i źródła

- [Instrukcja użytkownika](deye-solarman-diagnostics/DOCS.md)
- [Encje sterowania](deye-solarman-diagnostics/CONTROL_ENTITIES.md)
- [Architektura jednego dodatku](docs/architecture/MULTI_ADDON_AND_CATALOGS.md)
- [Home Assistant - app configuration](https://developers.home-assistant.io/docs/apps/configuration/)
- [Home Assistant - app presentation](https://developers.home-assistant.io/docs/apps/presentation/)
- [PyModbus - client documentation](https://pymodbus.readthedocs.io/en/latest/source/client.html)

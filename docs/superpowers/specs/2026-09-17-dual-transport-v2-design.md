# Deye Diagnostics 2.0.0 - projekt dwóch transportów

## Cel

Jeden dodatek Home Assistant obsługuje równocześnie SolarMan TCP i RS485 Modbus RTU. Każdy sensor i każda encja sterująca używa dokładnie jednego wybranego transportu, ale MQTT Discovery, `unique_id`, tematy stanów, katalogi i panel Ingress pozostają wspólne.

## Architektura

`TransportManager` utrzymuje dwa niezależne sloty: `solarman_tcp` i `modbus_rtu`. Slot zawiera klienta, blokadę, konfigurację odczytów, stan połączenia, liczbę błędów i opóźnienie. Awaria jednego slotu nie zatrzymuje drugiego ani MQTT.

`SolarmanClient` i `ModbusRtuTransport` implementują wspólny kontrakt `RegisterTransport`. Adapter RS485 używa synchronicznego `pymodbus.client.ModbusSerialClient` z `retries=0`. Projekt sam steruje reconnectem; po niepewnym zapisie nie wykonuje zapisu ponownie ani przez ten sam, ani przez drugi transport.

Runtime ma jeden publisher MQTT. Definicje encji zachowują dotychczasowe klucze i identyfikatory. Lokalna konfiguracja dodaje `transport`, a wynik skanu przechowuje osobne wyniki pod `last_scan.solarman_tcp` i `last_scan.modbus_rtu`.

## Konfiguracja i migracja

Wersja 2.0.0 zastępuje sekcje `logger` i `polling` sekcjami `solarman` i `rs485`. Każda zawiera `enabled`, parametry połączenia i własne parametry odczytu. Wspólne pozostają MQTT, falownik, profile, skan, katalog i diagnostyka.

Loader akceptuje również konfigurację 1.x. `logger` jest migrowany do aktywnego `solarman`, a wartości `polling` stają się parametrami SolarMan. RS485 jest wtedy wyłączony. Zapisane sensory i sterowania bez pola `transport` otrzymują `solarman_tcp`.

Dodatek otrzymuje `uart: true`, a pole `rs485.device` używa schematu urządzenia szeregowego. Domyślne parametry RS485 są przykładowe i wymagają potwierdzenia na falowniku: `/dev/ttyUSB0`, 9600, 8N1, Modbus ID 1, timeout 1 s.

## Odczyt i scheduler

Każdy transport ma osobny worker i osobny scheduler oparty na `next_due` per sensor. Worker wybiera encje należne dla swojego transportu, grupuje bliskie rejestry i czeka wyłącznie do najbliższego terminu. `read_every` sensora zastępuje domyślny interwał wybranego transportu.

MQTT publikuje stan z jednego aktywnego transportu. Atrybuty zawierają `transport`. Gdy transport jest offline, tylko przypisane mu encje stają się niedostępne.

## Skanowanie

Jeden skan wykonuje dostępne transporty sekwencyjnie w kolejności SolarMan, RS485. Nie uruchamia równoległych żądań do falownika. Każdy wynik ma status `supported`, `timeout`, `invalid_value`, `unavailable` albo `unsupported`. Status zbiorczy `unknown` oznacza, że żaden dozwolony i aktywny transport nie potwierdził encji.

Jeśli działa jeden transport, jest wybierany automatycznie i UI nie pokazuje selektora. Jeśli oba potwierdzą encję, użytkownik wybiera jeden. Jeśli tylko jeden potwierdzi encję, drugi jest pokazany jako niedostępny i nie można go wybrać. Kolejny skan zachowuje wybór, dopóki pozostaje dostępny.

Katalog może ograniczyć skan przez `transports`. Brak pola oznacza oba transporty.

## Sterowanie

Sterowanie używa tego samego modelu wyboru i wyników skanu. Komenda przechodzi wyłącznie do klienta wybranego transportu. Zachowane zostają read-before-write, limity, maski bitowe, FC16, read-back oraz globalna blokada dalszych zapisów po niepewnym wyniku danej komendy.

Skan sterowania nigdy nie zapisuje rejestrów.

## MQTT i usunięcie własności

W jednym procesie nie ma konkurujących wydawców, dlatego `EntityOwnership`, `OwnershipCoordinator`, `/share/entity_owners.json`, source-specific command topics i blokady właściciela zostają usunięte. Discovery, `unique_id` oraz tematy stanów pozostają zgodne z 1.x. Komenda sterowania ma jeden temat pod wspólnym `base_topic`.

## Panel i języki

Konfiguracja dodatku ma pełne `translations/pl.yaml` i `translations/en.yaml`. Panel Ingress używa jednego słownika i18n `pl.json` lub `en.json`, wybieranego z języka przekazanego przez Home Assistant albo domyślnego `pl`.

Karty sensorów i sterowania pokazują wyniki obu transportów, opóźnienie oraz selektor tylko wtedy, gdy oba transporty są możliwe. Test własnego sensora przy dwóch transportach wymaga wskazania transportu; testy obu są wykonywane sekwencyjnie.

## Obsługa błędów

- Nieobecny port szeregowy oznacza offline RS485 i ponawianie po `reconnect_delay`.
- Błąd SolarMan nie zatrzymuje RS485, panelu ani MQTT.
- Błąd RS485 nie zatrzymuje SolarMan, panelu ani MQTT.
- Timeout zapisu nie uruchamia zapisu drugim transportem.
- Nieprawidłowy lub niedozwolony wybór transportu jest odrzucany przed zapisem konfiguracji.

## Kryteria akceptacji

- Działają tryby tylko SolarMan, tylko RS485 i oba naraz.
- Skan dwóch transportów jest sekwencyjny.
- Wybór transportu jest dokładnie jeden per encja i zachowuje się po ponownym skanie.
- Scheduler honoruje krótsze i dłuższe `read_every` niezależnie dla obu transportów.
- Awaria jednego interfejsu nie zatrzymuje drugiego.
- Sterowanie wykonuje jeden zapis przez wybrany transport i zachowuje read-back.
- Zmiana transportu nie zmienia `unique_id` ani encji Home Assistant.
- Konfiguracja 1.x migruje do SolarMan bez utraty wyborów.
- Panel konfiguracji i Ingress działają po polsku i angielsku.

## Ograniczenie weryfikacji

Testy automatyczne używają atrap transportów. Fizyczny port USB-RS485, timing magistrali, zgodność rejestrów i zapisy falownika wymagają sprawdzenia na HAOS oraz konkretnym urządzeniu.

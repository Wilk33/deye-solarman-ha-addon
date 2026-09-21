# SolarMan Diagnostics 2.0.5 - architektura jednego dodatku

## Stan bieżący

Wersja 2.0.5 ma jeden instalowalny katalog `deye-solarman-diagnostics`, jeden proces runtime i jeden klient MQTT. Ten proces może obsługiwać SolarMan TCP, Modbus RTU przez USB-RS485 albo oba transporty równocześnie.

Obsługiwane tryby to:

- `solarman-only`;
- `rs485-only`;
- `dual`.

Repozytorium nie buduje drugiego instalowalnego dodatku RS485. Folder `apps/deye-solarman` zawiera kod aplikacji i oba adaptery, ale nie ma własnego `config.yaml` dla Home Assistant Supervisor.

## Źródła i artefakt

```text
packages/deye_inverter_core/
  wspólny runtime, MQTT, katalogi, skanowanie, UI i sterowanie

apps/deye-solarman/src/deye_solarman_diagnostics/
  punkt startowy, adapter SolarMan TCP i adapter Modbus RTU

catalogs/models/deye_sg04_sg05_3ph_lv/
  catalog-index.yaml, telemetry.yaml, control.yaml

deye-solarman-diagnostics/
  jedyny instalowalny build context Home Assistant OS
```

`tools/package_addon.py` kopiuje pliki Python, JavaScript, i18n PL/EN, katalogi i manifest do `deye-solarman-diagnostics/rootfs/usr/src/app`. Tryb `--check` wykrywa każdą różnicę między źródłem a artefaktem.

Przed obliczeniem SHA-256 oraz zapisaniem katalogu `tools/package_addon.py` normalizuje zakończenia linii CRLF i CR do LF. Manifest i plik w obrazie zawierają dzięki temu tę samą reprezentację bajtową niezależnie od systemu, na którym zbudowano pakiet.

Indeks katalogu ma revision `2.0.5`. Obraz przypina `pymodbus==3.14.0` dla adaptera RTU.

## Granica transportu

Rdzeń zależy od wspólnego kontraktu rejestrów:

```python
class RegisterTransport(Protocol):
	@property
	def transport_id(self) -> str: ...

	def connect(self) -> None: ...
	def close(self) -> None: ...
	def read_holding_registers(self,start: int,count: int) -> list[int]: ...
	def write_holding_registers(self,start: int,values: list[int]) -> object: ...
```

Adapter SolarMan opakowuje `pysolarmanv5`, a adapter RTU klienta `pymodbus`. Rdzeń nie importuje konkretnej biblioteki transportowej.

## TransportManager

`TransportManager` tworzy slot tylko dla włączonego transportu. Każdy slot ma:

- własnego klienta;
- własną blokadę operacji;
- własne ustawienia odpytywania;
- własny limit czasu i opóźnienie ponownego łączenia;
- status oraz ostatnie opóźnienie.

Równoległe workery monitorowania korzystają z osobnych slotów. Awaria jednego slotu nie zatrzymuje zdrowego transportu. Zamknięcie procesu najpierw zatrzymuje i łączy workery, skany i aktywne testy HTTP, a następnie zamyka klientów pod właściwymi blokadami.

## Skanowanie

Skan panelu jest deterministycznie sekwencyjny:

1. SolarMan TCP;
2. Modbus RTU.

Wynik encji zawiera osobną gałąź dla każdego transportu, w tym `status`, `latency_ms`, wartości RAW i ewentualny błąd. Nieaktywny transport ma status `unavailable`, a transport niedozwolony przez mapę `unsupported`.

Po skanie każda encja ma pole `transport`. Selektor jest pokazywany tylko dla definicji wspieranych przez oba transporty. Zapis wyboru wymaga `supported` dla wskazanego transportu. Runtime nie wykonuje fallbacku po błędzie.

Skan telemetrii, skan sterowania i Test własnego sensora są read-only. Test obu transportów również wykonuje je kolejno SolarMan TCP -> RS485.

## Monitoring

Każdy aktywny transport uruchamia niezależny worker z własnym harmonogramem. Definicje są dzielone według zapisanego pola `transport`. Worker otrzymuje tylko swoje encje.

Snapshot runtime jest generacyjny. Przeładowanie konfiguracji tworzy nową generację definicji, zatrzymuje poprzednie workery i nie publikuje spóźnionego wyniku starej generacji. Częściowy odczyt zachowuje poprawne wartości, status i liczniki timeoutów już przetworzonych encji.

## Jeden MQTT

Proces ma jeden `MqttPublisher` i domyślny `client_id: solarman`. Oba transporty publikują do wspólnego `base_topic: solarman_diagnostics`.

Tożsamość sensora nie zawiera transportu:

```text
unique_id: deye_solarman_<serial_falownika>_<klucz>
state: solarman_diagnostics/<serial_falownika>/<topic_suffix>
```

Sterowanie używa:

```text
solarman_diagnostics/<serial_falownika>/controls/<klucz>/set
```

Atrybut stanu zawiera wybrany transport. Discovery sensora odwołuje się do wspólnej dostępności procesu i dostępności per-entity w trybie `all`. Last Will oraz kontrolowane wyłączenie ustawiają wspólną dostępność na `offline`.

## Transakcje konfiguracji i Discovery

Jeden `ConfigurationCoordinator` wyznacza granicę dla:

- zapisu wyborów panelu;
- zmiany snapshotu runtime;
- publikowania i usuwania MQTT Discovery;
- potwierdzania przetworzonych wpisów kolejki usunięć.

Operacje Discovery są idempotentne i potwierdzane przyrostowo po potwierdzonym QoS 1. Błąd w połowie serii nie usuwa lokalnej informacji o wcześniej opublikowanym retained wpisie. Ponowienie kontynuuje pracę, a późniejsze wyłączenie nadal zna wszystkie wpisy wymagające usunięcia.

Rollback plików konfiguracji nie cofa równoległej, już zatwierdzonej generacji runtime.

## Model katalogu

`catalog-index.yaml` wskazuje dwie mapy i ich sumy SHA-256:

- `telemetry` - telemetria oraz szablon pakietów BMS dla zadeklarowanych transportów;
- `control` - odczyt ustawień i jawnie walidowane komendy.

Każda mapa deklaruje `transports`. Loader pakietu sprawdza sumę pliku i zgodność transportu przed użyciem definicji. Zewnętrzne źródła `catalog.url` oraz `catalog.control_url` są niezależne, dzięki czemu użytkownik może łączyć telemetrię i sterowanie od różnych dostawców albo wyłączyć jedną z list. Pobrane mapy są walidowane jako dane YAML i zapisywane atomowo do osobnych, wewnętrznych cache.

Wbudowany profil `deye_battery_packs` jest zawsze aktywny. Nie jest częścią schematu opcji i użytkownik nie może go przypadkowo wyłączyć.

## Sterowanie

Każda komenda sterowania pozostaje związana z jednym transportem. Przebieg obejmuje:

1. walidację komendy oraz jej aktualności;
2. read-before-write;
3. zachowanie bitów współdzielonego rejestru;
4. jeden FC16;
5. read-back;
6. publikację potwierdzonego stanu.

Błąd przed rozpoczęciem FC16 jest rozróżniany od niepewnego wyniku po rozpoczęciu zapisu. Po niepewnym wyniku nie ma ponowienia, a wspólny serwis sterowania globalnie blokuje wszystkie kolejne zapisy na obu transportach. Odczyty nadal działają.

## Konfiguracja i migracja

`config.yaml` ma `version: "2.0.5"`, `uart: true`, sekcje `solarman` i `rs485` oraz kompletne tłumaczenia PL/EN. Pola tożsamości falownika, profili, diagnostyki i skanowania są na najwyższym poziomie, dzięki czemu Home Assistant pokazuje je stale i zapisuje przełączniki jako bezpośrednie wartości konfiguracji.

Parser zachowuje zgodność z konfiguracją 1.x. `logger` wraz ze wspólną sekcją `polling` jest interpretowany jako włączony `solarman`, a RS485 pozostaje wyłączone. Istniejące pliki wyboru są ładowane z domyślnym transportem SolarMan TCP, jeśli starszy wpis nie zawiera pola `transport`.

## Inwarianty wydania

- jeden instalowalny dodatek i jeden proces;
- jeden klient MQTT;
- jedna tożsamość encji niezależnie od transportu;
- dokładnie jeden wybrany transport na encję;
- brak fallbacku odczytu i zapisu;
- skan SolarMan TCP -> RS485;
- niezależne workery monitorowania;
- read-only dla skanów i Test własnego sensora;
- realny zapis wyłącznie przez wybraną encję MQTT;
- brak automatycznego ponowienia niepewnego FC16;
- globalna blokada zapisu po niepewnym wyniku;
- pełne i18n PL/EN;
- domyślnie ograniczone logowanie z `detailed_logs: false`.

## Granice walidacji

Testy jednostkowe, testy współbieżności, smoke import i kontrola pakietu nie potwierdzają fizycznego portu USB, elektryki ani timingu RS485, map rejestrów konkretnego firmware czy rzeczywistego FC16 falownika. Te elementy wymagają testu na docelowym sprzęcie.

## Źródła

- [Home Assistant - app configuration](https://developers.home-assistant.io/docs/apps/configuration/)
- [Home Assistant - app presentation](https://developers.home-assistant.io/docs/apps/presentation/)
- [PyModbus - client documentation](https://pymodbus.readthedocs.io/en/latest/source/client.html)

# Task 2 - adapter Modbus RTU

## Status

Zaimplementowano synchroniczny adapter RS485 Modbus RTU zgodny z `Rs485Config` i wspólnym kontraktem transportu.

## Zakres zmian

- Dodano `ModbusRtuTransport` z `transport_id="modbus_rtu"` oraz metodami `connect`, `close`, `reconnect`, `read_holding_registers` i `write_holding_registers`.
- Konstruktor przyjmuje kompletną fabrykę klienta, dlatego testy nie otwierają fizycznego portu i nie zależą od importu PyModbus podczas importowania modułu.
- Realny klient jest tworzony jako `ModbusSerialClient` z `port`, `baudrate`, `bytesize`, `parity`, `stopbits`, `timeout` i `retries=0`.
- Odczyt i zapis przekazują Modbus ID jako `device_id`.
- Odczyt zwraca zwykłą listę rejestrów.
- Zapis wykonuje dokładnie jedno wywołanie `write_registers`; adapter nie ponawia zapisu automatycznie.
- Brak lub zerwanie połączenia jest zgłaszane jako `TransportConnectionClosedError`.
- Odpowiedzi z `isError()` oraz odpowiedź odczytu bez rejestrów są zgłaszane jako nowy `TransportProtocolError` z modułu wspólnego kontraktu.
- Dodano zależność runtime `pymodbus==3.14.0`.
- Dodano `uart: true` w kanonicznym manifeście dodatku.
- Wygenerowane kopie `rs485.py` oraz `transport.py` zsynchronizowano przez istniejący `tools/package_addon.py`.
- Nie zmieniono MQTT ani runtime aplikacji.

## TDD - RED

Testy adaptera zapisano przed kodem produkcyjnym.

Polecenie:

```powershell
.\.work\venv\Scripts\python.exe -m unittest tests.test_dual_transport.ModbusRtuTransportTests -v
```

Wynik oczekiwanej porażki:

```text
ModuleNotFoundError: No module named 'deye_solarman_diagnostics.rs485'
Ran 1 test in 0.000s
FAILED (errors=1)
exit_code=1
```

Porażka wynikała bezpośrednio z braku modułu adaptera wymaganego przez Task 2.

## TDD - GREEN

Testy adaptera po implementacji:

```powershell
.\.work\venv\Scripts\python.exe -m unittest tests.test_dual_transport.ModbusRtuTransportTests -v
```

Wynik:

```text
Ran 8 tests in 0.007s
OK
exit_code=0
```

Pełny plik testów Task 2 po synchronizacji pakietu:

```text
Ran 13 tests in 0.032s
OK
exit_code=0
```

## Weryfikacja

- Import adaptera z wygenerowanego katalogu pakietu: `packaged import OK`, kod `0`.
- Pełna regresja: `Ran 115 tests in 12.718s`, `OK`, kod `0`.
- `python -m compileall`: kod `0`.
- `tools/package_addon.py --check`: `Verified 41 files`, kod `0`.
- `git diff --check`: kod `0`; Git zgłosił jedynie informację o przyszłej normalizacji LF do CRLF w `requirements.txt`.

## Self-review

- Każda metoda publicznego kontraktu jest wykonywana przez testy; reconnect zamyka starego klienta i tworzy nowego.
- Test fabryki sprawdza komplet parametrów 8N1 i `retries=0` na literalnych wartościach niezależnych od implementacji.
- Testy odczytu i zapisu sprawdzają literalne argumenty `address`, `count` lub `values` oraz `device_id`.
- Test zapisu sprawdza pojedynczą operację `write_registers`; adapter nie ma pętli retry ani fallbacku na inny transport.
- Testy pokrywają brak połączenia, połączenie zerwane, nieudany `connect()` oraz błędne odpowiedzi odczytu i zapisu.
- Import PyModbus pozostaje w domyślnej fabryce, więc pełna wstrzyknięta fabryka wystarcza do testów bez fizycznego portu.
- Kanoniczna i wygenerowana kopia adaptera są synchronizowane przez dotychczasowy mechanizm pakowania.
- Zakres poza briefem ogranicza się do `TransportProtocolError` w `transport.py`, potrzebnego do odróżnienia prawidłowej odpowiedzi błędu Modbus od zerwanego połączenia.
- Nie znaleziono zmian w MQTT, publisherze ani runtime.

## Ryzyka i ograniczenia

- Nie wykonano testu na fizycznym USB-RS485, HAOS ani falowniku; port, timing magistrali, parametry 8N1, Modbus ID i rejestry wymagają weryfikacji urządzeniowej.
- Testy adaptera korzystają z kompletnej fabryki klienta i nie wykonują transmisji szeregowej.
- Lokalne środowisko zawiera PyModbus 3.15.0, a obraz dodatku jest przypięty do wymaganej wersji 3.14.0. Użyte sygnatury sprawdzono lokalnie, lecz integrację dokładnie z 3.14.0 zweryfikuje dopiero budowa obrazu lub środowisko z zależnościami obrazu.
- Timeout zapisu nadal oznacza niepewny wynik po stronie falownika. Adapter celowo nie ponawia takiego zapisu.

# Sterowanie

Wersja 1.4.0 udostępnia zakładkę Ingress: **Sterowanie**. Ma osobny wynik skanu i wybór MQTT. Używa wyglądu, filtrów i układu kart znanych z zakładki Sensory. Lista jest pobierana z `catalog.control_url` i zapisywana jako cache w `catalog.control_cache_file`; bez poprawnego źródła lub cache pozostaje pusta.

## Obsługa

1. Otwórz **Sterowanie** i wybierz **Skanuj teraz**. Skan odczytuje aktualne ustawienia, bez zapisu rejestrów.
2. Przejrzyj wartości, HEX i ewentualny powód blokady zapisu. Indywidualne przyciski testu zostały usunięte; stan odświeża skan.
3. Zaznacz **MQTT** przy poprawnie odczytanych encjach i wybierz **Zapisz wybór MQTT**. Dodatek automatycznie przeładuje runtime.
4. Steruj encjami z Home Assistant. Liczby są publikowane jako `number`, przełączniki jako `switch`, listy wyboru i godziny programów jako `select`, a zegar systemowy jako `text` w formacie `YYYY-MM-DD HH:MM:SS`.

**Reset konfiguracji** przywraca nazwy i harmonogramy oraz odznacza MQTT. **Usuń encje** usuwa lokalną listę i wycofuje jej MQTT Discovery. Obie operacje dotyczą konfiguracji dodatku; nie resetują ustawień falownika.

Można zmienić nazwę, ikonę, interwał odczytu, interwał ponownej publikacji, próg zmiany i zachowywanie stanu MQTT. Adresy, maski, przeliczniki oraz kodowanie komend pochodzą z katalogu i nie są nadpisywane formularzem.

## Mapa i pochodzenie

Katalog zawiera **115 encji** profilu `three_phase_lv`, bez powielania aliasów. Nie zawiera `US version grounding fault`, `Grid Standard`, `Configured Grid Phases` ani `Allow Remote`. Kanoniczna mapa jest w `catalogs/models/deye_sg04_sg05_3ph_lv/control.yaml`; używa składni JSON zgodnej z YAML. Pakowanie kopiuje ją wraz z indeksem i sumą SHA-256 do danych wspólnego rdzenia. Źródło zostało przypięte do commita `e2466b6505c1990aced1f18c12a42ded638aee9b` projektu kellerza/sunsynk:

- [Profil trójfazowy wspólny](https://github.com/kellerza/sunsynk/blob/e2466b6505c1990aced1f18c12a42ded638aee9b/src/sunsynk/definitions/three_phase_common.py).
- [Profil trójfazowy LV](https://github.com/kellerza/sunsynk/blob/e2466b6505c1990aced1f18c12a42ded638aee9b/src/sunsynk/definitions/three_phase_lv.py).
- [Kodowanie i dekodowanie encji zapisywalnych](https://github.com/kellerza/sunsynk/blob/e2466b6505c1990aced1f18c12a42ded638aee9b/src/sunsynk/rwsensors.py).
- [Zapis i zachowywanie pozostałych bitów](https://github.com/kellerza/sunsynk/blob/e2466b6505c1990aced1f18c12a42ded638aee9b/src/sunsynk/sunsynk.py).

Przykładowe wpisy:

| Ustawienie | Rejestr | Typ i metoda |
| --- | --- | --- |
| Inverter enabled | 80 | Przełącznik 0/1 |
| Battery Max Charge current | 108 | Liczba, A |
| Grid Charge Battery current | 128 | Liczba, A |
| Load Limit | 142 | Lista: Allow Export, Essentials, Zero Export |
| Export Limit power | 143 | Liczba z limitem odczytywanym z Rated power |
| Prog Time Of Use Enabled | 146 | Przełącznik, maska bitu 0 |
| Prog1 Time | 148 | Godzina HHMM, granice od sąsiednich programów |
| Prog1 charge | 172 | Lista, maska 0x03 |
| Prog1 mode | 172 | Lista, maska 0x1C |
| Battery 1 Manufacturer | 229 | Lista protokołów producentów BMS |

To definicje projektu Sunsynk, nie potwierdzenie zgodności każdego pola z lokalnym firmware. Skan potwierdza odczyt i dekodowanie; nie wykonuje próbnego zapisu.

Eksporter `tools/import_sunsynk_controls.py` wymaga checkoutu dokładnie powyższej rewizji i zależności biblioteki Sunsynk w środowisku deweloperskim. Runtime dodatku nie importuje ani nie pobiera kodu Sunsynk. Runtime pobiera wyłącznie zweryfikowane dane YAML z adresu ustawionego w `catalog.control_url`.

## Własność od 1.3.0

Stan i atrybuty są nadal wspólne, a Discovery i unique_id pozostają bez zmian. Temat komend jest właściwy dla źródła. `/share/entity_owners.json` i stabilny plik blokady uniemożliwiają równoczesne przydzielenie tej samej encji dwóm transportom. Wybór zajętej encji jest zablokowany w panelu i odrzucany przez API (HTTP 409). Runtime sprawdza właściciela ponownie pod blokadą przed zapisem i read-back; stara kolejka nie może usunąć Discovery nowego właściciela.

Źródła mają osobne identyfikatory połączenia MQTT oraz `origin`. Przeniesienie wykonuje się przez wyłączenie MQTT i zapis w pierwszej aplikacji, następnie włączenie i zapis w drugiej. Sam restart/zatrzymanie nie zwalnia rejestracji. Rozwiązanie wymaga wspólnego rejestru i obsługi protokołu przez oba dodatki; nie steruje istniejącym zewnętrznym Sunsynk multi.

## Komendy i odczyty

Wiadomości MQTT trafiają do ograniczonej kolejki. Runtime obsługuje je przez tę samą blokadę co telemetrię, formuły i skany. Zmiana ustawienia wykonuje kolejno: odczyt aktualnego słowa, odczyt zależnych granic, walidację, kodowanie, zapis FC16 oraz odczyt kontrolny. Przy masce bitowej pozostałe bity pozostają zachowane.

Implementacja korzysta z mapy i formatów Sunsynk z lokalnymi korektami opisanymi poniżej. Odrzuca wartości spoza zakresu zamiast przycinać je do granic. Odrzuca też NaN, nieskończoność i wartości niezgodne z krokiem. Wielosłowowy zegar jest zapisywany w jednej operacji FC16. Liczby nie przekraczają zakresu dostępnych słów nawet wtedy, gdy granica w źródle jest większa.

Komendy retained, obce klucze i polecenia dla odznaczonych encji są pomijane. Kolejka mieści 32 komendy; komenda wygasa po 10 sekundach, również podczas oczekiwania na skan. Udane komendy są rozdzielone co najmniej sekundą. Nie ma automatycznego ponawiania zapisu po timeout. Niepewny wynik lub błędny read-back blokuje dalsze zapisy do ponownego zapisania konfiguracji albo restartu dodatku. Same odczyty nadal mogą działać. Jedna blokada obejmuje tylko ten dodatek, nie inne klienty RS485 lub chmurę.

MQTT Discovery ma `optimistic: false` i `retain: false` dla komend. Stan i atrybuty korzystają z ustawień zachowywania stanu. Dostępność uwzględnia połączenie MQTT i wynik odczytu konkretnej encji. Tematy są oddzielone od telemetrii:

```text
<base_topic>/<inverter_serial>/controls/<control_key>/state
<base_topic>/<inverter_serial>/source/solarman_tcp/controls/<control_key>/set
<base_topic>/<inverter_serial>/controls/<control_key>/attributes
<base_topic>/<inverter_serial>/source/solarman_tcp/controls/<control_key>/availability
```

Konfiguracja, wynik skanu i lista opublikowanych encji są zapisywane atomowo do `control_sensors.json`, w tym samym katalogu co `detected_sensors.yaml` (domyślnie `/config/control_sensors.json`). Usunięcie encji wycofuje Discovery z właściwej domeny `number`, `switch`, `select` lub `text`.

## Korekty mapy w 1.2.1

Korekty są zapisane w `catalogs/models/deye_sg04_sg05_3ph_lv/control-overrides.json` i nakładane po każdym imporcie Sunsynk. Aktualizacja wczytuje poprawione definicje także dla wcześniej zapisanych encji. Zachowuje ich klucze MQTT, własne nazwy i harmonogramy; stara domyślna nazwa pojemności jest zastępowana poprawną.

| Rejestr | Bieżące zachowanie |
| --- | --- |
| R102 | Battery Capacity, Ah. Dotychczasowy klucz `control_battery_capacity_current` pozostaje dla ciągłości encji. |
| R108/R109 | Maksimum wyznaczane z R20/R21 (moc znamionowa): 5/6/8/10/12 kW odpowiada 120/150/190/210/240 A. Nierozpoznana moc blokuje zapis, pozostawiając odczyt aktualnego prądu. |
| R139 | Wartość jest odczytywana, np. 500 W. Fałszywy limit 100 W usunięto. Maksimum niepotwierdzone, więc zapis i tworzenie encji sterowania są zablokowane. |
| R336 | Parallel Modbus SN: `(raw & 0xFC00)>>10`, zakres 0..63. Zapis przesuwa wartość o 10 bitów i zachowuje pozostałe pola rejestru. |
| R182/R184 | RAW/UNKNOWN. Cała definicja pozostaje tylko do odczytu do potwierdzenia mapy firmware; żaden kod nie jest domyślnie interpretowany jako liczba faz lub standard sieci. |
| R178/R228 | Nieznany stan pola, w tym 00, jest UNKNOWN / Not applicable. Nie jest zamieniany na Disable i nie staje się opcją możliwą do zapisu. Znane stany zachowują obsługę sterowania. |

Runtime ponownie odczytuje stan przed każdą komendą i odrzuca zapis nieznanego pola. Dla już wybranej encji UNKNOWN publikowane są atrybuty RAW i niedostępność; nie jest wysyłana niepoprawna opcja do MQTT select. Encja może wrócić do sterowania po rozpoznanym odczycie. R139/R182/R184 są odznaczane, a ich wcześniej opublikowane Discovery jest wycofywane.

Podstawa limitów oraz Ah: [instrukcja Deye SUN-(5-12)K-SG04LP3-EU, strona drukowana 36](https://www.deyeinverter.com/deyeinverter/2026/03/19/BManualSUN-5-12K-SG04LP3-EU20260319en.pdf) i [karta katalogowa Deye 8-12 kW](https://pl.deyeinverter.com/deyeinverter/2024/08/05/datasheet_sun-8-12k-sg04lp3_240729_pl.pdf). Pozostałe korekty bazują na masce źródłowej Sunsynk i wynikach odczytu przekazanych przez użytkownika 2026-09-16. Brak potwierdzonego maksimum R139 i słowników konkretnego firmware pozostaje jawnie oznaczony. Zgłoszone poprawne odczyty nie stanowią potwierdzenia fizycznych zapisów.

## Testowanie

Testy `tests/test_controls.py` obejmują odczyt bez zapisu, API Ingress, skan, utrwalanie wyboru, maski bitowe, limity dynamiczne, liczby ze znakiem, godziny, odrzucanie komend, brak ponawiania niepewnych zapisów, formaty Discovery i usuwanie encji.

```text
python -m unittest discover -s tests -v
```

Testy automatyczne używają symulowanych rejestrów i klienta MQTT. Nie zastępują sprawdzenia na HAOS i konkretnym falowniku.

Dokumentacja MQTT Home Assistant: [Number](https://www.home-assistant.io/integrations/number.mqtt/), [Select](https://www.home-assistant.io/integrations/select.mqtt/), [Switch](https://www.home-assistant.io/integrations/switch.mqtt/), [Text](https://www.home-assistant.io/integrations/text.mqtt/).

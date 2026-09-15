# Encje sterowania

Wersja 1.2.0 dodaje trzecią zakładkę Ingress: **Encje sterowania**. Ma osobny wynik skanu i wybór MQTT. Używa wyglądu, filtrów i układu kart znanych z zakładki Wykryte sensory.

## Obsługa

1. Otwórz **Encje sterowania** i wybierz **Skanuj teraz**. Skan odczytuje aktualne ustawienia, bez zapisu rejestrów.
2. Przejrzyj wartości i HEX. **Test - odczytaj stan** wykonuje pojedynczy odczyt wybranej encji, bez publikacji MQTT i bez zmiany ustawienia.
3. Zaznacz **MQTT** przy poprawnie odczytanych encjach i wybierz **Zapisz wybór MQTT**. Dodatek automatycznie przeładuje runtime.
4. Steruj encjami z Home Assistant. Liczby są publikowane jako `number`, przełączniki jako `switch`, listy wyboru i godziny programów jako `select`, a zegar systemowy jako `text` w formacie `YYYY-MM-DD HH:MM:SS`.

**Reset konfiguracji** przywraca nazwy i harmonogramy oraz odznacza MQTT. **Usuń encje** usuwa lokalną listę i wycofuje jej MQTT Discovery. Obie operacje dotyczą konfiguracji dodatku; nie resetują ustawień falownika.

Można zmienić nazwę, ikonę, interwał odczytu, interwał ponownej publikacji, próg zmiany i zachowywanie stanu MQTT. Adresy, maski, przeliczniki oraz kodowanie komend pochodzą z katalogu i nie są nadpisywane formularzem.

## Mapa i pochodzenie

Katalog zawiera **119 encji** profilu `three_phase_lv`, bez powielania aliasów. Kanoniczna mapa jest w `catalogs/models/deye_sg04_sg05_3ph_lv/control.yaml`; używa składni JSON zgodnej z YAML. Pakowanie kopiuje ją wraz z indeksem i sumą SHA-256 do danych wspólnego rdzenia. Źródło zostało przypięte do commita `e2466b6505c1990aced1f18c12a42ded638aee9b` projektu kellerza/sunsynk:

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

Eksporter `tools/import_sunsynk_controls.py` wymaga checkoutu dokładnie powyższej rewizji i zależności biblioteki Sunsynk w środowisku deweloperskim. Runtime dodatku nie importuje ani nie pobiera kodu Sunsynk. Katalog sterowania jest częścią obrazu, osobną od zdalnej mapy telemetrycznej YAML.

## Komendy i odczyty

Wiadomości MQTT trafiają do ograniczonej kolejki. Runtime obsługuje je przez tę samą blokadę co telemetrię, formuły i skany. Zmiana ustawienia wykonuje kolejno: odczyt aktualnego słowa, odczyt zależnych granic, walidację, kodowanie, zapis FC16 oraz odczyt kontrolny. Przy masce bitowej pozostałe bity pozostają zachowane.

Implementacja zachowuje mapę i formaty Sunsynk, ale odrzuca wartości spoza zakresu zamiast przycinać je do granic. Odrzuca też NaN, nieskończoność i wartości niezgodne z krokiem. Wielosłowowy zegar jest zapisywany w jednej operacji FC16. Liczby nie przekraczają zakresu dostępnych słów nawet wtedy, gdy granica w źródle jest większa.

Komendy retained, obce klucze i polecenia dla odznaczonych encji są pomijane. Kolejka mieści 32 komendy; komenda wygasa po 10 sekundach, również podczas oczekiwania na skan. Udane komendy są rozdzielone co najmniej sekundą. Nie ma automatycznego ponawiania zapisu po timeout. Niepewny wynik lub błędny read-back blokuje dalsze zapisy do ponownego zapisania konfiguracji albo restartu dodatku. Same odczyty nadal mogą działać. Jedna blokada obejmuje tylko ten dodatek, nie inne klienty RS485 lub chmurę.

MQTT Discovery ma `optimistic: false` i `retain: false` dla komend. Stan i atrybuty korzystają z ustawień zachowywania stanu. Dostępność uwzględnia połączenie MQTT i wynik odczytu konkretnej encji. Tematy są oddzielone od telemetrii:

```text
<base_topic>/<inverter_serial>/controls/<control_key>/state
<base_topic>/<inverter_serial>/controls/<control_key>/set
<base_topic>/<inverter_serial>/controls/<control_key>/attributes
<base_topic>/<inverter_serial>/controls/<control_key>/availability
```

Konfiguracja, wynik skanu i lista opublikowanych encji są zapisywane atomowo do `control_sensors.json`, w tym samym katalogu co `detected_sensors.yaml` (domyślnie `/config/control_sensors.json`). Usunięcie encji wycofuje Discovery z właściwej domeny `number`, `switch`, `select` lub `text`.

## Testowanie

Testy `tests/test_controls.py` obejmują odczyt bez zapisu, API Ingress, skan, utrwalanie wyboru, maski bitowe, limity dynamiczne, liczby ze znakiem, godziny, odrzucanie komend, brak ponawiania niepewnych zapisów, formaty Discovery i usuwanie encji.

```text
python -m unittest discover -s tests -v
```

Testy automatyczne używają symulowanych rejestrów i klienta MQTT. Nie zastępują sprawdzenia na HAOS i konkretnym falowniku.

Dokumentacja MQTT Home Assistant: [Number](https://www.home-assistant.io/integrations/number.mqtt/), [Select](https://www.home-assistant.io/integrations/select.mqtt/), [Switch](https://www.home-assistant.io/integrations/switch.mqtt/), [Text](https://www.home-assistant.io/integrations/text.mqtt/).

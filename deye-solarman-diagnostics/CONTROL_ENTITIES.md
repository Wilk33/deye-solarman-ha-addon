# Encje sterowania - SolarMan Diagnostics 2.0.5

## Zakres

Zakładka `Sterowanie` pokazuje ustawienia z katalogu `control` i pozwala wybrać bezpieczne encje MQTT. Ten sam proces obsługuje SolarMan TCP oraz Modbus RTU (RS485), ale każda encja ma dokładnie jeden zapisany transport.

Tryby dodatku `solarman-only`, `rs485-only` i `dual` nie zmieniają tej zasady. W trybie `dual` komenda działa bez fallbacku na drugi transport. Jeśli wybrany transport jest niedostępny, zapis zostaje odrzucony.

## Operacje tylko do odczytu

Skan zakładki `Sterowanie` jest tylko do odczytu. Odczytuje aktualny stan przez SolarMan TCP, a następnie przez RS485, zapisuje status i opóźnienie obu transportów oraz wskazuje, które definicje są obsługiwane.

Zakładka `Sterowanie` nie ma indywidualnego przycisku Test. Test we `Własnych sensorach` również jest tylko do odczytu. Żadna z tych operacji nie wykonuje FC16.

Prawdziwy zapis występuje wyłącznie przez wybraną encję sterowania MQTT.

## Wybór transportu

Katalog deklaruje listę `transports` dla każdej definicji. Panel pokazuje selektor transportu tylko wtedy, gdy definicja obsługuje SolarMan TCP i Modbus RTU. Zapis wyboru wymaga wyniku `supported` dla wskazanego transportu.

Wybrany transport jest zapisany wraz z definicją encji. Runtime odczytuje stan oraz wykonuje komendę przez ten sam transport. Atrybut MQTT `transport` pozwala sprawdzić aktywny wybór.

Zmiana transportu zachowuje `unique_id`, temat stanu i automatykę Home Assistant.

## Tematy MQTT

Domyślny wspólny prefiks to:

```yaml
client_id: solarman
base_topic: solarman_diagnostics
```

Dla klucza sterowania używane są tematy:

```text
solarman_diagnostics/<serial_falownika>/controls/<klucz>/state
solarman_diagnostics/<serial_falownika>/controls/<klucz>/set
solarman_diagnostics/<serial_falownika>/controls/<klucz>/attributes
solarman_diagnostics/<serial_falownika>/controls/<klucz>/availability
```

Command topic jest wspólny dla obu transportów. Wybór transportu znajduje się w lokalnej konfiguracji encji, a nie w nazwie tematu.

Discovery używa zachowanego identyfikatora:

```text
deye_solarman_<serial_falownika>_<klucz>
```

Dostępność encji zależy od wspólnej dostępności procesu, wspólnej dostępności runtime sterowania oraz dostępności konkretnego klucza. Po kontrolowanym zatrzymaniu albo Last Will wspólna dostępność przechodzi na `offline`.

## Typy encji

Katalog może utworzyć:

- `number` dla liczby z potwierdzonym minimum, maksimum i krokiem;
- `select` dla zweryfikowanego enum;
- `switch` dla potwierdzonej flagi;
- encję czasu albo daty, jeśli katalog określa bezpieczny format.

Definicje oznaczone jako read-only, nieznane albo bez potwierdzonych ograniczeń pozostają widoczne diagnostycznie, lecz nie przyjmują komend.

## Kontrakt bezpiecznego zapisu

Każda zaakceptowana komenda przechodzi ten sam proces:

1. Odrzucenie retained, nieaktualnego lub zbyt dużego payloadu.
2. Sprawdzenie, że encja nadal jest wybrana i zapis nie jest globalnie zablokowany.
3. Sprawdzenie typu, zakresu, enum, ograniczeń dynamicznych i wybranego transportu.
4. Odczyt read-before-write aktualnych rejestrów.
5. Zachowanie sąsiednich bitów w rejestrach współdzielonych.
6. Kodowanie dokładnie wymaganych słów.
7. Pojedynczy zapis FC16.
8. Odczyt kontrolny read-back przez ten sam transport.
9. Publikacja stanu dopiero po zgodnym wyniku read-back.

Kod nie udostępnia surowej konsoli zapisu, zapisu z formuły ani zapisu podczas skanu.

## Błędy i blokada globalna

Błąd wykryty przed rozpoczęciem FC16 oznacza, że zapis nie został rozpoczęty. Komenda kończy się błędem, lecz sama nie blokuje zdrowego transportu ani kolejnych zapisów.

Po rozpoczęciu FC16 timeout, zamknięcie połączenia, błąd odpowiedzi lub niezgodny read-back daje niepewny wynik. Falownik mógł przyjąć pierwszą komendę, dlatego obowiązują dwie zasady:

- brak ponowienia tej komendy;
- globalna blokada wszystkich dalszych zapisów, zarówno SolarMan TCP, jak i RS485.

Blokada nie zatrzymuje odczytów, skanów ani publikacji stanu. Jest usuwana dopiero przez przeładowanie konfiguracji po jej zapisaniu albo restart dodatku. Przed odblokowaniem trzeba porównać aktualne ustawienie z falownikiem.

## Ograniczenia wartości

Katalog i runtime sprawdzają ograniczenia statyczne oraz dynamiczne. Przykładowo wartość może zależeć od mocy znamionowej odczytanej z innego rejestru. Jeśli ograniczenia nie dają się wiarygodnie wyznaczyć, zapis jest blokowany.

Nieznany kod enum nie jest automatycznie dodawany do listy. Stan może zostać pokazany diagnostycznie jako UNKNOWN, ale nie staje się dozwoloną wartością komendy.

Programy czasu i zegar systemowy mają dodatkową walidację formatu. Read-back porównuje wartość logiczną po ponownym zdekodowaniu, a nie tylko surowy payload MQTT.

## Sterowanie w panelu

Typowy przebieg:

1. Skonfiguruj transporty i uruchom dodatek.
2. W zakładce `Sterowanie` wykonaj skan read-only.
3. Dla pozycji `supported` porównaj wartości z interfejsem falownika.
4. W trybie `dual` wybierz transport, który ma potwierdzony odczyt.
5. Włącz MQTT tylko dla potrzebnych encji.
6. Zapisz wybór i poczekaj na ponowne opublikowanie Discovery.
7. Pierwszą zmianę wykonaj z małą, odwracalną wartością i sprawdź ją na urządzeniu.

Reset albo usunięcie listy wyłącza encje i kolejkuje usunięcie ich retained Discovery. Ponowne włączenie publikuje aktualną konfigurację idempotentnie.

## Źródła mapy

Kanoniczna mapa znajduje się w `catalogs/models/deye_sg04_sg05_3ph_lv/control.yaml`. Jest budowana z przypiętej rewizji profilu Sunsynk i lokalnej nakładki korekt. Informacje o pochodzeniu i licencji są w katalogu modelu.

Obsługa na liście katalogowej nie jest dowodem zgodności z każdym firmware. Status skanu potwierdza odpowiedź transportu, ale nie potwierdza skutku zapisu.

## Granice weryfikacji

Testy automatyczne sprawdzają walidację, kodowanie, zachowanie masek, symulowany FC16, read-back, brak ponowienia i globalną blokadę. Nie potwierdzają:

- fizycznego portu USB;
- parametrów i timingu RS485;
- mapy rejestrów konkretnego firmware;
- rzeczywistego FC16 na falowniku;
- bezpieczeństwa danej nastawy dla lokalnej instalacji.

Przed użyciem encji zapisujących sprawdź dokumentację urządzenia, porównaj odczyty i potwierdź zachowanie na konkretnym falowniku.

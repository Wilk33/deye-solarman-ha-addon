# SolarMan Diagnostics 2.0.1

Jeden dodatek Home Assistant OS do lokalnego odczytu i sterowania falownikiem Deye przez SolarMan TCP, bezpośredni Modbus RTU (RS485) albo oba transporty jednocześnie.

## Trzy tryby

- `solarman-only` - włączone `solarman.enabled`, wyłączone `rs485.enabled`;
- `rs485-only` - wyłączone `solarman.enabled`, włączone `rs485.enabled`;
- `dual` - oba transporty są włączone.

W trybie `dual` transporty mają niezależne workery i interwały. Skan jest sekwencyjny: SolarMan TCP -> RS485. Każda encja wybiera dokładnie jeden obsługiwany transport i nie używa fallbacku na drugi.

## Panel i MQTT

Panel Ingress ma pełne tłumaczenia PL/EN oraz zakładki `Sensory`, `Sterowanie` i `Własne sensory`. Pokazuje status oraz opóźnienie obu transportów. Selektor transportu pojawia się tylko dla definicji obsługiwanych przez oba transporty.

Dodatek używa jednego klienta MQTT. Domyślne wartości to `client_id: solarman` i `base_topic: solarman_diagnostics`. Istniejące `unique_id` i tematy stanu pozostają wspólne niezależnie od transportu. Wspólny command topic ma postać:

```text
solarman_diagnostics/<serial_falownika>/controls/<klucz>/set
```

## Operacje diagnostyczne i zapis

Skan `Sensory`, skan `Sterowanie` i Test we `Własnych sensorach` są tylko do odczytu. Zakładka `Sterowanie` nie ma osobnego przycisku Test. Prawdziwy zapis wykonuje wyłącznie wybrana encja sterowania MQTT.

Zapis obejmuje read-before-write, walidację, pojedynczy FC16 i read-back. Po niepewnym wyniku rozpoczętego FC16 nie ma ponowienia, a wszystkie dalsze zapisy na obu transportach są globalnie blokowane do przeładowania konfiguracji albo restartu. Odczyty nadal działają.

## RS485

Metadane zawierają `uart: true`. Wartości `/dev/ttyUSB0`, 9600 8N1 i Modbus ID 1 są przykładem, który trzeba sprawdzić na konkretnym adapterze, falowniku i firmware.

## Pierwsze uruchomienie

1. Skonfiguruj co najmniej jeden transport.
2. Dla SolarMan podaj adres i numer seryjny loggera.
3. Dla RS485 wybierz rzeczywisty port szeregowy i sprawdź jego parametry.
4. Pozostaw `mqtt.use_supervisor: true`, jeśli broker udostępnia Home Assistant Supervisor.
5. Uruchom dodatek, wykonaj skan i wybierz encje MQTT.

Nowa instalacja ma pusty `default_profile`. Listy sensorów i sterowania są pobierane odpowiednio z `catalog.url` i `catalog.control_url`, walidowane i zapisywane do osobnych cache.

`detailed_logs` jest domyślnie wyłączone. Normalny log ogranicza szczegóły połączeń i pojedynczych publikacji. Pełny debug należy włączać tylko podczas diagnozy.

## Aktualizacja z 1.x

Konfiguracja `logger` wraz ze wspólną sekcją `polling` jest migrowana do `solarman`. RS485 pozostaje wyłączone, dopóki użytkownik go nie skonfiguruje. Zapisane wybory sensorów, sterowania i własnych sensorów pozostają zachowane, podobnie jak MQTT `unique_id`.

## Granice testów

Testy automatyczne nie potwierdzają fizycznego portu USB, timingu RS485, map rejestrów konkretnego firmware ani rzeczywistego FC16 falownika. Odczyty i zapisy trzeba zweryfikować na własnym urządzeniu.

Pełna instrukcja znajduje się w [DOCS.md](DOCS.md), a zasady zapisu w [CONTROL_ENTITIES.md](CONTROL_ENTITIES.md).

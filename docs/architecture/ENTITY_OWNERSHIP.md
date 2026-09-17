# Wspólna własność encji

## Koncepcja zatwierdzona przez użytkownika 2026-09-17

- Jeden identyfikator `<serial>:<component>:<key>`, jedno Discovery i zachowany `unique_id`.
- Rejestr `/share/entity_owners.json` wspólny dla aplikacji. Właściciele `solarman_tcp` i przyszły `modbus_rtu`.
- Stabilny plik `.lock` z `flock` na HAOS/Linux; zapis JSON przez plik tymczasowy i atomowe zastąpienie. Lokalny Windows używa blokady bajtowej systemu.
- Wybór MQTT, reset i usuwanie działają w sekcji krytycznej obejmującej lokalną konfigurację i rejestr. Konflikt zwraca HTTP 409 i przywraca lokalne pliki. Po awarii procesu niespójny wybór nie publikuje bez potwierdzenia właściciela; start uzgadnia rejestr z trwałą konfiguracją.
- Discovery, stan, RAW, atrybuty i usuwanie Discovery sprawdzają właściciela pod blokadą trzymaną aż do potwierdzenia publikacji przez broker. Opóźnione usunięcie jest dozwolone tylko dla nieprzypisanej encji.
- Zgodnie z korektą użytkownika stan, RAW i atrybuty pozostają wspólne, pod dotychczasowymi tematami `<base>/<serial>/...`. Komendy i dostępność transportu mają prefiks `<base>/<serial>/source/<source>/`. Komenda sterowania ponownie sprawdza właściciela bezpośrednio przed zapisem, trzymając blokadę przez zapis i read-back.
- Panel pokazuje właściciela w trzech zakładkach i wyłącza wybór zajętej encji. Konflikt pozostaje sprawdzany na serwerze.
- Źródło i nazwa aplikacji są wstrzykiwane przez punkt wejścia transportu. Rejestr nie korzysta z API HA ani z retained MQTT jako mutexu.

## Granice

Brak automatycznego wywłaszczania po zatrzymaniu aplikacji i brak TTL. Przeniesienie wymaga odznaczenia/zapisu u dotychczasowego właściciela, potem zaznaczenia/zapisu u nowego. Wspólna ścieżka, broker, prefiksy MQTT i kanoniczne klucze muszą być jednakowe. Jedna instancja danego transportu na falownik. Istniejące zewnętrzne dodatki Sunsynk nie uczestniczą w tym protokole; adapter RS485 projektu nadal nie jest gotowym dodatkiem.

Źródło kontraktu Discovery: [Home Assistant MQTT](https://www.home-assistant.io/integrations/mqtt/), konfiguracja aktualizowana na tym samym temacie, `unique_id` i `origin`.

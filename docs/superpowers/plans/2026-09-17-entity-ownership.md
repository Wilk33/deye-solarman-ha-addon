# Entity Ownership Implementation Plan

**Goal:** Zrealizować zatwierdzony wspólny rejestr encji dla rdzenia i adapterów.

**Architecture:** Rejestr z blokadą systemową, warstwa transakcji konfiguracji oraz ochrona operacji MQTT i sterowania. Wspólny temat stanu zgodnie z korektą użytkownika; osobne tematy komend, tożsamość Discovery zachowana.

**Tech Stack:** Python, standardowe flock/msvcrt, JSON, MQTT, istniejący Ingress JS.

**Spec:** `docs/architecture/ENTITY_OWNERSHIP.md`. Realizacja lokalna w bieżącym zadaniu.

## Zadania

- [x] Rejestr `packages/deye_inverter_core/ownership.py`: testy multiprocess claim, release, uszkodzony JSON i rozróżnienie serial/component. API: `EntityOwnershipRegistry(path)`, `EntityOwnership(registry,serial,source,name)`, `guard(component,key,unowned=False)`, `reconcile(desired,strict=False)`.
- [x] Koordynator `ownership_config.py`: transakcja `apply(action)` obejmująca kopie plików konfiguracji, walidację wszystkich aktywnych kluczy i rollback na HTTP 409; test braku zmian lokalnych po konflikcie. Start: uzgodnienie dotychczasowych wyborów bez przejmowania obcych encji.
- [x] `mqtt.py`, `controls.py`, `main.py`, punkt wejścia adaptera: wspólne tematy stanu, źródłowe komendy i origin, blokada przez potwierdzenie Discovery, kontrola własności przed Modbus. Test dwóch publisherów, opóźnionego remove, starej komendy po przekazaniu i stałych tematów stanu i unique_id.
- [x] `web.py`, `control_panel.js`, `custom_panel.js`: transakcje zapisów/resetów/usuwania, dane ownership i HTTP 409, etykiety właścicieli, zablokowane checkboxy. Sprawdzenie przez HTTP, w tym równoległy konflikt.
- [x] Pełne unittest, kontrole Python/JS, wygenerowanie dodatku i `package_addon.py --check`. Dokumentacja i wersja 1.3.0. Lokalnie: 93 testy OK, kontrola panelu JS OK.

Przebieg każdej zmiany zachowania: test reprodukujący brak ochrony, uruchomienie i potwierdzenie niepowodzenia, implementacja, ponowne uruchomienie. Stan fizycznego falownika nie jest zmieniany podczas tych testów.

Publikacja: commit i push na main; wynik CI jest rejestrowany w GitHub Actions dla commitu wydania.

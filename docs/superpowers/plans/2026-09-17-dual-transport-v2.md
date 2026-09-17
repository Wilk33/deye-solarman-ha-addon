# Deye Diagnostics 2.0.0 Dual Transport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Zbudować jeden dodatek 2.0.0 obsługujący jednocześnie SolarMan TCP i RS485 Modbus RTU z wyborem jednego transportu per encja.

**Architecture:** Wspólny `TransportManager` zarządza dwoma niezależnymi klientami i workerami. Skanowanie jest sekwencyjne, monitoring równoległy per transport, a MQTT i UI pozostają wspólne.

**Tech Stack:** Python 3.12, PyModbus 3.14.0, pysolarmanv5, paho-mqtt, PyYAML, JavaScript panelu Ingress, Home Assistant app schema.

**Spec:** `docs/superpowers/specs/2026-09-17-dual-transport-v2-design.md`

## Global Constraints

- Wersja dodatku: `2.0.0`.
- Jeden proces i jeden publisher MQTT.
- Jeden aktywny transport per sensor lub sterowanie.
- Brak zapisu przez drugi transport po timeout.
- Zachować istniejące `unique_id`, state topic i historię encji.
- Testy muszą powstać i zawieść przed kodem produkcyjnym.
- Parametry RS485 pozostają przykładowe do testu na fizycznym falowniku.

---

### Task 1: Modele konfiguracji i migracja 1.x

**Files:**
- Modify: `packages/deye_inverter_core/models.py`
- Modify: `packages/deye_inverter_core/config.py`
- Modify: `deye-solarman-diagnostics/config.yaml`
- Test: `tests/test_dual_transport.py`

**Interfaces:**
- Produces: `SolarmanConfig`, `Rs485Config`, `TransportPollingConfig`, `AppConfig.solarman`, `AppConfig.rs485`.

- [ ] Napisz testy konfiguracji 2.0.0, migracji `logger` i `polling`, walidacji co najmniej jednego aktywnego transportu oraz domyślnie wyłączonego RS485.
- [ ] Uruchom testy i potwierdź błąd wynikający z braku nowych modeli.
- [ ] Dodaj modele, parser zgodny wstecz oraz sekcje `solarman` i `rs485` w panelu HA.
- [ ] Uruchom testy konfiguracji i pełny zestaw regresji.

### Task 2: Adapter Modbus RTU

**Files:**
- Create: `apps/deye-solarman/src/deye_solarman_diagnostics/rs485.py`
- Modify: `deye-solarman-diagnostics/rootfs/requirements.txt`
- Modify: `deye-solarman-diagnostics/config.yaml`
- Test: `tests/test_dual_transport.py`

**Interfaces:**
- Consumes: `Rs485Config`.
- Produces: `ModbusRtuTransport` z metodami `connect`, `close`, `reconnect`, `read_holding_registers`, `write_holding_registers` i `transport_id="modbus_rtu"`.

- [ ] Napisz test adaptera z kompletnym klientem szeregowym: argumenty 8N1, `retries=0`, device ID, błędy protokołu i odczyt listy rejestrów.
- [ ] Uruchom test i potwierdź brak modułu adaptera.
- [ ] Zaimplementuj adapter oraz dodaj `pymodbus==3.14.0` i `uart: true`.
- [ ] Uruchom testy adaptera i importu pakietu.

### Task 3: TransportManager i niezależny reconnect

**Files:**
- Create: `packages/deye_inverter_core/transport_manager.py`
- Modify: `packages/deye_inverter_core/transport.py`
- Test: `tests/test_dual_transport.py`

**Interfaces:**
- Produces: `TransportManager`, `TransportSlot`, `TransportStatus`, `manager.get(id)`, `manager.available()`, `manager.run(id, operation)`.

- [ ] Napisz testy dwóch slotów, osobnych locków, opóźnień i awarii jednego transportu bez zatrzymania drugiego.
- [ ] Uruchom testy i potwierdź brak managera.
- [ ] Zaimplementuj manager bez globalnej blokady.
- [ ] Uruchom testy managera i regresję transportu SolarMan.

### Task 4: Model wyboru i skan sekwencyjny

**Files:**
- Modify: `packages/deye_inverter_core/models.py`
- Modify: `packages/deye_inverter_core/scanner.py`
- Modify: `packages/deye_inverter_core/definitions.py`
- Modify: `packages/deye_inverter_core/controls.py`
- Test: `tests/test_dual_transport.py`

**Interfaces:**
- Produces: `SensorDefinition.transport`, `SensorDefinition.transports`, `scan_transports_sequentially(...)`, wyniki `last_scan` per transport i walidację wyboru.

- [ ] Napisz przypadki: oba supported, tylko SolarMan, tylko RS485, żaden, unavailable i unsupported.
- [ ] Potwierdź oczekiwane błędy testów.
- [ ] Dodaj scalanie wyników, migrację starego `last_scan` oraz zachowanie prawidłowego wyboru użytkownika.
- [ ] Dodaj analogiczny model do sterowania i potwierdź brak zapisu podczas skanu.
- [ ] Uruchom testy skanowania i persistence.

### Task 5: Scheduler per transport

**Files:**
- Modify: `packages/deye_inverter_core/scheduler.py`
- Create: `packages/deye_inverter_core/transport_runtime.py`
- Test: `tests/test_dual_transport.py`

**Interfaces:**
- Produces: scheduler `next_due`, `due(now)`, `mark_read(key, now)` oraz worker przypisany do jednego `TransportSlot`.

- [ ] Napisz testy `read_every` 1 s przy globalnym 5 s, `read_every` 60 s, dwóch różnych częstotliwości i grupowania podobnych terminów.
- [ ] Potwierdź, że dotychczasowa pętla nie spełnia testów.
- [ ] Zaimplementuj scheduler terminowy i niezależne workery.
- [ ] Uruchom testy czasu z kontrolowanym zegarem bez `sleep`.

### Task 6: Runtime, MQTT i usunięcie EntityOwnership

**Files:**
- Modify: `packages/deye_inverter_core/main.py`
- Modify: `packages/deye_inverter_core/mqtt.py`
- Modify: `packages/deye_inverter_core/web.py`
- Delete: `packages/deye_inverter_core/ownership.py`
- Delete: `packages/deye_inverter_core/ownership_config.py`
- Test: `tests/test_dual_transport.py`
- Delete: `tests/test_ownership.py`
- Delete: `tests/test_ownership_api.py`

**Interfaces:**
- Consumes: `TransportManager`, wyniki skanu i wybór `transport`.
- Produces: jeden runtime MQTT bez registry ownership, wspólny command topic i atrybut `transport`.

- [ ] Napisz test integracyjny trybów SolarMan-only, RS485-only i dual oraz awarii jednego transportu.
- [ ] Potwierdź, że obecny runtime nie przechodzi testów.
- [ ] Przebuduj start, reconnect i panel na manager transportów.
- [ ] Usuń ownership z publikacji, zapisu konfiguracji i komend MQTT bez zmiany `unique_id`.
- [ ] Potwierdź dokładnie jeden zapis przez wybrany transport i brak fallbacku zapisu.

### Task 7: UI wyboru transportu i i18n

**Files:**
- Modify: `packages/deye_inverter_core/panel.js`
- Modify: `packages/deye_inverter_core/control_panel.js`
- Modify: `packages/deye_inverter_core/custom_panel.js`
- Modify: `packages/deye_inverter_core/web.py`
- Create: `packages/deye_inverter_core/i18n/pl.json`
- Create: `packages/deye_inverter_core/i18n/en.json`
- Create: `deye-solarman-diagnostics/translations/en.yaml`
- Modify: `deye-solarman-diagnostics/translations/pl.yaml`
- Test: `tests/test_dual_transport.py`

**Interfaces:**
- Produces: endpoint słownika, tłumaczenie PL/EN i kontrolki transportu zależne od wyników skanu.

- [ ] Napisz testy API panelu dla języka i danych obu transportów.
- [ ] Potwierdź brak endpointu i pól transportu.
- [ ] Dodaj wspólną funkcję `t(key)` i słowniki bez kopiowania panelu.
- [ ] Dodaj widok wyników obu transportów i selektor tylko dla dwóch supported.
- [ ] Uruchom testy API i statyczną walidację JavaScript.

### Task 8: Pakowanie, dokumentacja i wydanie 2.0.0

**Files:**
- Modify: `tools/package_addon.py`
- Modify: `deye-solarman-diagnostics/CHANGELOG.md`
- Modify: `deye-solarman-diagnostics/DOCS.md`
- Modify: `README.md`
- Modify: `docs/architecture/MULTI_ADDON_AND_CATALOGS.md`
- Generate: `deye-solarman-diagnostics/rootfs/usr/src/app/**`

**Interfaces:**
- Produces: samodzielny obraz HAOS 2.0.0 z kodem obu transportów.

- [ ] Zmień rewizję pakietu i MQTT origin na `2.0.0`.
- [ ] Uzupełnij migrację, konfigurację portu, ryzyko fizycznych zapisów i diagnostykę dwóch transportów.
- [ ] Wygeneruj pakiet i uruchom `tools/package_addon.py --check`.
- [ ] Uruchom wszystkie testy, `compileall`, walidację YAML, walidację JavaScript i `git diff --check`.
- [ ] Wykonaj niezależny code review, popraw uwagi i ponów pełną walidację.

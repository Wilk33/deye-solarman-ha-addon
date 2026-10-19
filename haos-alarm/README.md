# Alarm 1.0.1

Dodatek monitoruje dowolne liczbowe encje Home Assistant i uruchamia dokładnie jeden skonfigurowany rodzaj wyjścia alarmowego: audio albo GPIO Raspberry Pi 5.

## Konfiguracja monitorowania

`monitored_entities` jest listą edytowalnych wpisów. Każdy wpis zawiera:

- `entity_id` - identyfikator sensora Home Assistant;
- `name` - nazwa używana w powiadomieniach;
- `alarm_low` - opcjonalny dolny próg alarmowy;
- `warning_low` - opcjonalny dolny próg ostrzegawczy;
- `warning_high` - opcjonalny górny próg ostrzegawczy;
- `alarm_high` - opcjonalny górny próg alarmowy;
- `hysteresis` - nieujemna wartość określająca zapas wymagany do ponownego uzbrojenia czujnika po potwierdzeniu alarmu.

Puste pole wyłącza dany próg. Wpis bez żadnego progu pozostaje zapisany, ale nie jest odpytywany. Wartości `unknown`, `unavailable` oraz wartości nienumeryczne nie uruchamiają alarmu i są zapisywane w logu.

Przykład:

```yaml
monitored_entities:
  - entity_id: sensor.deye_deye_10kw_battery_temperature
    name: Temperatura baterii
    alarm_low: ""
    warning_low: ""
    warning_high: "50"
    alarm_high: "60"
    hysteresis: "5"
```

Dla strony dolnej musi zachodzić `alarm_low <= warning_low`. Dla strony górnej musi zachodzić `warning_high <= alarm_high`.

## Potwierdzenie i ponowne uzbrojenie alarmu

Po przekroczeniu progu alarmowego uruchamia się syrena lub wyjście GPIO. Przycisk `button.haos_alarm_acknowledge` potwierdza wszystkie alarmy aktywne w chwili naciśnięcia i natychmiast wyłącza wyjście alarmowe.

Potwierdzenie jest zapamiętywane oddzielnie dla każdego czujnika i dla kierunku przekroczenia:

- po alarmie górnym czujnik zostanie ponownie uzbrojony dopiero przy wartości `warning_high-hysteresis`;
- po alarmie dolnym czujnik zostanie ponownie uzbrojony dopiero przy wartości `warning_low+hysteresis`;
- jeżeli odpowiadający próg ostrzegawczy jest pusty, punktem odniesienia jest próg alarmowy;
- alarm w przeciwnym kierunku jest nowym zdarzeniem i uruchamia wyjście bez czekania na zakończenie poprzedniego cyklu.

Przykład dla `warning_high=50`, `alarm_high=60` i `hysteresis=5`:

1. Wartość rośnie z 30 do 63 - alarm się uruchamia.
2. Użytkownik naciska przycisk potwierdzenia - syrena milknie.
3. Wartości 63, 55, 50 i 46 nie uruchamiają ponownie alarmu tego czujnika.
4. Przy wartości 45 czujnik zostaje ponownie uzbrojony.
5. Kolejne osiągnięcie 60 lub więcej ponownie uruchamia alarm.

Jeżeli w czasie wyciszenia pierwszy czujnik nadal ma 63, a drugi czujnik przekroczy własny próg alarmowy, drugi czujnik normalnie uruchomi alarm.

## Powiadomienia

`notification_targets` przyjmuje listę konkretnych encji `notify`, na przykład:

```yaml
notification_targets:
  - notify.mobile_app_mateusz
```

Każde nowe ostrzeżenie lub alarm tworzy trwałe powiadomienie w Home Assistant oraz wysyła wiadomość do wszystkich skonfigurowanych odbiorców. `notify_recovery` włącza wiadomość po zakończeniu cyklu alarmowego i ponownym uzbrojeniu czujnika.

## Wyjście audio

Ustaw:

```yaml
output_mode: audio
audio_file: ""
audio_volume_percent: 95
```

Pusty `audio_file` używa wbudowanego sygnału alarmowego. Można wskazać własny plik WAV z zamontowanego katalogu `/media`, na przykład `/media/Alarm_F.wav`. Dodatek używa bezpośrednio systemowego wyjścia audio Home Assistant OS przez PulseAudio i nie wymaga encji `media_player` ani Music Assistant.

## Wyjście GPIO Raspberry Pi 5

Ustaw:

```yaml
output_mode: gpio
gpio_pin: 17
gpio_active_high: true
```

`gpio_pin` jest numerem BCM od 0 do 27. Runtime wyszukuje kontroler `pinctrl-rp1`, wyznacza jego dynamiczną bazę sysfs i przy zatrzymaniu zawsze ustawia wyjście w stanie nieaktywnym. GPIO Raspberry Pi jest wyjściem logicznym 3,3 V. Syrena, przekaźnik lub inne obciążenie wymagają właściwego stopnia wykonawczego.

## Encje MQTT

Dodatek publikuje dokładnie dwie encje przez MQTT Discovery:

- `button.haos_alarm_acknowledge` - potwierdza i wycisza alarmy aktywne w chwili naciśnięcia;
- `sensor.haos_alarm_state` - pokazuje `ok`, `warning`, `alarm`, `acknowledged` albo `unavailable`.

Szczegóły monitorowanych encji są atrybutami sensora stanu. Dla każdego wpisu zawierają bieżący poziom, wartość, informację o potwierdzeniu, stan uzbrojenia, histerezę i próg ponownego uzbrojenia. Nie tworzą dodatkowych encji MQTT.

Podczas pierwszego uruchomienia wersji 1.0.1 dodatek usuwa z MQTT Discovery starą encję `switch.haos_alarm_enabled`.

## Współpraca z Continuous Noise

Retained temat `haos_alarm/active` ma wartość `ON` tylko wtedy, gdy wyjście alarmowe rzeczywiście działa. Continuous Noise używa tego tematu do zatrzymania szumu. Po potwierdzeniu alarmu temat przechodzi na `OFF` i poprzednio wybrany szum może zostać wznowiony. Nowy alarm z innego czujnika ponownie ustawia `ON`.

## Granice weryfikacji

Testy automatyczne sprawdzają progi, histerezę, potwierdzenie i ponowne uzbrojenie per czujnik, niezależność czujników, MQTT Discovery, bezpieczny stan GPIO, manifest i zgodność pakietu. Nie potwierdzają fizycznego dźwięku, mapowania konkretnej karty audio, konkretnego obwodu GPIO ani dostarczenia powiadomienia przez zewnętrzną usługę telefonu. Te elementy wymagają testu na docelowym Home Assistant OS i Raspberry Pi 5.

## Źródła

- [Home Assistant - konfiguracja aplikacji](https://developers.home-assistant.io/docs/add-ons/configuration/)
- [Home Assistant - MQTT button](https://www.home-assistant.io/integrations/button.mqtt/)
- [Home Assistant - MQTT Discovery](https://www.home-assistant.io/integrations/mqtt/#mqtt-discovery)
- [Home Assistant - powiadomienia](https://www.home-assistant.io/integrations/notify/)
- [Home Assistant Companion - podstawowe powiadomienia](https://companion.home-assistant.io/docs/notifications/notifications-basic/)
- [Linux kernel - GPIO sysfs](https://kernel.org/doc/html/v5.19/admin-guide/gpio/sysfs.html)
- [Raspberry Pi - aktualne praktyki GPIO](https://pip-assets.raspberrypi.com/categories/685-app-notes-guides-whitepapers/documents/RP-006553-WP/A-history-of-GPIO-usage-on-Raspberry-Pi-devices-and-current-best-practices)

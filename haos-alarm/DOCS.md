# Alarm 1.0.0

Dodatek monitoruje dowolne liczbowe encje Home Assistant i uruchamia dokładnie jeden skonfigurowany rodzaj wyjścia alarmowego: audio albo GPIO Raspberry Pi 5.

## Konfiguracja monitorowania

`monitored_entities` jest listą edytowalnych wpisów. Każdy wpis zawiera:

- `entity_id` - identyfikator sensora Home Assistant;
- `name` - nazwa używana w powiadomieniach;
- `alarm_low` - opcjonalny dolny próg alarmowy;
- `warning_low` - opcjonalny dolny próg ostrzegawczy;
- `warning_high` - opcjonalny górny próg ostrzegawczy;
- `alarm_high` - opcjonalny górny próg alarmowy.

Puste pole wyłącza dany próg. Wpis bez żadnego progu pozostaje zapisany, ale nie jest odpytywany. Wartości `unknown`, `unavailable` oraz wartości nienumeryczne nie uruchamiają alarmu i są zapisywane w logu.

Przykład:

```yaml
monitored_entities:
  - entity_id: sensor.deye_deye_10kw_battery_temperature
    name: Temperatura baterii
    alarm_low: ""
    warning_low: ""
    warning_high: "45"
    alarm_high: "50"
```

Dla strony dolnej musi zachodzić `alarm_low <= warning_low`. Dla strony górnej musi zachodzić `warning_high <= alarm_high`.

## Powiadomienia

`notification_targets` przyjmuje listę konkretnych encji `notify`, na przykład:

```yaml
notification_targets:
  - notify.mobile_app_mateusz
```

Każde nowe ostrzeżenie lub alarm tworzy trwałe powiadomienie w Home Assistant oraz wysyła wiadomość do wszystkich skonfigurowanych odbiorców. `notify_recovery` włącza wiadomość o powrocie wartości do prawidłowego zakresu.

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

- `switch.haos_alarm_enabled` - włącza albo wyłącza działanie wyjścia alarmowego;
- `sensor.haos_alarm_state` - pokazuje `ok`, `warning`, `alarm`, `unavailable` albo `disabled`.

Szczegóły monitorowanych encji są atrybutami sensora stanu i nie tworzą dodatkowych encji MQTT.

## Współpraca z Continuous Noise

Retained temat `haos_alarm/active` ma wartość `ON` tylko wtedy, gdy wyjście alarmowe rzeczywiście działa. Continuous Noise używa tego tematu do zatrzymania szumu. Po wyłączeniu alarmu poprzednio wybrany szum zostaje wznowiony.

## Granice weryfikacji

Testy automatyczne sprawdzają progi, przejścia stanów, MQTT Discovery, bezpieczny stan GPIO, manifest i zgodność pakietu. Nie potwierdzają fizycznego dźwięku, mapowania konkretnej karty audio, konkretnego obwodu GPIO ani dostarczenia powiadomienia przez zewnętrzną usługę telefonu. Te elementy wymagają testu na docelowym Home Assistant OS i Raspberry Pi 5.

## Źródła

- [Home Assistant - konfiguracja aplikacji](https://contributors.home-assistant.io/apps/reference/configuration/)
- [Home Assistant - powiadomienia](https://www.home-assistant.io/integrations/notify/)
- [Home Assistant Companion - podstawowe powiadomienia](https://companion.home-assistant.io/docs/notifications/notifications-basic/)
- [Linux kernel - GPIO sysfs](https://kernel.org/doc/html/v5.19/admin-guide/gpio/sysfs.html)
- [Raspberry Pi - aktualne praktyki GPIO](https://pip-assets.raspberrypi.com/categories/685-app-notes-guides-whitepapers/documents/RP-006553-WP/A-history-of-GPIO-usage-on-Raspberry-Pi-devices-and-current-best-practices)

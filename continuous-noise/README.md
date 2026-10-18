# Continuous Noise 1.0.0

Dodatek generuje i bez końca odtwarza wybrany szum na systemowym wyjściu audio Home Assistant OS. Nie wymaga encji `media_player` ani Music Assistant.

## Konfiguracja

Lista `noises` określa przełączniki dostępne w Home Assistant:

```yaml
noises:
  - key: pink
    name: Szum różowy
    type: pink
  - key: violet
    name: Szum fioletowy
    type: violet
volume_percent: 50
```

Obsługiwane typy to:

- `white` - szum biały;
- `pink` - szum różowy;
- `brown` - szum brązowy;
- `violet` - szum fioletowy.

`key` musi być unikalny. Dla każdego wpisu dodatek publikuje jedną encję `switch` przez MQTT Discovery. Włączenie jednego szumu wyłącza wszystkie pozostałe. Wyłączenie nieaktywnego przełącznika nie zatrzymuje aktualnie odtwarzanego szumu.

## Alarm

Dodatek subskrybuje:

```yaml
alarm_coordination_topic: haos_alarm/active
alarm_availability_topic: haos_alarm/availability
```

Stan `ON` alarmu zatrzymuje audio, ale zachowuje wybór użytkownika. Po zakończeniu alarmu odtwarzanie zostaje wznowione. Gdy dodatek Alarm stanie się niedostępny, blokada jest zdejmowana, aby szum nie pozostał trwale zatrzymany po awarii.

## Audio

Pliki WAV są generowane lokalnie przy starcie i odtwarzane w pętli przez systemowy serwer PulseAudio Home Assistant OS. Dodatek nie pobiera strumienia z Internetu i nie zapisuje plików w bibliotece multimediów użytkownika.

## Granice weryfikacji

Testy automatyczne sprawdzają wzajemne wykluczanie przełączników, zatrzymanie i wznowienie przez alarm, MQTT Discovery, manifest oraz zgodność pakietu. Nie potwierdzają fizycznego dźwięku ani mapowania konkretnego urządzenia audio. Wymaga to testu na docelowym Home Assistant OS.

## Źródła

- [Home Assistant - konfiguracja aplikacji](https://contributors.home-assistant.io/apps/reference/configuration/)
- [Music Assistant Local Audio - sposób użycia lokalnego audio HAOS](https://github.com/music-assistant/local-audio-addon/blob/main/README.md)
- [PulseAudio - paplay](https://www.freedesktop.org/wiki/Software/PulseAudio/Documentation/User/CommandLine/)

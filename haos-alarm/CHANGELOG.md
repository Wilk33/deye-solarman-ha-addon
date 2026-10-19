# Changelog

## 1.0.2

- Dodano encję `number.haos_alarm_test_value` do sprawdzania ostrzeżeń, alarmów, potwierdzenia i ponownego uzbrojenia.
- Wartość testowa ma zakres od -30 do 30 oraz stałe progi -20, -10, 10 i 20 z histerezą 5.
- Dodano kontrolę istnienia skonfigurowanych encji `notify` podczas uruchamiania dodatku.
- Rozszerzono log o czytelny błąd dla nazw starszych akcji `notify.mobile_app_*` użytych zamiast encji `notify`.

## 1.0.1

- Zastąpiono globalny przełącznik wyłączenia alarmu przyciskiem potwierdzenia aktywnego alarmu.
- Potwierdzenie wycisza bieżący alarm oddzielnie dla każdego czujnika.
- Dodano konfigurowalną histerezę ponownego uzbrojenia do każdego monitorowanego czujnika.
- Inny czujnik może uruchomić alarm, gdy pierwszy pozostaje potwierdzony.
- Dodano stan acknowledged i atrybuty cyklu alarmowego.

## 1.0.0

- Dodano monitorowanie listy dowolnych encji Home Assistant.
- Dodano cztery opcjonalne progi na wpis.
- Dodano wyłączny tryb audio albo GPIO Raspberry Pi 5.
- Dodano trwałe powiadomienia i listę celów `notify`.
- Dodano dokładnie dwie encje MQTT: włączenie alarmu i stan alarmu.
- Dodano koordynację z dodatkiem Continuous Noise.

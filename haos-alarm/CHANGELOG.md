# Changelog

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

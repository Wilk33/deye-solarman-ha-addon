# Deye Solarman Diagnostics

Dodatek Home Assistant OS do diagnostycznego, lokalnego odczytu falownika Deye przez logger Solarman TCP. Publikuje wybrane odczyty przez MQTT Discovery.

Dodatek jest przeznaczony jako wolniejsza sciezka diagnostyczna i uzupelnienie bezposredniej integracji RS485, na przyklad `Sunsynk or Deye Inverter add-on (multi)`. Nie zastepuje kanalu RS485.

Wersja `0.3.2` dodaje panel Ingress Home Assistant do skanowania katalogu bezpiecznych, tylko do odczytu rejestrow telemetrycznych dla rodziny Deye SUN-*-SG04LP3 / SG05LP3. Wynik skanu nie tworzy automatycznie encji MQTT. Uzytkownik wybiera interesujace pozycje w panelu, bez pracy w terminalu.

Pelna instrukcja konfiguracji i skanowania jest w [DOCS.md](DOCS.md).

Zrodla katalogu rejestrow: [mapa SG04LP3 / SG05LP3](https://github.com/Developer089/deye-modbus-ha/blob/main/custom_components/deye_modbus/maps/sun_3ph_hybrid.yaml) oraz [mapa diagnostyczna pakietow BMS](https://gist.github.com/Lewa-Reka/9796390db54fa5b317f27bc435a2a320). Odczyty BMS oznaczone jako `candidate` wymagaja potwierdzenia wynikiem skanu na konkretnym falowniku.

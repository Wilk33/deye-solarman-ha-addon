# Deye Solarman Diagnostics

Dodatek Home Assistant OS do diagnostycznego, lokalnego odczytu falownika Deye przez logger Solarman TCP. Publikuje wybrane odczyty przez MQTT Discovery.

Dodatek jest przeznaczony jako wolniejsza sciezka diagnostyczna i uzupelnienie bezposredniej integracji RS485, na przyklad `Sunsynk or Deye Inverter add-on (multi)`. Nie zastepuje kanalu RS485.

Wersja stabilna `1.1.1` samoczynnie odtwarza zamknieta sesje Solarman TCP, publikuje temperatury w standardowej jednostce Home Assistant `°C`, synchronizuje panel Ingress z motywem Home Assistant, pokazuje HEX i ASCII oraz pobiera pelna, aktualizowalna mape rejestrow YAML z GitHub z lokalnym cache i fallbackiem w obrazie. Zapis wyboru MQTT stosuje zmiany bez restartowania kontenera dodatku. Pulpit `Wlasne sensory` umozliwia dodanie recznych definicji Modbus oraz bezpiecznych skryptow odczytujacych rejestry przez `sensor(...)` i `RAW(...)`. Numery seryjne BMS sa dekodowane per sensor z `byte_order: low_high`.

Pelna instrukcja konfiguracji i skanowania jest w [DOCS.md](DOCS.md).

Wynik przegladu podstawowych typow, skalowania i kolejnosci slow rejestrow znajduje sie w [REGISTER_TYPE_AUDIT.md](REGISTER_TYPE_AUDIT.md).

Zrodla katalogu rejestrow: [mapa SG04LP3 / SG05LP3](https://github.com/Developer089/deye-modbus-ha/blob/main/custom_components/deye_modbus/maps/sun_3ph_hybrid.yaml) oraz [mapa diagnostyczna pakietow BMS](https://gist.github.com/Lewa-Reka/9796390db54fa5b317f27bc435a2a320). Odczyty BMS oznaczone jako `candidate` wymagaja potwierdzenia wynikiem skanu na konkretnym falowniku.

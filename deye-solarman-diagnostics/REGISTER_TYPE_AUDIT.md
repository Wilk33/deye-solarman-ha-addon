# Audyt typow rejestrow

Data audytu: 2026-09-01.

## Zakres i zrodlo

Audyt obejmuje 94 definicje telemetrii falownika oraz 23 definicje na pakiet BMS z `deye_sg04_sg05_3ph_lv_catalog.yaml`. Podstawowe odczyty porownano z publiczna mapa [Developer089/deye-modbus-ha](https://github.com/Developer089/deye-modbus-ha/blob/main/custom_components/deye_modbus/maps/sun_3ph_hybrid.yaml), ktora deklaruje zgodnosc z rodzina Deye SUN-*K-SG04LP3 / SG05LP3 oraz pochodzenie z dokumentu protokolu Deye.

Mapa zewnetrzna jest zrodlem referencyjnym projektu, nie potwierdzeniem konkretnej wersji firmware lokalnego falownika. Adresy oraz znaczenie rejestrow BMS pozostaja oddzielnym obszarem kandydatow.

## Wynik

- 68 pierwotnych definicji telemetrycznych ma zgodny adres, liczbe rejestrow, signedness, mnoznik i kolejnosc slow z dotychczasowym audytem. Kolejne 26 pozycji sa kandydatami z audytu mapy i wymagaja porownania z lokalnym falownikiem przed uzyciem w automatyzacji.
- `uint16`: wszystkie jednowyrazowe wartosci bez znaku, m.in. napiecia, dodatnie prady PV, SOC, czestotliwosci, energie dobowe i stan pracy.
- `int16`: wszystkie jednowyrazowe wartosci oznaczone jako signed w mapie, m.in. prad i moc baterii, moce oraz prady sieci, moce i prady falownika, obciazenia i moc generatora.
- `uint32` z `word_order: low_high`: wszystkie osiem licznikow energii calkowitej. Pierwszy rejestr zawiera low word.
- Temperatura baterii, AC i DC: `uint16`, `multiplier: 0.1`, `offset: -100.0`. Jest to rownowazne wzorowi mapy `(raw-1000)*0.1`.
- Numery seryjne BMS: `ascii` z `byte_order: low_high`, dwa drukowalne znaki na rejestr. Dla slow `0x3530 0x3034 0x3037 0x3030 0x3145 0x3630 0x3930 0x3830` wynik to `05407000E1060908`. Kolejnosc rejestrow nie zmienia sie; odwracane sa tylko dwa bajty pojedynczego slowa.

## BMS

Pakietowe rejestry BMS `R10038-R10177` nie wystepuja w referencyjnej mapie podstawowej telemetrii. Ich typy pozostaja celowo oznaczone jako kandydaci:

- napiecie, temperatura, SOC, SOH, pojemnosc, min/max cell voltage i cykle: `uint16` z mnoznikami zapisanymi w katalogu;
- prad pakietu: `int16` z mnoznikiem `0.1`;
- MOS, alarm, fault i wersje: `hex`;
- serial: `ascii` z `byte_order: low_high`.

Skan potwierdza dostep i wartosc transportowa. Nie potwierdza samodzielnie semantyki rejestru BMS. Porownuj wartosci oznaczone `candidate` z BMS lub wyswietlaczem falownika przed wlaczeniem ich do automatyzacji.

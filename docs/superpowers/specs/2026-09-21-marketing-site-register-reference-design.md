# SolarMan Diagnostics - publiczna strona i przeglądarka definicji

Data: 2026-09-21

Status: projekt zatwierdzony w rozmowie, dokument oczekuje na końcowy przegląd przed przygotowaniem planu implementacji

## 1. Cel

Repozytorium otrzyma dwujęzyczną stronę GitHub Pages, która:

- jasno przedstawia zastosowanie i najważniejsze funkcje SolarMan Diagnostics;
- prowadzi użytkownika do instalacji, dokumentacji i kodu źródłowego;
- pokazuje telemetrię, sterowanie, dwa transporty i Własne sensory;
- udostępnia interaktywną przeglądarkę definicji rejestrów;
- automatycznie wykrywa wszystkie rodziny modeli w `catalogs/models/*`;
- nie powiela ręcznie danych z `telemetry.yaml` i `control.yaml`;
- publikuje się dopiero po przejściu walidacji dodatku, katalogów i strony.

Docelowy adres:

```text
https://wilk33.github.io/deye-solarman-ha-addon/
```

## 2. Kryteria powodzenia

Implementacja jest zakończona, gdy:

1. GitHub Pages publikuje dwujęzyczną stronę produktu.
2. Strona działa pod prefiksem `/deye-solarman-ha-addon/` i lokalnie.
3. Generator wykrywa modele bez listy nazw zapisanej w kodzie.
4. Model może zawierać telemetrię, sterowanie albo obie mapy.
5. Niepoprawny manifest, suma SHA-256 albo mapa zatrzymuje budowę.
6. Przeglądarka pozwala wyszukiwać i filtrować definicje.
7. Każda definicja ma bezpośredni adres URL.
8. Interfejs działa po polsku i angielsku.
9. Liczby modeli i definicji są generowane z katalogów.
10. Publiczne materiały nie zawierają danych prywatnych ze zrzutów.
11. Pull request buduje i testuje stronę, ale jej nie publikuje.
12. Wdrożenie z `main` jest możliwe dopiero po przejściu wszystkich kontroli.

## 3. Zakres

W zakresie są:

- statyczna strona produktu;
- interaktywna przeglądarka definicji;
- automatyczne wykrywanie katalogów modeli;
- wspólna walidacja integralności katalogów;
- dwujęzyczny interfejs PL/EN;
- bezpieczne materiały wizualne na podstawie przekazanych zrzutów;
- integracja z README i dokumentacją dodatku;
- automatyczne wdrożenie GitHub Pages;
- testy generatora, danych strony i krytycznych funkcji interfejsu.

Poza zakresem są:

- zmiany runtime dodatku;
- zmiany protokołu SolarMan, Modbus RTU albo MQTT;
- zmiany definicji rejestrów poza opcjonalnymi metadanymi prezentacyjnymi modelu;
- framework JavaScript;
- analityka, reklamy, trackery i zewnętrzne fonty;
- edycja katalogów przez publiczną stronę;
- automatyczne tłumaczenie nazw technicznych definicji.

## 4. Wybrane podejście

Strona będzie niestandardową aplikacją statyczną zbudowaną z HTML, CSS i JavaScript bez frameworka. Skrypt Python przygotuje artefakt GitHub Pages i dane katalogów.

Podejście zostało wybrane zamiast MkDocs i aplikacji SPA, ponieważ:

- daje pełną kontrolę nad prezentacją marketingową i filtrami;
- nie wprowadza ekosystemu Node.js ani nowych zależności produktu;
- pozwala leniwie ładować mapy wielu modeli;
- zachowuje prosty statyczny model wdrożenia;
- nie łączy strony marketingowej z runtime dodatku Home Assistant.

## 5. Architektura informacji

### 5.1 Strona produktu

Trasa `/` zawiera:

1. Sekcję główną opisującą lokalną komunikację z falownikiem Deye.
2. Przejścia do instalacji, definicji i repozytorium GitHub.
3. Schemat dwóch transportów prowadzących do jednego runtime i MQTT.
4. Porównanie SolarMan TCP oraz Modbus RTU przez RS485.
5. Sekcję telemetrii i dekodowania statusów.
6. Sekcję sterowania z opisem read-before-write, FC16 i read-back.
7. Sekcję Własnych sensorów oraz formuł.
8. Sekcję niezależnych katalogów telemetrii i sterowania.
9. Skróconą instrukcję instalacji.
10. Odsyłacze do dokumentacji, definicji i kodu.

### 5.2 Przeglądarka definicji

Trasa `/reference/` zawiera:

- selektor modelu;
- zakładki `Telemetria` i `Sterowanie`;
- statystyki wybranego modelu;
- wyszukiwarkę i filtry;
- sortowalną tabelę na szerokim ekranie;
- karty na ekranie wąskim;
- panel szczegółów definicji;
- odsyłacze do plików źródłowych.

Stan przeglądarki jest kodowany w URL, na przykład:

```text
/reference/?model=deye_sg04_sg05_3ph_lv&map=telemetry&q=battery#run_state
```

Adres odtwarza model, mapę, wyszukiwanie, filtry i otwartą definicję.

## 6. Wygląd i materiały

Strona zachowa wizualne powiązanie z panelem Ingress:

- ciemne tło;
- błękitny kolor nawigacji i głównych działań;
- zielony status poprawnego odczytu i online;
- pomarańczowy status diagnostyczny i ostrzeżenie;
- czerwony błąd;
- typografię techniczną dla rejestrów, RAW, masek i kluczy;
- większą typografię marketingową w nagłówkach.

Publiczne materiały wizualne powstaną jako przygotowane kopie wybranych zrzutów. Oryginalne pliki nie zostaną dodane do repozytorium. Publiczna kopia nie może zawierać adresu IP, numeru seryjnego, identyfikatora urządzenia USB, ścieżki Ingress, prywatnego logu, avatara ani panelu konta Home Assistant. Preferowane widoki to sensory, sterowanie, Własne sensory i źródła katalogów. Każdy obraz otrzyma opis alternatywny.

## 7. Dwujęzyczność

Teksty interfejsu będą przechowywane w:

```text
site/i18n/pl.json
site/i18n/en.json
```

Tłumaczone są nawigacja, tekst marketingowy, filtry, komunikaty błędów, instalacja i objaśnienia techniczne.

Dane techniczne z katalogu pozostają niezmienione, w szczególności `key`, `name`, nazwy opcji, jednostki, identyfikatory transportów i nazwy metod. Wybrany język i motyw będą zapisane lokalnie w przeglądarce.

## 8. Wykrywanie modeli

Generator przegląda bezpośrednie podkatalogi:

```text
catalogs/models/*
```

Katalog jest modelem, jeżeli zawiera `catalog-index.yaml`. Nazwy modeli nie są wpisane do generatora.

Model może zadeklarować tylko `telemetry`, tylko `control` albo obie mapy. Brak niezadeklarowanej mapy nie jest błędem.

## 9. Metadane prezentacyjne modelu

`catalog-index.yaml` może zawierać opcjonalne pola:

```text
display_name
manufacturer
model_families
```

Generator używa `display_name`, a przy jego braku `catalog_set`. Brak opcjonalnych metadanych nie blokuje modelu.

`tools/package_addon.py` zachowa te pola przez jawną listę dozwolonych metadanych podczas odświeżania sum katalogu. Runtime może je ignorować. Dodanie metadanych nie zmienia map rejestrów.

## 10. Wspólna integralność katalogów

Powstanie moduł `tools/catalog_integrity.py`, który odpowiada za:

- odczyt UTF-8;
- normalizację `CRLF`, `CR` i `LF` do `LF`;
- obliczanie SHA-256;
- rozwiązywanie ścieżek map;
- blokowanie wyjścia poza katalog modelu;
- walidację manifestu i podstawowej struktury mapy.

Z modułu korzystają `tools/package_addon.py`, `tools/build_site.py` oraz testy katalogów. Zapobiega to różnym implementacjom SHA-256 w pakowaniu dodatku i budowaniu strony.

## 11. Walidacja katalogu

Dla każdego modelu generator sprawdza:

1. `format == 1`.
2. Zgodność `catalog_set` z nazwą katalogu.
3. Poprawną strukturę `maps`.
4. Bezpieczną lokalną ścieżkę pliku mapy.
5. Istnienie zadeklarowanego pliku.
6. Zgodność SHA-256 po normalizacji linii.
7. Zgodność `map_id`.
8. Zgodność `catalog_set` mapy i indeksu.
9. Zgodność `purpose`.
10. Zgodność `writable`.
11. Poprawną listę `transports`.
12. Unikalność kluczy definicji.
13. Rejestry zapisane jako liczby całkowite.
14. Listę `sensors` dla telemetrii.
15. Listę `commands` dla sterowania.

Nieznane dodatkowe pola definicji są zachowywane w danych strony.

Błędny YAML lub JSON, niezgodna suma, niebezpieczna ścieżka, brak pliku, niezgodne identyfikatory, powtórzony klucz albo błędna podstawowa struktura mapy zatrzymują budowę. Komunikat wskazuje model, mapę, plik i niespełniony warunek.

## 12. Artefakt strony

Generator tworzy katalog roboczy `.site-dist/`:

```text
.site-dist/
  index.html
  404.html
  reference/
    index.html
  assets/
    site.css
    site.js
  generated/
    models.json
    models/
      deye_sg04_sg05_3ph_lv/
        telemetry.json
        control.json
  sitemap.xml
  robots.txt
```

W repozytorium pozostają źródła strony w `site/` oraz narzędzia `tools/build_site.py` i `tools/catalog_integrity.py`. `.site-dist/` jest ignorowany przez Git i przekazywany bezpośrednio jako artefakt GitHub Pages.

## 13. Manifest modeli

`generated/models.json` zawiera identyfikator, nazwę prezentacyjną, producenta, rodziny modeli, rewizję, dostępne mapy, transporty, liczbę definicji, sumy SHA-256, ścieżki danych i odnośniki do GitHub.

Każda mapa jest osobnym plikiem JSON. Przeglądarka ładuje tylko manifest oraz aktualnie wybraną mapę.

## 14. Prezentacja definicji

Wyszukiwarka obejmuje nazwę, klucz, numer rejestru, jednostkę, kategorię, typ, metodę sterowania, wartości enum i opisy bitów.

Filtry obejmują model, rodzaj mapy, kategorię, transport, typ danych, odczyt lub zapis, liczbę rejestrów, enum, bitmask oraz zakres stały lub dynamiczny.

Panel szczegółów pokazuje wszystkie dostępne pola definicji, w tym rejestry, mnożnik lub factor, offset, jednostkę, kolejność słów i bajtów, harmonogram, klasy Home Assistant, opcje, nieznane wartości, maskę, przesunięcie, zakres oraz metodę sterowania.

## 15. Bezpieczeństwo interfejsu

Dane katalogu są traktowane jako tekst. Interfejs:

- używa bezpiecznych operacji DOM, w tym `textContent`;
- nie wykonuje HTML z katalogu;
- nie używa `eval`;
- nie pobiera skryptów z CDN;
- nie pobiera zewnętrznych fontów;
- nie zawiera analityki ani trackerów;
- stosuje możliwą dla strony statycznej politykę Content Security Policy.

Błędy pobrania danych są prezentowane w języku interfejsu. Awaria przeglądarki definicji nie blokuje strony produktu.

## 16. GitHub Actions i Pages

Obecny workflow walidacji pozostaje bramką jakości. Zostanie rozszerzony o testy integralności wszystkich modeli, testy generatora, kontrolę składni JavaScript, zbudowanie artefaktu oraz kontrolę wymaganych plików i odnośników.

Pull request buduje i testuje stronę bez publikacji. Push do `main` po poprawnej walidacji publikuje artefakt przez:

- `actions/configure-pages@v5`;
- `actions/upload-pages-artifact@v4`;
- `actions/deploy-pages@v4`.

Job wdrożenia ma uprawnienia `contents: read`, `pages: write` i `id-token: write`. Wdrożenie używa środowiska `github-pages` i zależy od udanego jobu budowania. Źródłem Pages jest GitHub Actions. Nie powstaje gałąź `gh-pages`.

## 17. Integracja z repozytorium

README otrzyma skrócony opis produktu, link do strony, link do definicji, status CI i Pages, szybką instalację, najważniejsze funkcje, bezpieczne materiały wizualne oraz odnośniki do dokumentacji technicznej.

Strona zostanie podlinkowana z README dodatku, dokumentacji użytkownika i opisu katalogów. Adres repozytorium instalacyjnego pozostaje bez zmian.

## 18. SEO i dostępność

Strona zawiera tytuły i opisy PL/EN, canonical URL, Open Graph, metadane podglądu linku, ikonę projektu, `sitemap.xml`, `robots.txt`, `404.html` i podstawowe dane strukturalne aplikacji.

Interfejs obsługuje nawigację klawiaturą, widoczny fokus, semantyczne nagłówki, opisy alternatywne, odpowiedni kontrast, `prefers-reduced-motion` oraz ekrany telefonu, tabletu i komputera. Tabela zmienia się w karty na małym ekranie.

## 19. Testy i przegląd

Testy generatora obejmują:

- kilka modeli;
- obie mapy;
- tylko telemetrię;
- tylko sterowanie;
- zgodne sumy dla LF i CRLF;
- niezgodną sumę SHA-256;
- wyjście ścieżką poza model;
- powtórzone klucze;
- deterministyczny manifest;
- poprawne ścieżki wygenerowanych map.

Testy artefaktu obejmują komplet plików, poprawny JSON, obsługę prefiksu repozytorium, linki wewnętrzne, składnię JavaScript, zgodność statystyk i brak znanych danych prywatnych w treści tekstowej.

Weryfikacja funkcjonalna obejmuje wyszukiwanie, filtry, enum, bitmask, zakresy dynamiczne, link bezpośredni, PL/EN, widok mobilny i wdrożenie publiczne.

Kontrola błędów ma dwie tury:

1. Integralność, prywatność, bezpieczeństwo i wdrożenie.
2. Wyszukiwanie, linki, języki, urządzenia mobilne i czytelność.

Nie są wymagane testy kosmetycznych przypadków brzegowych bez wpływu na wiarygodność albo użyteczność.

## 20. Wersjonowanie

Strona nie zmienia runtime dodatku, Modbusa, MQTT ani definicji encji. Sama implementacja strony nie podbija wersji dodatku.

Opcjonalne metadane prezentacyjne indeksu nie zmieniają logicznej zawartości map rejestrów. Jeżeli implementacja ujawni konieczność zmiany zachowania instalowanego dodatku, taka zmiana zostanie wydzielona poza ten zakres.

## 21. Ryzyka i ograniczenia

- Rozwój schematu: generator waliduje wymagane pola i zachowuje nieznane pola.
- Wiele dużych modeli: manifest jest mały, a mapy są ładowane osobno.
- Różne zakończenia linii: wspólny moduł normalizuje dane przed SHA-256.
- Dane prywatne: oryginały zrzutów pozostają poza repozytorium, a kopie przechodzą kontrolę.
- Awaria Pages: strona jest oddzielona od dodatku i nie wpływa na zainstalowane instancje.

## 22. Źródła

- [Sunsynk - Sensor definitions](https://kellerza.github.io/sunsynk/reference/definitions)
- [GitHub Docs - Using custom workflows with GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)
- [GitHub Docs - Configuring a publishing source](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)
- [GitHub - actions/deploy-pages](https://github.com/actions/deploy-pages)
- [GitHub - actions/upload-pages-artifact](https://github.com/actions/upload-pages-artifact)
- [Katalogi modeli](../../../catalogs/models/README.md)
- [Architektura katalogów](../../architecture/MULTI_ADDON_AND_CATALOGS.md)
- [README projektu](../../../README.md)


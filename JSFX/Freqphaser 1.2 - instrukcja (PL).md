# Freqphaser 1.2 — instrukcja obsługi

Freqphaser to wtyczka JSFX do REAPER-a, przeznaczona do masteringu i miksu. Przenosi materiał
z kanału **Side** do kanału **Mid** w pięciu pasmach częstotliwości, z wybranym kątem fazy dla
każdego pasma. Dzięki temu dźwięki, które istnieją tylko w stereo (szerokie pogłosy, rozszerzone
syntezatory, rozstawione mikrofony), nie znikają przy odsłuchu w mono: w telefonie, w radiu, na
nagłośnieniu klubowym.

Autor: Dima Gorelik, 2026. Licencja GPL v3.

---

## 1. Instalacja

1. Skopiuj plik `Freqphaser 1.2` do folderu efektów REAPER-a:
   `Options → Show REAPER resource path…` → folder `Effects` (dowolny podfolder).
2. W przeglądarce FX kliknij prawym przyciskiem i wybierz **Rescan**.
3. Dodaj efekt **JS: Freqphaser 1.2** na ścieżkę albo na master.

Wtyczka działa na sygnale stereo (2 wejścia / 2 wyjścia).

---

## 2. Krótko o Mid i Side

Każdy sygnał stereo można zapisać jako dwie części:

- **Mid** = (L + R) / 2 — to, co jest wspólne dla obu kanałów; to słychać w mono.
- **Side** = (L − R) / 2 — różnica między kanałami; w mono **znika całkowicie**.

Freqphaser bierze część Side w wybranym paśmie i kopiuje ją albo przenosi do Mid, żeby
przetrwała sumowanie do mono.

---

## 3. Układ okna

### Górny wykres — pasma i zwrotnice

Pięć kolorowych krzywych to pięć pasm (B1–B5). Cztery kropki to **zwrotnice (crossovery)**:
domyślnie 200 Hz, 1,5 kHz, 7 kHz i 10 kHz. Kropkę przeciąga się myszą w poziomie.
Krzywe pokazują prawdziwy kształt masek; pasma zawsze sumują się do całości.

### Kolumny pasm (B1 … B5)

| Kontrolka | Co robi |
|---|---|
| **AMOUNT** | Ile materiału Side przenieść, od 0,00 do 1,00 bita (krok 0,05). |
| **PHASE** | Kąt fazy kopii wstawianej do Mid, od −180° do +180°. |
| **90** | Mały przycisk obok gałki Phase: jednym kliknięciem ustawia +90°. Świeci się, gdy faza wynosi ±90°. |
| **MOVE / FOLD / ADD** | Tryb pasma; kliknięcie przełącza kolejno MOVE → FOLD → ADD. |
| **LISTEN** | Odsłuch samego materiału Side tego pasma (tylko jedno pasmo naraz). |

### Pasek globalny

| Kontrolka | Co robi |
|---|---|
| **SLOPE** | Nachylenie zwrotnic: 12, 24, 48 lub 96 dB/okt. |
| **MONO CHECK** | Odsłuch wyniku w mono (L + R). Listen ma pierwszeństwo przed Mono Check. |

### Sekcja WIDTH

| Kontrolka | Co robi |
|---|---|
| **FOLD** | Szerokopasmowe zwężanie całego sygnału: Side → Mid pod stałym kątem +90°. |
| **MACRO / MICRO / RATIO** | Wzmocnienie pozostałego Side, bitowo dokładne (wzór RCBitRangeGain, patrz rozdział 6). |
| **Procent (np. 100%)** | Wynikowa szerokość stereo. |

### Obsługa myszą

- **Przeciąganie** w górę/w dół — zmiana wartości gałki lub pola.
- **Kółko myszy** — krok: 0,05 bita / 1° / 1 bit Macro / 1% Micro / 0,25 Ratio.
- **Prawy przycisk** — wpisanie dokładnej wartości z klawiatury (Enter zatwierdza, Esc anuluje).

---

## 4. Skala bitowa Amount — dlaczego maksimum to 1 bit

Amount liczy się wzorem **`ilość = 2^bity − 1`**:

| Amount | Ilość przeniesiona | Znaczenie |
|---|---|---|
| 0 bit | 0 | nic się nie dzieje |
| 0,25 bit | 0,19 | delikatnie |
| 0,5 bit | 0,41 | mniej więcej połowa |
| 0,75 bit | 0,68 | większość |
| **1 bit** | **1,00** | **cały materiał Side pasma** |

**1 bit to nie „+6 dB”, tylko 100% materiału Side.** Więcej przenieść się nie da: Side jest
różnicą kanałów (L − R), więc dodanie do Mid „więcej niż całego Side” może jedynie odjąć
przeciwny kanał, czyli odwrócić jego polaryzację. Dlatego skala kończy się na 1 bicie.

---

## 5. Tryby: MOVE, ADD i FOLD

### MOVE — przeniesienie (domyślny)

Wstawia kopię Side do Mid **i jednocześnie usuwa tę samą ilość z Side**. Materiał zmienia
miejsce: przestaje być „szeroki” i staje się „środkowy”.

- Przy **1 bicie** cały Side pasma ląduje w Mid: **pasmo staje się mono**.
- Obraz stereo w tym paśmie się zwęża, ale nic nie ginie przy sumowaniu do mono.
- Gdy wszystkie pięć pasm jest w MOVE na 1 bicie, cały Side zostaje usunięty.

**Używaj MOVE**, gdy chcesz, żeby pasmo brzmiało tak samo w stereo i w mono, na przykład bas
i dół środka na masterze albo szerokie, „fazujące” syntezatory.

### ADD — dodanie

Wstawia kopię Side do Mid, ale **Side zostaje nietknięty**. Szerokość stereo się nie zmienia,
a w mono pojawia się materiał, który wcześniej znikał.

- W stereo słychać przede wszystkim więcej środka w tym paśmie.
- ADD **podnosi poziom i szczyty**, zwłaszcza przy fazie bliskiej 0° lub 180°. Wtyczka celowo
  nie ma automatycznej kompensacji poziomu, więc zostaw zapas (headroom) albo ścisz sygnał
  za wtyczką.

**Używaj ADD**, gdy stereo ma zostać szerokie, a chcesz tylko „ratować” mono.

### FOLD — automatyczne przeniesienie ze stałą mocą

Tryb „bez myślenia o fazie”. Faza jest zawsze **+90°**, a ilość usuwana z Side jest liczona
automatycznie, **osobno dla każdej częstotliwości**, tak żeby **głośność pasma się nie zmieniała**:

- do Mid trafia `a`, w Side zostaje `√(1 − a²)`;
- przy żadnej wartości Amount żaden kanał się nie kasuje;
- 1 bit = pełne mono, tak samo jak w MOVE;
- na granicy z sąsiednim, nieruszanym pasmem nie powstaje dziura −3 dB.

W trybie FOLD gałka Phase nie działa (pod nią widać napis „+90 fold”).

| Amount | Do Mid | Zostaje w Side (FOLD) | Kąt mieszania |
|---|---|---|---|
| 0,25 bit | 0,19 | 0,98 | 11° |
| 0,5 bit | 0,41 | 0,91 | 24,5° |
| 0,75 bit | 0,68 | 0,73 | 43° |
| 1 bit | 1,00 | 0 | 90° (mono) |

„Kąt mieszania” to proporcja Side/Mid, **nie** ustawienie gałki Phase.

---

## 6. Faza — jaki kąt ustawić?

**Krótka odpowiedź: +90° (albo −90°), niezależnie od liczby bitów.** Do tego służy przycisk **90**.

Dlaczego? Dźwięk obecny tylko w jednym kanale po przeniesieniu ma w Mid głośność:

- tylko lewy kanał: `1 + 2a·cos φ + a²`
- tylko prawy kanał: `1 − 2a·cos φ + a²`

Składnik `2a·cos φ` przechyla obraz: jeden kanał rośnie, drugi jest odejmowany. Znika on
**tylko przy cos φ = 0, czyli przy ±90°**, i to dla każdej wartości Amount.

| Faza | Efekt przy MOVE 1 bit |
|---|---|
| **0°** | Prawy kanał pasma znika w środku, zostaje lewy. |
| **180°** | Lewy kanał pasma znika w środku, zostaje prawy. |
| **±90°** | Oba kanały trafiają do środka po równo, nic się nie kasuje. |
| inne | Stopniowe przechylenie w lewo lub w prawo. |

Kąty 0° i 180° mają sens tylko wtedy, gdy **celowo** chcesz przesunąć pasmo w lewo lub w prawo.

**MOVE na ±90° a FOLD:** w MOVE przy wartościach pośrednich (np. 0,5 bita) energia
materiału Side w paśmie spada o mniej więcej 3 dB, bo z Side ubywa tyle samo, ile przybywa w Mid. FOLD usuwa z Side
mniej i trzyma stałą głośność. Przy 1 bicie oba tryby dają to samo.

---

## 7. Sekcja WIDTH

- **FOLD (bit)**: jak tryb FOLD, ale szerokopasmowo, dla całego sygnału naraz, na stałym kącie
  +90°. 0 bit = bez zmian, 1 bit = całość w mono.
- **MACRO / MICRO / RATIO**: wzmocnienie pozostałego Side według wzoru RCBit:
  `wzmocnienie = 2^((Macro + Micro% / 100) × Ratio)`.
  Macro +1 przy Ratio 1 = Side ×2 (+6,02 dB); Macro −1 = Side ×0,5.
  To zwykłe wzmocnienie M/S. Nie przenosi niczego do Mid, tylko poszerza lub zwęża obraz.

---

## 8. Typowe zastosowania

**Bezpieczne mono na masterze**
1. Wszystkie pasma w **MOVE**, faza **90** (przycisk).
2. B1 (bas, poniżej 200 Hz): 1 bit, bo bas powinien być mono.
3. Pozostałe pasma podnoś stopniowo, sprawdzając **MONO CHECK**, aż w mono nic nie znika.

**Zachowanie szerokości z ratowaniem mono**
1. Pasmo w **ADD**, faza 90.
2. Ustaw Amount do momentu, w którym przy MONO CHECK wraca brakujący materiał.
3. Sprawdź szczyty na wyjściu.

**Najprościej: FOLD**
1. Pasmo w **FOLD**.
2. Kręć tylko Amount: głośność pasma zostaje stała, o fazę nie trzeba się martwić.

**Diagnostyka**: **LISTEN** na paśmie pokazuje, co w nim jest w Side, czyli co zniknie w mono.

---

## 9. Ważne informacje techniczne

- **Opóźnienie (PDC)**: silnik liniowo-fazowy zgłasza 18 432 próbki, czyli ok. 418 ms przy
  44,1 kHz, 384 ms przy 48 kHz i 192 ms przy 96 kHz. REAPER kompensuje to automatycznie;
  przy nagrywaniu przez tę wtyczkę odsłuch będzie opóźniony.
- **Płynne zmiany**: każda zmiana parametru jest przejściem 50 ms między dwoma jądrami filtra,
  bez trzasków, także podczas automatyki.
- **Brak Output Trim**: po trybie ADD poziom może wzrosnąć, więc ścisz sygnał za wtyczką.
- **Wąskie pasmo 7–10 kHz** przy łagodnym nachyleniu nie osiąga pełnej jedności w środku; jeśli
  to pasmo ma działać „na całość”, wybierz 48 albo 96 dB/okt.

---

## 10. Co nowego w 1.2

- Nowy tryb pasma **FOLD**: przeniesienie ze stałą mocą na +90°, liczone dla każdej
  częstotliwości osobno.
- Przycisk **90** przy każdej gałce Phase.
- **MOVE jest domyślnym trybem** (w 1.1 domyślny był ADD).
- Numery parametrów się nie zmieniły; parametr Mode ma po prostu trzecią wartość (Fold).

# RCBitNova V1.6 — instrukcja obsługi

**RCBitNova** to bitowy, dynamiczny korektor M/S dla REAPERA (JSFX). Ma osiem pasm, dynamikę
w dwóch trybach, filtry górno- i dolnoprzepustowe w fazie minimalnej albo liniowej oraz analizator
widma z kontrolą zgodności mono.

Autor: Dima Gorelik. Licencja: GPL.

---

## Spis treści

1. [Instalacja](#1-instalacja)
2. [Logika bitowa — najważniejsza rzecz w tej wtyczce](#2-logika-bitowa)
3. [Mapa okna](#3-mapa-okna)
4. [Pasma korektora](#4-pasma-korektora)
5. [Obsługa myszą i klawiaturą](#5-obsługa-myszą-i-klawiaturą)
6. [Dynamika: tryb A i tryb B](#6-dynamika-tryb-a-i-tryb-b)
7. [Filtry HP i LP, faza, rozdzielczość](#7-filtry-hp-i-lp)
8. [Analizator widma](#8-analizator-widma)
9. [Opóźnienie (PDC) i obciążenie procesora](#9-opóźnienie-i-procesor)
10. [Przepisy — typowe zastosowania](#10-przepisy)
11. [Ograniczenia i rzeczy, o których trzeba wiedzieć](#11-ograniczenia)
12. [Wszystkie parametry](#12-wszystkie-parametry)

---

## 1. Instalacja

1. Skopiuj plik `RCBitNova V1.6` do folderu efektów REAPERA:
   - macOS: `~/Library/Application Support/REAPER/Effects/`
   - Windows: `%APPDATA%\REAPER\Effects\`
2. W przeglądarce FX odśwież listę (F5) i wyszukaj **`JS: RCBitNova V1.6`**.

Starsze wersje (V1.0 … V1.5) mogą zostać obok — każda wersja to osobny plik i osobna wtyczka,
więc stare projekty otwierają się bez zmian.

**Ważne przy aktualizacji pliku.** REAPER **nie wczytuje ponownie** pliku JSFX dla instancji, które
już istnieją w otwartym projekcie. Jeżeli podmienisz plik, stare instancje dalej wykonują poprzednią
wersję kodu, dopóki ich nie zresetujesz (offline → online) albo nie otworzysz projektu na nowo.
Objaw: „działa dopiero po resecie”.

---

## 2. Logika bitowa

Wszystkie wzmocnienia w RCBitNova wyrażone są w **bitach**, nie w decybelach:

> **1 bit = 6,0206 dB = dokładnie dwukrotna zmiana amplitudy.**

Wzmocnienie pasma liczy się tak:

```
wzmocnienie = 2 ^ ((Macro + Micro / 100) × Bit Ratio)
```

| Macro | Micro | Bit Ratio | Wynik |
|---|---|---|---|
| −1 | 0 | 1 | dokładnie **½** amplitudy (−6,02 dB) |
| +1 | 0 | 1 | dokładnie **2×** |
| −1 | 0 | 0,5 | dokładnie **1/√2** (−3,01 dB) |
| −2 | 0 | 1 | dokładnie **¼** |
| 0 | −50 | 1 | pół bitu w dół (−3,01 dB) |

**Dlaczego bity.** Przy całkowitym `Macro` i `Bit Ratio = 1` wzmocnienie jest **dokładną potęgą
dwójki**. W arytmetyce zmiennoprzecinkowej mnożenie przez potęgę dwójki zmienia tylko wykładnik
i **nie wprowadza żadnego błędu zaokrąglenia** — sygnał przechodzi bit w bit. Wzmocnienie
„−6 dB” liczone z decybeli jest zawsze trochę niedokładne.

- **Macro** — całe bity, od −16 do +16. To jest główna gałka.
- **Micro** — ułamek bitu w procentach, od −100 do +100 (krok 0,1 %). Do precyzyjnych korekt;
  przestaje być potęgą dwójki.
- **Bit Ratio** — mnożnik całości, od 0 do 3. `0,5` daje półbity, `2` — podwójne kroki.

Ta sama logika obowiązuje w progach dynamiki (`Soft Ceiling`, `Hard Ceiling` — w bitach poniżej
0 dBFS) i na wyjściu (`Output Macro / Micro`).

---

## 3. Mapa okna

```
┌──────────────────────────────────────────────────────────────────────────┐
│   [HP 20]  [LP 20000]  [Phase: Min]  [HP res: Norm]  [LP res: Norm]       │ ← górny pasek, rząd 1
│            [Analyzer: Off] [Dom: Mid] [Tilt: 4.5]   [Peak: Off]           │ ← rząd 2: analizator
│                                                                          │
│  +4 ┤                         ●                                           │
│   0 ┤ ■──○──────────○────────/ \──────────○──────────○─────────■          │ ← krzywa EQ (±4 bity)
│  −4 ┤                                                                     │   ● ○ pasma, ■ HP/LP
├──────────────────────────────────────────────────────────────────────────┤
│ [Freq 100] [Macro 0] [Micro 0.0] [Ratio 1.00] [Q 0.707] [QChar 0.000]     │ ← pola wybranego pasma
│  B1 B2 B3 B4 B5 B6 B7 B8                                                  │ ← wybór pasma
│  B1 [Dyn] [EQ|Split] [S] Soft 1.00  [H] Hard 0.00                         │ ← panel dynamiki,
│  …                                                                        │   jeden wiersz na pasmo
└──────────────────────────────────────────────────────────────────────────┘
```

- **Krzywa EQ** — biała linia, skala **±4 bity** wokół środka. Pokazuje sumę wszystkich pasm
  i filtrów.
- **Kółka** — pasma. Pełne = włączone, puste = wyłączone.
- **Kwadraty** na linii zera — uchwyty filtrów HP (lewy) i LP (prawy).
- **Górny pasek** — globalne przełączniki filtrów (rząd 1) i analizatora (rząd 2).
- **Pola** pod wykresem — wartości wybranego pasma, edytowalne.
- **Panel dynamiki** — jeden wiersz na pasmo. Przycisk **`B1` … `B8` na początku wiersza**
  rozwija kartę z resztą ustawień pasma (Stereo, Attack, Release, Micro progów); ponowny klik ją
  zwija.

W bardzo małym oknie chowają się pasek wyboru pasm, drugi rząd górnego paska (analizator)
i panel dynamiki — pierwszy rząd górnego paska i wykres zostają.

---

## 4. Pasma korektora

Osiem pasm, B1–B8. Domyślnie włączone jest tylko **B1**. Domyślne częstotliwości:

| B1 | B2 | B3 | B4 | B5 | B6 | B7 | B8 |
|---|---|---|---|---|---|---|---|
| 100 | 1000 | 3000 | 10 000 | 150 | 700 | 5000 | 15 000 Hz |

Każde pasmo ma:

| Parametr | Zakres | Opis |
|---|---|---|
| **Enable** | Off / On | Włączenie pasma. Wyłączone pasmo nie zużywa procesora. |
| **Type** | Bell / Low Shelf / High Shelf | Dzwon albo półka. |
| **Freq** | 20 – 20 000 Hz | Częstotliwość środkowa lub graniczna. |
| **Q** | 0,1 – 10 | Szerokość dzwonu. Większe Q = węższy. |
| **Macro** | −16 … +16 bitów | Wzmocnienie w całych bitach. |
| **Micro** | −100 … +100 % bitu | Dokładne dostrojenie. |
| **Bit Ratio** | 0 – 3 | Mnożnik wzmocnienia (zob. rozdz. 2). |
| **Placement** | Both / Mid / Side / Left / Right | Na czym pasmo działa. |
| **Q Character** | 0 – 1 | 0 = stałe Q, 1 = Q proporcjonalne (zwęża się przy większym wzmocnieniu, jak w analogu). |

**Placement** to jedna z najważniejszych funkcji: każde pasmo może działać na obu kanałach,
tylko na środku (Mid), tylko na bokach (Side) albo tylko na lewym lub prawym kanale. Dzięki temu
w jednej instancji można np. podbić środek wokalu w Mid i jednocześnie przyciąć syczenie
w Side.

---

## 5. Obsługa myszą i klawiaturą

### Pasma (kółka na wykresie)

| Gest | Co zmienia |
|---|---|
| **Klik** w wyłączone pasmo | włącza je |
| **Przeciąganie w poziomie** | częstotliwość (Freq), po skali logarytmicznej |
| **Przeciąganie w pionie** | Macro — całe bity, jeden bit na ok. 24 piksele |
| **Shift** + przeciąganie w pionie | Bit Ratio, krokami 0,05 |
| **Alt** + przeciąganie w pionie | Q |
| **Kółko myszy** nad pasmem | Q (z Cmd/Ctrl — drobniej) |
| **Prawy klik** | menu: włącz/wyłącz, typ, placement, Q Character |

**Wyłączanie pasma** — prawym klikiem, pierwsza pozycja menu. Lewy klik tylko włącza, bo lewy klik
na włączonym paśmie rozpoczyna przeciąganie.

Modyfikator (Shift, Alt) czytany jest **w chwili naciśnięcia** i obowiązuje do końca gestu. Jeden
gest zawsze zmienia dokładnie jeden parametr.

### Filtry (kwadraty na linii zera)

| Gest | Co zmienia |
|---|---|
| **Przeciąganie w poziomie** | częstotliwość odcięcia |
| **Shift** + przeciąganie w pionie | rezonans |
| **Prawy klik** | menu: nachylenie (slope) i placement |

### Pola liczbowe

- **Klik** w pole — fokus, potem wpisz cyfry i zatwierdź **Enter**. **Escape** anuluje.
- **Przeciąganie** w pionie zmienia wartość. W polach HP i LP prawo jest logarytmiczne:
  ok. 120 pikseli na oktawę.
- Podwójny klik **nie** ma osobnej funkcji.

### Przyciski górnego paska

Klik przełącza albo przechodzi do następnej wartości (`Dom`, `Tilt`). Prawy klik na `Peak`
kasuje zapamiętane szczyty.

Przyciski i pola paska **nigdy** nie włączają ani nie łapią pasma, które leży pod nimi na wykresie.

---

## 6. Dynamika: tryb A i tryb B

Każde pasmo może działać dynamicznie: włącz **Dyn** w jego wierszu panelu dynamiki.

Przełącznik **EQ | Split** wybiera tryb:

### Tryb A — Dynamic EQ („EQ”)

Kiedy sygnał w paśmie przekracza próg, ten sam dzwon (albo półka) **dynamicznie przycina**
pasmo o wielkość przekroczenia. Statyczne wzmocnienie pasma i dynamiczne cięcie są od siebie
niezależne.

- Gładki, czysty fazowo, muzyczny — styl TDR Nova.
- **Nie jest bitowy**: redukcja jest płynną wartością zmiennoprzecinkową.
- **Nie gwarantuje** sufitu. Nakładające się pasma, faza i dekodowanie M/S mogą go przekroczyć.
- Przy bardzo krótkim ataku generuje **aliasing** (zmierzony: −56 … −71 dB przy ataku 0,05 ms)
  i intermodulację. **Atak 5 ms lub dłuższy** trzyma aliasing poniżej −65 dB — o tym trzeba
  pamiętać zwłaszcza przy de-essingu.

### Tryb B — Band-Split („Split”)

Pasmo jest **wycinane** z sygnału, ograniczane jako osobny sygnał prawdziwą logiką
RCBitLimiter / RCBitBrickwall i **dokładnie składane z powrotem**. Wszystko poza pasmem przechodzi
nietknięte.

- **Bitowy**: sufity to dokładne potęgi dwójki.
- Bardzo czysty: aliasing −124 … −141 dB. Nie potrzebuje nadpróbkowania.
- **Ma lookahead** (zob. niżej) i dodaje opóźnienie.
- **Gwarancja dotyczy wkładu wyciętego pasma**, a nie sumy na wyjściu — inne pasma i dekodowanie
  M/S dodają się do niego.

Jeżeli ciągłe „jeżdżenie” zmiennoprzecinkowym wzmocnieniem w trybie A brzmi sztucznie albo
martwo — przełącz pasmo na tryb B.

### Progi: Soft i Hard

| Parametr | Zakres | Znaczenie |
|---|---|---|
| **S** (Soft) | Off / On | łagodny próg z obwiednią |
| **Soft Ceiling** | 0 – 16 bitów poniżej 0 dBFS (+ Micro) | `1,00` = −6,02 dBFS |
| **H** (Hard) | Off / On | natychmiastowy próg, działa po Soft |
| **Hard Ceiling** | 0 – 16 bitów poniżej 0 dBFS (+ Micro) | |
| **Attack** | 0,05 – 50 ms | |
| **Release** | 1 – 500 ms | |

**Soft** podąża za obwiednią w stylu RCBitLimiter i może chwilowo przekroczyć próg. **Hard**
reaguje natychmiast; w trybie B jest to bitowy „ostatni policjant” — twarde przycięcie pasma do
sufitu.

### Stereo dynamiki (tylko przy Placement = Both)

| Tryb | Działanie |
|---|---|
| **Linked** | jeden detektor na oba kanały, ta sama redukcja |
| **Dual L/R** | lewy i prawy kanał osobno |
| **Dual M/S** | środek i boki osobno |

### Lookahead (tylko tryb B)

`Lookahead (ms, Mode B)` — **globalny**, od 0,1 do 10 ms, domyślnie 2 ms. Detektor widzi szczyt,
zanim ten dotrze do wyjścia. Dodaje dokładnie tyle opóźnienia.

Parametr **nie ma pokrętła w oknie wtyczki** — jest na liście `Param` i można go wynieść na panel
ścieżki.

W V1.6 długość lookahead **nie wpływa już na obciążenie procesora** (zob. rozdz. 9), więc można
swobodnie używać 10 ms.

### Dynamika półek

Dla półek detektor patrzy na obszar półki: dla High Shelf — na górę, dla Low Shelf — na dół
(filtr Q 0,7071, −3 dB na częstotliwości granicznej). Detektor Low Shelf **reaguje na składową
stałą (DC)** — to zamierzone, dobrze sprawdza się do poskramiania dudnienia, ale sygnał z offsetem
DC będzie go uruchamiał.

---

## 7. Filtry HP i LP

Dwa osobne filtry: górnoprzepustowy (HP) i dolnoprzepustowy (LP). Działają **przed** pasmami EQ.

| Parametr | Zakres | Opis |
|---|---|---|
| **Slope** | Off / 12 / 24 / 36 / 48 / 96 dB/okt / **FIR Brick** | nachylenie |
| **Freq** | 20 – 24 000 Hz | odcięcie |
| **Resonance** | 0 – 1 | dzwon rezonansowy na odcięciu (Q = 2). `0` = dokładnie wyłączony |
| **Placement** | Both / Mid / Side / Left / Right | jak w pasmach |

Zakres do **24 kHz** jest potrzebny przy 96 kHz: można np. ustawić ostry LP na 21,5 kHz przed
konwersją do 44,1 kHz.

### Faza: Min albo Linear

Przycisk **`Phase`** w górnym pasku.

- **Min** — klasyczne filtry Butterwortha (kaskada SVF), **zero opóźnienia**.
- **Linear** — filtry splotowe w fazie liniowej, **bez przesunięcia fazy**, kosztem opóźnienia.

**FIR Brick działa wyłącznie w fazie Linear.** W fazie Min nie robi nic — taki ustawiony filtr
jest wtedy po prostu wyłączony.

Zmiana fazy w czasie odtwarzania powoduje **krótkie wyciszenie**: wyjście wygasza się w 5 ms,
czeka, aż nowe filtry będą gotowe, i wraca. Bez trzasku, ale słychać przerwę. Najwygodniej
przełączać fazę przy zatrzymanym transporcie — wtedy zmiana jest natychmiastowa.

### Rozdzielczość: Normal albo High (tylko Linear)

`HP res` i `LP res` — osobno dla każdego filtra. To długość jądra FIR: 8192 albo 32 768 próbek.

Filtr FIR ma pasmo przejściowe o mniej więcej **stałej szerokości w hercach**, a nie w oktawach.
Dlatego przy niskich częstotliwościach krótkie jądro **nie może być strome**:

- HP 43 Hz, **Normal** — przejście szerokie na ok. **1,65 oktawy**.
- HP 43 Hz, **High** — przejście na ok. **0,37 oktawy**.

**Krzywa na wykresie w fazie Linear pokazuje filtr rzeczywiście zrealizowany**, a nie
idealny. Jeżeli niski HP w Linear/Normal rysuje się łagodnie — to prawda, a nie błąd. Potrzebujesz
stromego niskiego HP w fazie liniowej? Ustaw `HP res: High`.

---

## 8. Analizator widma

Włącza go przycisk **`Analyzer`** w drugim rzędzie górnego paska. Domyślnie jest wyłączony.

Analizator nic nie dodaje do toru audio: wtyczka z włączonym analizatorem daje na wyjściu
**dokładnie te same próbki**, co bez niego (sprawdzone testem zerowym, bit w bit). Całe liczenie
odbywa się w wątku graficznym — kiedy okno jest zamknięte, analizator nie kosztuje nic.

### Co widać

- **Szara** wypełniona krzywa — sygnał **na wejściu** wtyczki.
- **Zielona** — sygnał **na wyjściu**.
- Skala widma: **−20 … +2 bity** (−120 … +12 dBFS) na całą wysokość wykresu, rysowana od dołu.
  Krzywa EQ ma osobną skalę (±4 bity, od środka) — to dwie różne skale i dwa różne kształty.

Analizator rysuje tylko, kiedy płynie dźwięk. Po zatrzymaniu i zmianie domeny wykres jest pusty,
dopóki nie wznowisz odtwarzania — to zamierzone, a nie zawieszenie.

### Domena: przycisk `Dom`

| Domena | Szara krzywa | Zielona krzywa |
|---|---|---|
| **Mid** | środek wejścia | środek wyjścia |
| **Side** | boki wejścia | boki wyjścia |
| **Left** | lewy kanał wejścia | lewy kanał wyjścia |
| **Right** | prawy kanał wejścia | prawy kanał wyjścia |
| **M/S** | **środek wyjścia** | **boki wyjścia** |

Przy każdej zmianie domeny wykres na chwilę znika i zapełnia się od nowa — żeby nigdy nie
mieszać dwóch różnych sygnałów na jednym obrazku.

### Tryb M/S i kolor czerwony — kontrola zgodności mono

W domenie **M/S** każda kolumna, w której **boki są głośniejsze od środka**, rysowana jest
na czerwono:

| Warunek | Kolor |
|---|---|
| Side ≤ Mid | zielony |
| Side > Mid | ciemnoczerwony |
| Side > Mid o ponad 1 bit | jaskrawoczerwony |

Czerwień to ostrzeżenie: w tej częstotliwości przy sumowaniu do mono sygnał może osłabnąć albo
zniknąć.

Dwa zabezpieczenia: kolumna barwi się tylko powyżej **−16 bitów** (przy samym dnie skali różnice
to szum arytmetyki), a zmiana koloru ma **histerezę 0,1 bitu**, żeby kolumny nie migotały na
granicy.

**Sprawdzone:** przy sygnale zsumowanym do mono przed wtyczką żadna kolumna nie robi się czerwona
na żadnym poziomie.

**Uwaga — rozdzielczość jest celowo drobna.** Inne analizatory (np. SPAN) wygładzają widmo,
zwykle o 1/6 oktawy, i wąskie miejsca, gdzie boki chwilowo przewyższają środek, giną w średniej.
RCBitNova pokazuje je świadomie. Oba obrazy są prawdziwe, tylko w różnej skali: gładki obraz jest
w SPAN, a ten pokazuje to, czego gładki obraz nie widać.

### Tilt i Peak

- **`Tilt`** — nachylenie wykresu: 0, 3 albo **4,5 dB na oktawę** (domyślnie), obrót wokół 1 kHz.
  Przy 4,5 dB/okt muzyka o naturalnym widmie wygląda mniej więcej płasko.
- **`Peak`** — zapamiętuje najwyższą wartość w każdej kolumnie (cienka linia nad wypełnieniem).
  **Prawy klik** na przycisku kasuje szczyty. Zmiana domeny też je kasuje. Start transportu —
  **nie**.

### Ograniczenia analizatora

- Powyżej częstotliwości Nyquista (np. powyżej 22,05 kHz przy 44,1 kHz) wykres jest **pusty** —
  tam nie ma czego pokazać.
- Poniżej ok. 1,5 kHz rozdzielczość ograniczona jest szerokością prążka FFT (11,7 Hz przy 96 kHz),
  nie szerokością piksela — wąski ton nisko rysuje się trochę szerzej.

---

## 9. Opóźnienie i procesor

### Opóźnienie (PDC)

REAPER kompensuje je automatycznie. Źródła opóźnienia:

| Ustawienie | Opóźnienie w próbkach | przy 96 kHz | przy 48 kHz |
|---|---|---|---|
| Phase **Min**, bez trybu B | 0 | 0 | 0 |
| Tryb B, lookahead 2 ms | 2 ms | 2 ms | 2 ms |
| Phase **Linear**, oba filtry Normal | 12 288 | 128 ms | 256 ms |
| Linear, jeden High, drugi Normal | 24 576 | 256 ms | 512 ms |
| Linear, oba High | 36 864 | 384 ms | 768 ms |

W fazie Linear liczą się **oba** filtry, nawet jeśli jeden ma `Slope: Off`.

Do nagrywania na żywo albo monitoringu przez wtyczkę używaj fazy **Min**.

### Procesor

Zmierzone na żywo przy 96 kHz, osiem pasm w trybie B, okno zamknięte:

| Lookahead | V1.5 | **V1.6** |
|---|---|---|
| 0,1 ms | 2,8 % | 2,6 % |
| 2 ms | 9,6 % | 2,6 % |
| 10 ms | **50 %** | **3,0 %** |

W V1.5 koszt rósł liniowo z długością lookahead. W V1.6 detektor szczytu działa na kolejce
monotonicznej i jego koszt nie zależy od długości okna — przy tym daje **bit w bit ten sam wynik**.

Dodatkowo kosztują: faza Linear (oba filtry splotowe), rozdzielczość High oraz otwarte okno
z włączonym analizatorem.

---

## 10. Przepisy

### Zgodność mono w miksie

1. `Analyzer: On`, `Dom: M/S`.
2. Puść fragment. Czerwone kolumny = tam boki przewyższają środek.
3. Jasnoczerwone pasy w dole pasma (bas, stopa) to zwykle problem do naprawienia.
4. Naprawa: pasmo z `Placement: Side` i ujemnym `Macro` na tej częstotliwości albo HP na `Side`.

### Ciasny dół w bokach

`HP Slope: 24`, `HP Freq: 120`, `HP Placement: Side`. Bas w środku zostaje nietknięty, a dół
w bokach znika.

### Ostry LP przed konwersją 96 → 44,1 kHz

`Phase: Linear`, `LP Slope: FIR Brick`, `LP Freq: 21500`, `LP res: High`. Sprawdź analizatorem,
że powyżej 22 kHz nic nie zostało (zanim włączysz filtr, zobacz, że coś tam było).

### Poskromienie rezonansu w bitowy sposób

Pasmo na częstotliwości rezonansu, `Dyn: On`, tryb **Split**, `Soft` z sufitem np. `2,00`
(−12 dBFS w paśmie), `Hard` o pół bitu wyżej. Wszystko poza pasmem przechodzi nietknięte.

### De-essing

Pasmo High Shelf albo dzwon na 6–8 kHz, `Placement: Mid` (albo `Both`), `Dyn: On`.

- Tryb **A** — gładko, ale **atak ≥ 5 ms**, inaczej aliasing.
- Tryb **B** — bitowo i czysto, z lookahead.

---

## 11. Ograniczenia

- **Tryb A nie jest bitowy** i przy krótkim ataku aliasuje (rozdz. 6). Tryb B jest bitowy.
- **Gwarancja trybu B dotyczy wyciętego pasma**, nie sumy na wyjściu.
- **FIR Brick nie działa w fazie Min.**
- **Zmiana fazy podczas odtwarzania** daje krótką przerwę w dźwięku.
- **Po podmianie pliku** istniejące instancje działają na starym kodzie do resetu (rozdz. 1).
- **Brak sidechainu** — świadomie. Sidechain w trybie A byłby zwykłym dynamicznym EQ z płynnym
  wzmocnieniem, jakich jest wiele. Celem tej wtyczki jest dokładność bitowa.
- **Lookahead** nie ma pokrętła w oknie — jest na liście `Param`.
- Przy lewej krawędzi niektórych krzywych HP w fazie Linear widać krótką pionową kreskę. To tylko
  rysunek (na dźwięk nie wpływa) i jeszcze nie jest wyjaśniona.

---

## 12. Wszystkie parametry

Numery suwaków są stałe między wersjami — dlatego zapisane projekty i automatyka się nie
przesuwają. Nowe parametry dostają zawsze numery wyższe od istniejących.

### Globalne

| # | Parametr | Zakres | Domyślnie |
|---|---|---|---|
| 1 | Bypass | Off / On | Off |
| 2 | Output Macro (bits) | −16 … +16 | 0 |
| 3 | Output Micro (% bit) | −100 … +100 | 0 |
| 4 | Lookahead (ms, Mode B) | 0,1 … 10 | 2 |
| 246 | Panel: open dynamics card | 0 … 8 | 0 |

### Pasmo (wzór dla B1; numery pozostałych pasm w liście `Param`)

| Parametr | Zakres | Domyślnie |
|---|---|---|
| Enable | Off / On | B1: On, reszta: Off |
| Type | Bell / Low Shelf / High Shelf | Bell |
| Freq | 20 … 20 000 Hz | zob. rozdz. 4 |
| Q | 0,1 … 10 | 0,707 |
| Macro (bits) | −16 … +16 | 0 |
| Micro (% bit) | −100 … +100 | 0 |
| Bit Ratio | 0 … 3 | 1 |
| Placement | Both / Mid / Side / Left / Right | Both |
| Q Character | 0 … 1 | 0 |
| Dyn | Off / On | Off |
| Dyn Stereo (Both only) | Linked / Dual L/R / Dual M/S | Linked |
| Soft Ceiling Macro (bits below 0) | 0 … 16 | 1 |
| Soft Ceiling Micro (% bit) | −100 … +100 | 0 |
| Attack (ms) | 0,05 … 50 | 1 |
| Release (ms) | 1 … 500 | 80 |
| Dyn Mode | A Dynamic EQ / B Band-Split | A |
| Soft | Off / On | On |
| Hard | Off / On | Off |
| Hard Ceiling Macro (bits below 0) | 0 … 16 | 0 |
| Hard Ceiling Micro (% bit) | −100 … +100 | 0 |

### Filtry i faza

| # | Parametr | Zakres | Domyślnie |
|---|---|---|---|
| 131 | HP Slope | Off / 12 / 24 / 36 / 48 / 96 / FIR Brick | Off |
| 132 | HP Freq (Hz) | 20 … 24 000 | 20 |
| 133 | HP Resonance | 0 … 1 | 0 |
| 134 | HP Placement | Both / Mid / Side / Left / Right | Both |
| 135 | LP Slope | Off / 12 / 24 / 36 / 48 / 96 / FIR Brick | Off |
| 136 | LP Freq (Hz) | 20 … 24 000 | 20 000 |
| 137 | LP Resonance | 0 … 1 | 0 |
| 138 | LP Placement | Both / Mid / Side / Left / Right | Both |
| 140 | Phase | Min / Linear | Min |
| 141 | HP Resolution (Linear only) | Normal / High | Normal |
| 142 | LP Resolution (Linear only) | Normal / High | Normal |

### Analizator (nowe w V1.6)

| # | Parametr | Zakres | Domyślnie |
|---|---|---|---|
| 247 | Analyzer | Off / On | Off |
| 248 | Analyzer Domain | Mid / Side / Left / Right / M/S | Mid |
| 249 | Analyzer Tilt (dB/oct) | 0 / 3 / 4,5 | 4,5 |
| 250 | Analyzer Peak Hold | Off / On | Off |

---

*RCBitNova V1.6, październik 2026.*

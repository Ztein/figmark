# T-001: Vektorgrafik-diagram missas helt

**Status:** Closed — fixad 2026-05-20 via approach F (PyMuPDF drawing-clustering)
**Prioritet:** HIGH — kärnfunktionalitet trasig för dokument med diagram
**Upptäckt:** 2026-05-20 vid manuell körning mot `penningpolitisk-rapport-mars-2026.pdf`

## Resolution

Implementerat i [src/diagrams.py](../../src/diagrams.py). Pipelinen detekterar nu
diagram-regioner via fyra-stegs algoritm:
1. Filtrera drawings (storlek + sidbakgrund)
2. Union-find clustering på spatial proximity (MERGE_DISTANCE=3)
3. Y-gap-split: dela klusters med interna lucker > 40 px (separerar staplade diagram)
4. Text-expansion: utöka bbox för att fånga axel-titlar och källrader, begränsad
   av andra kluster så de inte smälter ihop

Konfigurerbart via `diagrams:`-sektionen i [config.yaml](../../config.yaml).

Live-test: [tests/test_pipeline.py::test_pipeline_diagrams_extracted_from_penningpolitisk](../../tests/test_pipeline.py)
verifierar att 4 diagram extraheras från sida 11 + 68 av penningpolitiska rapporten,
med svenska syntolkningar som nämner axlar, prognoser och serier.

## Symptom

Körning mot Riksbankens penningpolitiska rapport (72 sidor, fullproppad med diagram) producerade **3 syntolkningar** — alla av omslagsgrafik och baksidesfält. Noll diagram syntolkades trots att rapportens innehåll i princip ÄR diagram.

```
Syntolkar 3 bild(er) via google/gemma-4-31B-it …
  sida 1: page-001-img-01.jpeg → API
  sida 1: page-001-img-02.jpeg → API
  sida 72: page-072-img-01.png → API
```

## Rotorsak

[src/images.py](../../src/images.py) använder `page.get_images(full=True)` + `doc.extract_image(xref)`. Det API:t returnerar bara **inbäddade raster-bilder** (JPEG/PNG-bytes lagrade som XObjects i PDF:en).

Riksbankens diagram är **vektorgrafik** (PDF path/draw-commands) — sannolikt exporterade från matplotlib/R/d3 till PDF där varje kurva, axel och text blir individuella path-instruktioner. Inspektion bekräftar:

```
Raster-bilder totalt:    10  (varav 7 är <50x50 dekorativa ikoner)
Vektor-drawings totalt:  4583
Sidor med drawings:      65 / 72
```

Top 10 sidor efter drawing-antal:
```
Sida 71: 236   Sida 69: 211   Sida 68: 206   Sida 70: 190
Sida 11: 174   Sida 66: 174   Sida 10: 165   Sida 45: 156
Sida 35: 145   Sida 14: 128
```

Dessa sidor innehåller alla diagram.

## Effekt

Pipelinen är effektivt obrukbar för alla dokument med diagram — vilket är de flesta myndighetsrapporter, ekonomiska rapporter, vetenskapliga artiklar med figurer (utöver inbäddade fotografier), forskningsöversikter etc. Det är fel zonen i en tillgänglighetspipeline: huvudfallet vi vill stödja är just rapporter med visuell datapresentation som behöver beskrivas.

## Åtgärdsalternativ

### Alternativ 1: Rendera klustrade drawing-regioner som bilder
Använd `page.get_drawings()`, gruppera överlappande/närliggande bounding boxes till klusters, rendera varje kluster-region via `page.get_pixmap(clip=bbox)`, skicka till Gemma.

- ✅ Behåller positionsinformation (vi vet var diagrammet sitter → korrekt inklippning)
- ✅ Skiljer flera diagram på samma sida
- ❌ Kluster-algoritm måste implementeras och tunas
- ❌ Drawings för tabell-linjer och text-dekoration blir falsk-positiva

### Alternativ 2: Heuristisk full-sid-rendering vid hög drawing-densitet
Om en sida har många drawings (tröskel: t.ex. > 50), rendera **hela sidan** som bild och skicka till Gemma med prompt "syntolka alla diagram, grafer och kartor på denna sida". Lågdensitets-sidor (tabellbordrar etc.) hoppas över.

- ✅ Enkel att implementera
- ✅ Robust mot falska positiver (kluster-detektion behövs inte)
- ❌ En sida = en syntolkning. Om sidan har 4 separata diagram blandas de i en text
- ❌ Förlorar positionsinformation per diagram
- ❌ Dyrare: ett API-anrop per diagram-sida (uppskattning för Riksbank-rapport: ~30 anrop)

### Alternativ 3: Hybrid — Alt 2 som default, opt-in Alt 1 senare
Börja med Alt 2 (snabbt att leverera värde). Migrera till Alt 1 om/när vi behöver per-diagram-precision.

- ✅ Levererar funktion idag
- ✅ Begränsad teknisk skuld om vi sen vill ha precision
- ❌ Tillfälligt sämre kvalitet på precision

### Alternativ 4: Kombinera raster + drawing-detektion
Behåll nuvarande raster-extraktion. Lägg till drawing-rendering. På sidor med BÅDE inbäddade raster-bilder OCH drawings: rendera båda, dubbletter undvikas med bbox-overlap-check.

- ✅ Hanterar mixade dokument naturligt
- ❌ Komplexitet växer
- ❌ Bbox-overlap-check är fiddly

## Rekommendation

**Alternativ 3 (Hybrid)**, börja med Alt 2. Skäl: pipelinen behöver fungera för diagram NU. Per-diagram-precision är trevligt men "syntolkning av hela sidan" som en text-block är fortfarande betydligt bättre än ingenting för tillgänglighetsändamål. Migrationen till Alt 1 senare kan göras inkrementellt.

## Acceptanskriterier

- [ ] `penningpolitisk-rapport-mars-2026.pdf` producerar minst 20 syntolkningar (rough proxy för "vi fångar diagram")
- [ ] `full_text.txt` innehåller `[Bild: …]`-block som referrerar till diagrams innehåll, inte bara omslag
- [ ] Tröskeln för "sida räknas som diagram-sida" är konfigurerbar i `config.yaml`
- [ ] Pentland-PDF (textartikel utan diagram) producerar fortfarande ~2 syntolkningar (regression-skydd)
- [ ] Live-test som verifierar minst en diagram-syntolkning är genomförd och svensk

## Förslag på config-fält
```yaml
diagrams:
  # När en sida har minst så här många drawing-operations behandlas den som diagram-sida
  drawings_threshold: 50
  # DPI och kvalitet för rendering av diagram-sidor (skickas till Gemma)
  render_dpi: 200
  jpeg_quality: 85
  # Separat prompt för diagram (annars används description.prompt)
  prompt: |
    Du ska syntolka diagram, grafer och kartor i denna PDF-sida för
    användare som behöver beskrivande text. Formulera på myndighetssvenska.
    Beskriv vad varje diagram visar, vilka axlar och enheter som används,
    och de viktigaste trenderna eller observationerna. Om sidan har flera
    diagram, beskriv varje för sig.
```

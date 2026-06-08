# PDF-parser med syntolkning

Tar en PDF och producerar en sammanhängande textversion där varje bild har ersatts av en AI-genererad syntolkning på myndighetssvenska.

## Principer

- **Fail loudly** — inga tysta fallbacks. När pipelinen byter strategi (t.ex. Tesseract → Gemma-OCR) skriks det ut med tydliga `!!!`-banners.
- **Kör på riktigt** — testerna körs som default mot riktiga Berget-API:t. Mockning används bara för isolerade unit-tester av intern logik.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Systemberoenden (för OCR av skannade PDF:er):

```bash
brew install tesseract tesseract-lang
```

Fyll i din Berget.ai-nyckel i `.env`:

```bash
# .env finns redan — öppna och ersätt placeholdern
BERGET_API_KEY=sk-din-riktiga-nyckel-här
```

## Användning

```bash
source .venv/bin/activate
python -m src.main path/to/document.pdf
```

Resultatet hamnar i `output/<pdf-namn>/`:

- `images/` — alla extraherade bilder
- `descriptions/` — en `.txt` per bild med syntolkning
- `raw_text.txt` — endast text, inga syntolkningar
- `full_text.txt` — text med syntolkningar inklippta där bilderna satt

## Tester

```bash
# Allt inklusive live-tester mot Berget (kostar några kronor, tar några minuter)
.venv/bin/python -m pytest

# Bara snabba unit-tester (ingen API-trafik)
.venv/bin/python -m pytest -m "not live"

# Bara live-pipeline-tester
.venv/bin/python -m pytest -m "live"
```

Live-testerna failar med ett tydligt skrik-meddelande om `BERGET_API_KEY` är en placeholder.

## Konfiguration

Allt utöver API-nyckeln styrs av `config.yaml`:

- `api.model` — vilken modell hos Berget som ska användas
- `description.prompt` — prompten för bild-syntolkning
- `diagrams.*` — diagram-detektion via vektorgrafik-clustering + diagram-specifik prompt
- `concurrency.max_workers` — antal samtidiga API-anrop (default 4)
- `ocr.*` — OCR-trösklar för Tesseract och fallback
- `scanned_detection.min_avg_chars_per_page` — när hela PDF:en ska behandlas som skannad

## Återkörning

Bildbeskrivningar cachas på disk. Andra körningen av samma PDF anropar inte API:et för bilder som redan har en `.txt`.

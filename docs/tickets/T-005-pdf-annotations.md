# T-005: Skriv in syntolkningar som text-annotations i PDF:en

**Status:** Closed — implementerad TDD-stil 2026-05-20
**Prioritet:** Medium — MVP-tillgänglighet
**Önskad:** 2026-05-20

## Symptom / motivering

Vi producerar idag en `full_text.txt` med syntolkningarna inklippta. För användare som faktiskt vill läsa PDF:en (inte en textfil) är detta extra arbete. Lägger vi in syntolkningarna som annotations direkt i en kopia av PDF:en så har skärmläsare något att läsa och seende får synliga popup-noter.

## Vad som byggs

- Ny modul `src/annotate.py` med `annotate_pdf(source, target, items)`
- Varje syntolkning blir en text-annotation (`page.add_text_annot`) på bildens/diagrammets position
- Annotation-`title` markerar om det är "Bild" eller "Diagram"
- `--annotate-pdf` flagga i CLI producerar `output/<pdf>/<pdf>_annoterad.pdf`

## Acceptanskriterier

- [ ] Modulen är TDD-skriven (tester före implementation)
- [ ] Test: output-PDF har en annotation per bild + diagram
- [ ] Test: annotation-contents matchar syntolkningen byte-för-byte
- [ ] Test: annotation-position ligger ovanpå källbildens bbox
- [ ] Test: annoterad PDF kan öppnas och pärsas av PyMuPDF
- [ ] Live-test: penningpolitiska rapporten producerar annoterad PDF med rätt antal annotations
- [ ] CLI: `--annotate-pdf` flagga, default av

# T-004: Tagged PDF / PDF/UA — riktig tillgänglighet via structure tree

**Status:** Open
**Prioritet:** Medium — bygger ovanpå T-005 (annotation-MVP)
**Önskad:** 2026-05-20

## Symptom / motivering

T-005 (text-annotations) ger syntolkningarna en synlig och läsbar form i PDF:en, men det är inte "riktig" tillgänglighet enligt PDF/UA-standarden. Skärmläsare som följer standarden förlitar sig på **structure tree** — varje bild ska vara ett `<Figure>`-element med ett `/Alt`-attribut. Annotations är ett komplement, inte ersättning.

## Krav

- Källans PDF "promoteras" till tagged PDF om den inte redan är det
- Varje extraherad bild/diagram blir ett `<Figure>`-element i structure tree
- `/Alt` på varje Figure innehåller syntolkningen
- Reading order respekteras (Figure-elementen ligger på rätt plats i text-flow:n)
- Output validerar mot PDF/UA-checker (t.ex. PAC, veraPDF)

## Åtgärdsalternativ

### Alternativ 1: pikepdf + manuell structure tree
Lägg till `pikepdf` som dependency. Använd dess Pdf-objektgraf-API för att bygga `/StructTreeRoot`, `/ParentTree`, och Figure-noder. Mycket arbete men full kontroll.

### Alternativ 2: använd ett färdigt verktyg som postprocess
Använd `pdfua-tool` eller liknande (om det finns) som CLI-process efter vår pipeline. Outsourcing av komplexiteten.

### Alternativ 3: hybrid annotations + StructTreeRoot-stub
Behåll annotations (T-005) som primär informationsbärare. Lägg till en minimal StructTreeRoot som bara binder samman annotations till "figure"-roles. Inte full PDF/UA men närmare.

## Rekommendation

**Alternativ 1 (pikepdf).** Är det "rätta" sättet enligt standard. Skalar till framtida features som heading-tags och språk-attribut.

## Acceptanskriterier

- [ ] `--tagged-pdf` flagg som producerar `<pdf>_tagged.pdf`
- [ ] PAC eller veraPDF accepterar outputten som PDF/UA-konform (åtminstone för Figure-elementen)
- [ ] VoiceOver/NVDA läser upp syntolkningen när användaren navigerar till bilden
- [ ] Live-test som validerar structure tree-existens på en känd PDF

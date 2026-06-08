# T-006: Skicka text-kontext runt bilden med vid syntolkning

**Status:** Closed — TDD-implementerad 2026-05-20 (alternativ 1: fast antal ord)
**Prioritet:** Medium — höjer kvaliteten på syntolkningarna märkbart
**Önskad:** 2026-05-20

## Symptom / motivering

Idag får Gemma bara bilden + prompten. Modellen vet inte vad PDF:en handlar om. För ett diagram i en penningpolitisk rapport ser den linjer och siffror, men har ingen aning om att det handlar om KPIF-prognoser specifikt eller från vilket scenario. Tolkningen blir generisk istället för domänspecifik.

Konkret exempel: ett diagram med två linjer kring 2026-2029 kan vara *vad som helst* (BNP, inflation, ränta, arbetslöshet). Texten ovanför bilden brukar säga "Diagram 1.3: Inflation enligt KPIF-måttet, prognos vs utfall" — om vi skickar med den ledtråden hade modellen direkt kunnat skriva korrekt syntolkning utan att gissa.

## Vad som ska byggas

- Innan varje bild/diagram skickas till Gemma — samla N ord text **före** och M ord **efter** ur PDF:en
- Kontexten hämtas ur PDF:ens reading order (text-block sorterade på y,x — vi har det redan)
- Vid sidgräns: hoppa till föregående/nästa sida om vi inte fyllt kvoten
- Hoppa över andra bild/diagram-block — vi vill ha text, inte placeholders
- Kontexten formateras tydligt i prompten så modellen vet vad som är kontext vs uppgift

## Konfiguration

Nya required-fält enligt vår "inga defaults i koden"-policy:

```yaml
context:
  enabled: true
  words_before: 100
  words_after: 100
```

## Åtgärdsalternativ

### Alternativ 1: Fast antal ord före/efter
Räkna ord linjärt — `text.split()` ger antal ord, backa N TextBlocks-värda ord. Förutsägbar token-kostnad.

- ✅ Enkelt, robust
- ✅ Konfigurerbar gräns
- ❌ Kan klippa mitt i mening

### Alternativ 2: Hela paragrafer/stycken
Hela TextBlocks-grupper, inga halverade meningar. Mer naturligt språk i prompten.

- ✅ Bättre språklig kvalitet i kontexten
- ❌ Varierande storlek — vissa stycken är 500 ord, andra 10
- ❌ Svårare att förutse token-kostnad

### Alternativ 3: Hela sidans text
Skicka allt text på samma sida som bilden. Inga avstånd-beräkningar.

- ✅ Enklast att implementera
- ❌ Diagram-tunga sidor → kontexten innehåller andra diagrams' text → distraherar modellen
- ❌ Dyrt på text-tunga sidor

### Alternativ 4: Hybrid — paragraphs men capped på N ord
Plocka hela stycken upp till en cap (säg 150 ord) — sluta vid ordkvot men runda av till styckesgräns.

- ✅ Kombinerar A:s förutsägbarhet med B:s språkkvalitet
- ❌ Mer kod

## Rekommendation

**Alternativ 1** som MVP. Enkel ord-räkning är robust och förutsägbar. Vi kan upgrade till Alternativ 4 senare om vi märker att kontexten klipper hänsynslöst.

## Acceptanskriterier

- [ ] `context.enabled`, `context.words_before`, `context.words_after` är required i config.yaml
- [ ] TDD: unit-tester för `get_text_context_around(pages, page_num, bbox, words_before, words_after)`
  - Bild i mitten av en sida → kontext från samma sida
  - Bild högst upp på sidan → hoppar till föregående sida
  - Bild längst ner → hoppar till nästa sida
  - Bild på första sidan → tom `before`
  - Bild på sista sidan → tom `after`
  - Sida med bara bilder → backar tills text hittas
- [ ] Prompten visar tydligt vad som är kontext med rubriker som
      `[Textsammanhang före bilden]\n...\n[Textsammanhang efter bilden]\n...\n[Uppgift]\n...`
- [ ] Live-test mot ett verkligt fall där kontexten gör skillnad
      (jämför syntolkning av samma diagram med/utan kontext)
- [ ] CLI-loggar visar antal ord kontext som faktiskt skickades per anrop

## Saker att tänka på

- **Token-kostnad**: 100 ord ≈ 130 tokens på svenska. 100 före + 100 efter = ~260 extra tokens per anrop.
  Det är hanterbart. Med 30 anrop totalt ≈ 8000 extra tokens. Marginell kostnad.
- **Cache-invalidation**: Idag cachar vi syntolkningar per bildfil. Om vi ändrar context-config så
  returneras gammal cache utan kontext. Antingen:
  a) Dokumentera att man måste rensa `output/<pdf>/descriptions/` vid context-config-ändring
  b) Hash:a prompt+context-config in i cache-filnamnet (mer arbete, värt det?)
  → Förmodligen (a) som MVP, (b) som egen ticket om det visar sig vara ett problem.
- **Ord-räkning på svenska**: `.split()` är bra nog. Inga special-tecken eller binding-streck att hantera.
- **Tabeller**: PDF:ens "text" inkluderar ibland tabellinnehåll. Det blir lite brus i kontexten men inte
  något stort problem — modellen kan filtrera bort.

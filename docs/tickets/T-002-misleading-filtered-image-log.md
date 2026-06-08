# T-002: Loggen säger "N bildblock" men förklarar inte varför 0 sparas

**Status:** Open
**Prioritet:** Low — kosmetiskt, men förvirrande vid diagnostik

## Symptom

Vid körning mot `penningpolitisk-rapport-mars-2026.pdf` visar loggen:

```
Sida 44/72
  → 8 textblock, 4 bildblock (referenser)
  → 0 bild(er) sparade

Sida 60/72
  → 9 textblock, 9 bildblock (referenser)
  → 0 bild(er) sparade
```

"4 bildblock detekterade, 0 sparade" får det att låta som en bugg. Användaren upptäckte detta vid diagnostik och rapporterade det som möjlig kandidat till T-001.

## Rotorsak

Bildblocken är 10×10 px dekorativa ikoner (förmodligen rasterized bullet-markers eller fotnotsmarkörer). [src/images.py](../../src/images.py) filtrerar bort allt under `cfg.images.min_width` / `min_height` (default 50). Filtret är korrekt — vi vill inte syntolka 10×10-ikoner. Men loggen säger ingenting om att filtrering skedde.

## Effekt

- Vilseledande vid diagnostik — ser ut som en bugg trots att det är förväntat beteende
- Försvårar att skilja "filtrerat bort" från "extraktion failade"

## Åtgärdsalternativ

### Alternativ 1: Lägg till filtreringscount i loggen
```
Sida 44/72
  → 8 textblock, 4 bildblock (referenser)
  → 0 bild(er) sparade (4 filtrerade: alla < 50x50)
```

Kräver att `extract_images_from_page` returnerar både `kept` och `skipped` listor, eller åtminstone en räknare.

### Alternativ 2: Logga bara på debug-nivå
Strunta i den detaljerade per-sid-loggen och visa bara den slutgiltiga sammanfattningen. Ger renare default-output men sämre diagnostik.

### Alternativ 3: Strukturerad log-utgång (JSON via flag)
För scriptning/automation. Overkill för denna ticket.

## Rekommendation

**Alternativ 1.** Liten kodändring, stort förklaringsvärde.

## Acceptanskriterier

- [ ] Vid filtrering visas anledning + antal i loggen
- [ ] Pentland-PDF (inga filtrerade bilder) visar samma logg som idag
- [ ] Ingen ändring i exit codes eller output-artefakter

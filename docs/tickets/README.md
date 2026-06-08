# Tickets

Öppna fel och förbättringar för pdf-parsern. Numreras `T-NNN`.

| ID | Status | Prioritet | Rubrik |
|---|---|---|---|
| [T-001](T-001-vector-diagrams-missed.md) | **Closed** | HIGH | Vektorgrafik-diagram missas helt — pipeline ser bara raster-bilder |
| [T-002](T-002-misleading-filtered-image-log.md) | Open | Low | Loggen säger "N bildblock" men förklarar inte varför 0 sparas |
| [T-003](T-003-parallel-image-description.md) | **Closed** | Medium | Parallell bearbetning av bild- och diagram-syntolkningar med snygg CLI |
| [T-004](T-004-tagged-pdf-pdfua.md) | Open | Medium | Tagged PDF / PDF/UA via pikepdf — riktig tillgänglighet via structure tree |
| [T-005](T-005-pdf-annotations.md) | **Closed** | Medium | Skriv in syntolkningar som text-annotations i PDF:en (MVP-tillgänglighet) |
| [T-006](T-006-text-context-around-images.md) | **Closed** | Medium | Skicka text-kontext runt bilden (100 ord före/efter) till syntolkningen |

## Hur en ticket skrivs
- Rubrik som beskriver symptom, inte lösning
- **Symptom**: vad observerades, med konkret repro
- **Rotorsak**: vad är det egentliga problemet
- **Effekt**: vem märker det och hur
- **Åtgärdsalternativ**: numrerade lösningsvägar med trade-offs — inte en redan-vald lösning
- **Acceptanskriterier**: hur vi vet att ticketen är klar

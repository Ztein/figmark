# T-003: Parallell bearbetning av bild- och diagram-syntolkningar

**Status:** Closed — implementerat 2026-05-20 via ThreadPoolExecutor + rich Live-vy
**Prioritet:** Medium — tidsvinst, inte funktionsfix
**Önskad:** 2026-05-20

## Resolution

Implementerat i [src/parallel.py](../../src/parallel.py). Pipelinen samlar nu
cache-misses från både bild- och diagram-syntolkningar i en lista av `Job` och
skickar till en ThreadPoolExecutor med konfigurerbar parallellism.

CLI bygger en `rich.Live`-vy som visar:
- Header-rad med progressbar, procent, klara/totalt, förlöpt tid, ETA
- Tabell över pågående anrop med löpande sekund-timer
- Tabell över de 5 senaste klara med körtid
- Slut-sammanfattning med snittid och uppmätt speedup

Konfigurerbar via `concurrency.max_workers` (default 4) i [config.yaml](../../config.yaml).

Verifierat live: [test_pipeline_determinism_workers_1_vs_4](../../tests/test_pipeline.py)
kör samma mini-PDF två gånger (1 worker + 4 workers) och verifierar att
`full_text.txt` är identisk byte-för-byte.

## Symptom / motivering

Körning mot `penningpolitisk-rapport-mars-2026.pdf` (~30 bilder+diagram) tar 3-5 minuter. Varje API-anrop till Gemma är 5-15 sekunder. Anropen körs sekventiellt — varje anrop blockerar tills föregående är klar — fast nästan all tid är I/O-vänta. Med rimlig parallellism kan vi få tiden ned till ~1 minut.

```
Nuvarande:  [###] [###] [###] [###] [###] [###]  → 30 * 8s = 4 min
Parallellt: [###]  → max 8s * (30/N) batchar
            [###]
            [###]
            [###]
```

CLI-utdata är dessutom enformig idag (`sida X: filename → API`), det blir inte mycket snyggare när det kommer 30 rader i följd.

## Krav

1. **Konfigurerbart antal samtidiga API-anrop** via `config.yaml`. Default rimligt — kanske 4 eller 6 — så vi inte träffar Bergets rate-limits oavsiktligt.
2. **Gäller både bilder OCH diagram** — en gemensam parallell pool för alla `describe_image` och `describe_diagram`-anrop.
3. **Snygg CLI-vy** under körning: progressbar, antal klara/totalt, vilka som körs just nu, eta. Inte spammig.
4. **Cache fortsätter funka** — om alla beskrivningar redan är cachade ska parallellism inte slå på alls.
5. **Fail loudly** — om en arbetare failar ska felet rapporteras tydligt med vilken bild/diagram det gällde. Helst avbryta hela körningen så vi inte tappar fel i bruset.
6. **Output deterministisk** — `raw_text.txt` och `full_text.txt` ska se identiska ut oavsett worker-antal eller exekveringsordning.

## Åtgärdsalternativ

### Alternativ 1: ThreadPoolExecutor + tqdm
`concurrent.futures.ThreadPoolExecutor` med N workers, `tqdm.tqdm` för progressbar.

- ✅ Enkelt — OpenAI SDK är thread-safe (HTTP-anrop)
- ✅ tqdm är minimal, välbeprövad, integrerar bra
- ✅ Befintlig retry-logik i `describe.py` och `diagrams.py` fungerar oförändrat
- ❌ tqdm-output är funktionell men inte "wow-snyggt"

### Alternativ 2: ThreadPoolExecutor + rich
`rich.progress` för avancerad progress-vy med live-uppdaterad tabell ("3 körs nu: bild X, diagram Y, ...").

- ✅ Snyggast i CLI — färger, live-tabell, eta, spinner
- ✅ Samma underliggande threading som Alt 1
- ❌ Adderar `rich` som dependency (~1 MB)
- ❌ Lite mer kod för att sätta upp Progress + Task per anrop

### Alternativ 3: asyncio + httpx + AsyncOpenAI
Full async pipeline. Lägg om `describe_image`, `describe_diagram`, `main.run` till async.

- ✅ Mer "modern Python"
- ✅ Skalar bra om vi i framtiden vill ha ännu fler samtidiga
- ❌ Stor refactor — main.run, tester, allt blir async
- ❌ ThreadPool räcker gott för I/O-bundet med dussintal anrop
- ❌ Komplicerar testkoden onödigt

### Alternativ 4: Behåll sekventiellt
- ✅ Ingen kod ändras
- ❌ Slö för stora dokument

## Rekommendation

**Alternativ 2 (ThreadPoolExecutor + rich).** Snyggt CLI är ett uttalat krav. Rich är industri-standard för CLI-UI i Python, väl underhållet, och inte stort. Threading räcker för I/O-bundet arbete med ~30-50 samtidiga anrop.

## Förslag på config-fält

```yaml
concurrency:
  # Antal samtidiga API-anrop för syntolkning. Berget tål typiskt 4-8 utan att
  # rate-limita. Sätt högre på egen risk.
  max_workers: 4
  # Avbryt hela körningen vid första fel (alternativet är att samla felen och
  # rapportera i slutet — men "fail loudly" säger avbryt).
  fail_fast: true
```

## Förslag på CLI-vy

```
Syntolkar 30 bilder och diagram via google/gemma-4-31B-it
Förlöpt: 0:01:23 • Återstår: ~0:00:42

[#############-------]  60%   18/30 klara   4 kör nu

  ↻ sida 11 diagram 2     8.4s
  ↻ sida 14 diagram 1     6.1s
  ↻ sida 35 bild 01       3.2s
  ↻ sida 68 diagram 1     0.7s

  ✓ sida  1 bild 01       4.2s
  ✓ sida  1 bild 02       5.7s
  ✓ sida 11 diagram 1     7.8s
  ...
```

**Detaljer:**
- **Förlöpt tid**: stigande räknare från start av syntolknings-fasen, formaterad `H:MM:SS`
- **Återstår** (ETA): beräknad från genomsnittlig tid per klart anrop × återstående anrop, justerad för max_workers
- **Procent klart**: stor och tydlig i progressbar-raden, både som procent och `klara/totalt`
- **Aktiva anrop**: lista med rullande sekund-timer per pågående anrop (så man ser vilka som hängt sig)
- **Klara anrop**: scrollas i botten med faktisk körtid per anrop
- Live-uppdatering med rich.Live så hela bilden uppdateras i samma område — inte spammar nya rader

När alla klara, en slut-sammanfattning:
```
Klart på 0:01:42. 30 anrop, snittid 4.5s/anrop, total API-tid 2:15 (sekventiellt skulle tagit ~2:15).
```

## Acceptanskriterier

- [ ] `concurrency.max_workers` i `config.yaml`, default 4
- [ ] Penningpolitiska rapporten kör minst 2× snabbare med max_workers=4 (uppmätt jämfört mot 1 worker)
- [ ] Live-test verifierar att slutoutput är identisk för max_workers=1 och max_workers=4 (samma `full_text.txt` byte-för-byte efter sortering)
- [ ] CLI visar progressbar med procent + klara/totalt
- [ ] CLI visar förlöpt tid (timer från start) + uppskattat återstående (ETA)
- [ ] CLI visar lista över pågående anrop med individuell sekund-timer
- [ ] Slut-sammanfattning med total tid, snittid per anrop, och total API-tid (sekventiell jämförelse)
- [ ] Fel i en worker triggrar tydligt fail-loudly-meddelande och avbryter resten
- [ ] Cache-vägen aktiveras före worker-startup om alla beskrivningar redan finns på disk
- [ ] README uppdaterad

## Saker att tänka på vid implementation

- **Rate-limits:** Berget kan returnera 429. Befintlig retry-logik i `describe.py` med exponentiell backoff fungerar oförändrat — men med flera samtidiga anrop kan vi triggra fler 429:er. Watch.
- **Tråd-vs-process-säkerhet:** `OpenAI`-klienten är thread-safe (HTTP-anrop via httpx, ingen delad muterbar state). Bra.
- **Cache-race:** Två trådar kan starta på samma bild om båda kollar cache före. För korrekthet inget problem (deterministisk filskrivning, kommer skrivas över med samma resultat). Vi bör läsa cache **innan** vi schemalägger en worker så vi sparar ett anrop.
- **Output-ordning:** `assemble()` körs efter alla anrop är klara, så slutfilen är deterministisk även om anropen klara i annan ordning.

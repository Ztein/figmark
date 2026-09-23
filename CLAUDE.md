# figmark — working agreement

`docs/PRD.md` is the spec. Read it before changing anything.

- **One phase at a time.** Work only inside the current phase (see the PRD's
  plan). No code for the next phase before its decision point has been passed
  and Joel has said yes.
- **Every phase ends in a number.** A change is kept only if the measurement it
  belongs to says it helps. No feature without its measurement.
- **Small on purpose.** Docling carries formats and layout; our own code is
  figure interpretation, the yardstick and the API. If our code grows past a few
  thousand lines, stop and ask.
- **Locally runnable models only.** Everything must be able to run offline on a
  48 GB Mac. During development a hosted endpoint may serve the same models, for
  speed — never a model that cannot run locally.
- **Public repo.** Nothing about any particular deployment, host, network,
  token or organisation goes in here.
- Branch + PR to `main`; commit messages end with a `Co-Authored-By:` trailer
  naming the model.

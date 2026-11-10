# Paper draft

[Read the PDF](manuscript.pdf) or edit the [Markdown manuscript](manuscript.md).
The title matches the registered PacificVis 2027 conference-paper abstract:
**Probabilistic Hierarchical Modeling of Tsunami Arrival-Time Differences**.

The draft reports the completed source-separated Bayesian analysis. It contains
the model equations and priors, sequence-based comparisons, parameter estimates,
three existing analytical figures, predictive discrepancies and limitations.
The [evidence index](evidence-index.md) identifies the tables, denominators and
checksums behind its numerical claims. The [bibliography](references.bib) contains
nine primary sources; the manuscript makes no first-use claim for Bayesian
hierarchical tsunami modeling.

This is an anonymous **author-review draft**, rather than an approved submission.
Its main scientific limitation is substantial conditional predictive mismatch
despite satisfactory reported sampling checks. It reports neither an untouched
test result nor validated physical first-arrival or operational forecast accuracy.
The 18 reserved outcomes remain sealed. The visualization contribution is a
static modeling case study; its novelty and fit for PacificVis require an author
decision. No user study or evaluated interactive system is claimed.

Before submission, the authors need to review and approve the actual claims,
confirm the departure from the prospective abstract's uncertain physical picks
and site hierarchy, set the appropriate review identity in `main.tex`, and
provide the intended stable, appropriately anonymized replication materials.
The PDF also needs a manual accessibility and reading-order check; it is not
tagged. The acknowledgments disclose the role of ChatGPT/Codex and must accurately
describe the authors' use of those tools.

The official [conference call](https://pacificvis2027.github.io/contribute/conference-papers/)
sets a maximum of nine content pages plus two pages containing only
acknowledgments and references. The draft has eight pages: seven content pages,
including the figures, followed by one acknowledgments/reference page.
[Submission requirements](https://pacificvis2027.github.io/contribute/paper-submission-guidelines/)
were checked on November 9, 2026. The paper deadline is November 9 at 23:59 AoE
(November 10 at 03:59 Pacific Standard Time).

## Rebuild

With Python 3.9 or later, Pandoc and Tectonic on `PATH`, run from the repository:

```sh
python3 paper/build.py --output-directory /private/tmp/tsunami-paper-build
```

The command creates an editable TeX bundle and `main.pdf` in the specified
directory. It converts the current Markdown, uses numeric BibTeX citations,
copies the three existing figures without modifying them, and compiles using
the official conference class. The standard Times-compatible fonts, margins and
type sizes are retained. Tectonic may fetch public TeX resources into its cache
on the first build. No statistical analysis or model fitting is performed.

The tracked `manuscript.pdf` is a reviewed build; rebuilding does not overwrite it.
Inspect a rebuilt PDF before replacing that file. Build logs and intermediate
files remain in the requested output directory.

## Template credit

The unmodified class and bibliography style in `template/` come from the
[IEEE VGTC conference LaTeX template, release 2024.02.14](https://github.com/ieeevgtc/vgtc_conference_latex/tree/2024.02.14),
linked by the [official publication guide](https://tc.computer.org/vgtc/publications/conference/).
The original README and class notices are retained. The template class must not
be modified without the approval stated in its header. `main.tex` is this
project's manuscript wrapper, separate from the upstream class.

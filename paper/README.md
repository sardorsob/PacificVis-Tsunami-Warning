# Paper draft

[Read the PDF](manuscript.pdf) or edit the [Markdown manuscript](manuscript.md).
The title matches the registered PacificVis 2027 conference-paper abstract:
**Probabilistic Hierarchical Modeling of Tsunami Arrival-Time Differences**.

The draft reports the completed source-separated Bayesian analysis. It contains
the model equations and priors, sequence-based comparisons, parameter estimates,
three compact vector figures drawn from the saved tables, predictive discrepancies and limitations.
The [evidence index](evidence-index.md) identifies the tables, denominators and
checksums behind its numerical claims. The [bibliography](references.bib) contains
ten selected scholarly and institutional sources; the manuscript makes no
first-use claim for Bayesian hierarchical tsunami modeling. Source details appear in footnotes at the bottom
of the relevant page. The complete bibliography remains at the end.

This is a **working draft** by Sardor Sobirov, an independent researcher.
The title block includes the research category and an underlined
“GitHub repository” link to the project repository.
Its main scientific limitation is substantial conditional predictive mismatch
despite satisfactory reported sampling checks. It reports neither an untouched
test result nor validated physical first-arrival or operational forecast accuracy.
The 18 reserved outcomes remain sealed. The visualization contribution is a
static modeling case study; its novelty and fit for PacificVis require an author
decision. No user study or evaluated interactive system is claimed.

Before submission, the authors need to review and approve the actual claims,
confirm the departure from the prospective abstract's uncertain physical picks
and site hierarchy, confirm the final venue formatting, and
provide stable replication materials for the submitted version.
The PDF also needs a manual accessibility and reading-order check; it is not
tagged. The acknowledgments disclose the role of ChatGPT/Codex and must accurately
describe the authors' use of those tools.

The official [conference call](https://pacificvis2027.github.io/contribute/conference-papers/)
sets a maximum of nine content pages plus two pages containing only
acknowledgments and references. The draft has seven pages: six content pages,
including the figures, followed by one acknowledgments/reference page.
[Submission requirements](https://pacificvis2027.github.io/contribute/paper-submission-guidelines/)
were checked on November 9, 2026. The paper deadline is November 9 at 23:59 AoE
(November 10 at 03:59 Pacific Standard Time).

## Paper figures

The figures use consistent typography, compact horizontal panels and a restrained
palette. Interval types, signed units and extrapolation remain explicit; longer
scientific qualifications are in the captions. The data values and original
result artifacts are unchanged.

| Figure | Preview | Editable vector | Publication vector |
| --- | --- | --- | --- |
| Residual spread and event variation | [PNG](figures/residual-spread-and-event-variation.png) | [SVG](figures/residual-spread-and-event-variation.svg) | [PDF](figures/residual-spread-and-event-variation.pdf) |
| Sequence prediction and probability check | [PNG](figures/sequence-prediction-and-probability-check.png) | [SVG](figures/sequence-prediction-and-probability-check.svg) | [PDF](figures/sequence-prediction-and-probability-check.pdf) |
| Median and new-report intervals | [PNG](figures/median-and-new-report-intervals.png) | [SVG](figures/median-and-new-report-intervals.svg) | [PDF](figures/median-and-new-report-intervals.pdf) |

Regenerate them into a new output directory using the pinned project environment:

```sh
MPLCONFIGDIR=/private/tmp/tsunami-paper-mpl uv run --locked --offline python paper/plot_figures.py --output-directory /private/tmp/tsunami-paper-figures
```

The renderer refuses to overwrite an existing figure directory. Its saved-table
inputs and exact plotted data are listed in the [evidence index](evidence-index.md).
The six CSV exports, vector files and 600-pixel previews have recorded checksums.
Two fresh visual review rounds and an independent numeric/range audit checked
the revised figures. A physical print and accessibility review remain useful.

## Rebuild

With Python 3.9 or later, Pandoc and Tectonic on `PATH`, run from the repository:

```sh
python3 paper/build.py --output-directory /private/tmp/tsunami-paper-build
```

The command creates an editable TeX bundle and `main.pdf` in the specified
directory. It converts the current Markdown, places source details in
page footnotes, retains numbered BibTeX references at the end,
embeds the three vector paper figures without changing their data, and compiles using
the official conference class. Headings use bold Times-compatible serif type
with normal capitalization through the class's font setting. The template's
margins and type sizes are retained. Paragraph spacing does not stretch to fill
shorter columns, and source footnotes stay at the page bottom.
Tectonic may fetch public TeX resources into its cache
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

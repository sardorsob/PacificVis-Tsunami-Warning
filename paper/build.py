"""Render the manuscript with the unmodified IEEE VGTC conference class."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from pathlib import Path


def build(output: Path) -> None:
    paper = Path(__file__).resolve().parent
    root = paper.parent
    output.mkdir(parents=True, exist_ok=True)
    text = re.sub(
        r"^---\n.*?\n---\n", "", (paper / "manuscript.md").read_text(), count=1, flags=re.S
    )
    abstract, body = text.split("## 1. Introduction", 1)
    abstract = abstract.split("## Abstract", 1)[1].split("**Keywords:**", 1)[0]
    body = "## 1. Introduction" + body.split("## References", 1)[0]
    body = re.sub(r"^(#{2,3}) \d+(?:\.\d+)?\. ", r"\1 ", body, flags=re.M)
    body = body.replace("## Acknowledgments", "\\clearpage\n\n## Acknowledgments {-}")
    table = r"""\begin{table*}[t]
\centering
\caption{Reports used in the final fits. Each timing quantity has its own inclusion rules.
The two NTWC datasets can share an observed time and are fitted separately.}
\begin{tabular}{llrr}
\hline
Response & Definition & Reports & Events \\
\hline
NCEI duration & Positive travel duration reported by NCEI & 1,215 & 47 \\
T-OBS & Observed UTC minus reviewed USGS origin & 258 & 20 \\
T-CAL & Estimated UTC minus observed UTC & 169 & 18 \\
\hline
\end{tabular}
\end{table*}"""
    body, tables = re.subn(
        r"\| Response \|.*?\*\*Table 1\.\*\*.*?\n",
        lambda _: table + "\n",
        body,
        count=1,
        flags=re.S,
    )
    if tables != 1:
        raise ValueError("Expected exactly one source cohort table")

    def figure(match: re.Match[str]) -> str:
        _description, source, number, caption = match.groups()
        caption = caption.replace("%", r"\%")
        source_path = (paper / source).resolve()
        try:
            source_path.relative_to(root / "artifacts")
        except ValueError:
            source_path.relative_to(paper / "figures")
        vector = source_path.with_suffix(".pdf")
        if vector.is_file():
            source_path = vector
        destination = output / f"figure{number}{source_path.suffix}"
        shutil.copyfile(source_path, destination)
        # Full-width floats preserve figure text; clearpage keeps all before references.
        return (
            "\\begin{figure*}[tp]\n\\centering\n"
            f"\\includegraphics[width=\\textwidth,height=0.74\\textheight,keepaspectratio]{{{destination.name}}}\n"
            f"\\caption{{{caption}}}\n\\end{{figure*}}\n"
        )

    body, figures = re.subn(
        r"!\[(.*?)\]\((.*?)\)\n\n\*\*Figure (\d+)\.\*\* (.*?)\n",
        figure,
        body,
        flags=re.S,
    )
    if figures != 3:
        raise ValueError("Expected exactly three source figures")
    for name, content in [("abstract.md", abstract.strip()), ("body.md", body)]:
        (output / name).write_text(content + "\n")
        subprocess.run(
            [
                "pandoc",
                "--from=markdown+raw_tex",
                "--to=latex",
                "--shift-heading-level-by=-1",
                "--natbib",
                name,
                "-o",
                name.replace(".md", ".tex"),
            ],
            cwd=output,
            check=True,
        )
    for name in ["main.tex", "references.bib"]:
        shutil.copyfile(paper / name, output / name)
    for name in ["vgtc.cls", "abbrv-doi.bst"]:
        shutil.copyfile(paper / "template" / name, output / name)
    subprocess.run(["tectonic", "--untrusted", "--keep-logs", "main.tex"], cwd=output, check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, required=True)
    build(parser.parse_args().output_directory.resolve())

#!/usr/bin/env bash
#
# Build the paper and pack the arXiv bundle.
#
#   ./build.sh
#
# arXiv compiles with pdflatex, and `\pdfoutput=1` on line 1 of main.tex selects it. The build
# needs only main.tex, generated/ and figures/, all tracked, so a fresh clone builds without the
# harness, its results or any Python. Regenerating generated/ and figures/ from results is
# ./regenerate.sh, not part of the build.
#
# Writes: main.pdf, abstract.txt (the abstract as plain text, one paragraph per line, for the
# arXiv and Zenodo forms, with a warning past arXiv's 1920 characters), and arxiv.tar.gz, the
# submission bundle: main.tex, generated/, figures/ at the root and, under anc/ where arXiv lists
# them as ancillary files, the data the paper rests on (see pack() and anc-README.md). The
# paper's scripts are not packed; they live in the public repository under paper/scripts/.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(cd .. && pwd)"
MAIN="${CCS_MAIN_RESULTS:-$ROOT/results/2026-10-19}"
MLCQ="${CCS_MLCQ_RESULTS:-$ROOT/results/mlcq}"

abstract() {
  local out=abstract.txt
  sed -n '/^\\begin{abstract}$/,/^\\end{abstract}$/p' main.tex \
    | sed -e '1d' -e '$d' \
    | sed -E -e 's/\\noindent//g' \
             -e 's/\\(emph|textbf|textit|texttt|textsc)\{([^}]*)\}/\2/g' \
             -e 's/\\([A-Za-z]+)\{\}/\\\1/g' \
    > "$out.tmp"
  # expand the number macros the abstract uses (generated/numbers.tex)
  python3 - "$out.tmp" "$out" <<'PY'
import re, sys
src, dst = sys.argv[1], sys.argv[2]
macros = dict(re.findall(r'\\newcommand\{\\([A-Za-z]+)\}\{(.*)\}', open('generated/numbers.tex').read()))
text = open(src).read()
text = re.sub(r'\\([A-Za-z]+)', lambda m: macros.get(m.group(1), m.group(0)), text)
text = text.replace('{,}', ',').replace('``', '"').replace("''", '"').replace('~', ' ')
text = re.sub(r'\\([%$&_#])', r'\1', text)
text = text.replace(r'\texttt{', '').replace('\\', '')
paras, cur = [], []
for line in text.splitlines():
    if line.strip():
        cur.append(line.strip())
    elif cur:
        paras.append(' '.join(cur)); cur = []
if cur:
    paras.append(' '.join(cur))
open(dst, 'w').write('\n\n'.join(paras) + '\n')
PY
  rm -f "$out.tmp"
  if grep -n '[\\{}]' "$out" >&2; then
    echo "WARNING: the lines above still contain LaTeX markup; teach abstract() in build.sh about it." >&2
  fi
  local chars; chars=$(wc -c < "$out" | tr -d ' ')
  echo "Wrote $out ($(wc -w < "$out" | tr -d ' ') words, $chars characters, arXiv limit 1920)"
  [ "$chars" -le 1920 ] || echo "WARNING: the abstract is $((chars - 1920)) characters over arXiv's 1920 limit." >&2
}

pack() {
  local stage; stage="$(mktemp -d)"
  trap 'rm -rf "$stage"' RETURN
  mkdir -p "$stage/anc"
  cp anc-README.md "$stage/anc/README.md"
  cp regeneration.txt "$stage/anc/REGENERATION.txt"
  # the harness's analyses and what they rest on
  local d="$stage/anc/main-run"; mkdir -p "$d/classpath"
  for f in analysis.json analysis.json.sha256 halves.json oracles.json run-log.jsonl; do cp "$MAIN/$f" "$d/" 2>/dev/null || echo "   ! $MAIN/$f missing" >&2; done
  cp "$MAIN"/analysis.exploratory.*.json "$MAIN"/analysis.exploratory.*.json.sha256 "$d/" 2>/dev/null || true
  cp "$MAIN"/classpath/*.json "$d/classpath/" 2>/dev/null || true
  cp "$MAIN/anc/results.csv" "$d/results.csv" 2>/dev/null || true
  cp "$ROOT"/sample/open-source-repository-sample*.csv "$ROOT"/sample/open-source-repository-sample*.derivation.json "$d/" 2>/dev/null || true
  cp "$ROOT/classpath-candidates.tsv" "$ROOT/classpath-log.tsv" "$ROOT/analysis-hashes.txt" "$d/" 2>/dev/null || true
  d="$stage/anc/mlcq-run"; mkdir -p "$d"
  for f in analysis.json analysis.json.sha256 halves.json run-log.jsonl; do cp "$MLCQ/$f" "$d/" 2>/dev/null || echo "   ! $MLCQ/$f missing" >&2; done
  cp "$MLCQ"/agreement.exploratory.*.json "$MLCQ"/agreement.exploratory.*.json.sha256 "$d/" 2>/dev/null || true
  cp "$MLCQ/anc/oracles.json" "$MLCQ/anc/results.csv" "$d/" 2>/dev/null || true
  cp "$ROOT"/labels/mlcq-labels.csv "$ROOT"/labels/mlcq-repos.csv "$ROOT"/labels/mlcq-summary.json "$ROOT/mlcq-hashes.txt" "$d/" 2>/dev/null || true
  # the paper's own reductions and read-outs (never the per-unit sidecars)
  d="$stage/anc/paper"; mkdir -p "$d"
  cp data/human.json data/agreement.json data/human_readout.log data/agreement.log "$d/" 2>/dev/null || echo "   ! paper/data read-outs missing: run ./regenerate.sh" >&2
  # the scripts themselves are not packed: they are committed under paper/scripts/ in the public
  # repository, which anc-README.md names, so the bundle carries data and read-outs only
  tar czf arxiv.tar.gz main.tex generated figures -C "$stage" anc
  echo "Packed arxiv.tar.gz ($(tar tzf arxiv.tar.gz | grep -c .) entries, $(du -h arxiv.tar.gz | cut -f1))"
}

abstract
if ! command -v pdflatex >/dev/null 2>&1; then
  echo "pdflatex not found: install TeX Live (./setup.sh says how). main.tex targets pdflatex, which arXiv runs." >&2
  exit 1
fi
pdflatex -interaction=nonstopmode -halt-on-error main.tex > build.log 2>&1 || { tail -n 40 build.log; exit 1; }
pdflatex -interaction=nonstopmode -halt-on-error main.tex > build.log 2>&1 || { tail -n 40 build.log; exit 1; }
echo "Built main.pdf ($(pdfinfo main.pdf 2>/dev/null | awk '/Pages/{print $2}') pages); $(grep -c Overfull build.log || true) overfull boxes, $(grep -c 'LaTeX Warning' build.log || true) LaTeX warnings (see build.log)"
pack

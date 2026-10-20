#!/usr/bin/env bash
#
# Install what the paper's scripts and build need. Idempotent.
#
#   ./setup.sh                 # the figure venv (matplotlib, pinned) and a TeX check
#   SKIP_TEX_CHECK=1 ./setup.sh
#
# Two toolchains, kept apart on purpose:
#   ../.venv          the HARNESS's virtualenv (../setup.sh or ../step1_setup.sh): every analysis
#                     script here (extract_*.py, human_readout.py, agreement.py, tables.py) runs on
#                     it, because they import the harness's own statistics and rules, which import
#                     the pinned lizard. Standard library otherwise.
#   ./.venv           the FIGURE virtualenv: matplotlib and numpy, pinned in requirements.txt.
#                     Only figures.py needs it; it reads the JSON the analysis scripts wrote and
#                     never imports the harness.
# pdflatex is what arXiv compiles with; main.tex loads only packages TeX Live carries
# (texlive-latex-base, -recommended, -extra, -fonts-recommended, lmodern on Debian/Ubuntu).
set -euo pipefail
cd "$(dirname "$0")"
echo "== 1/3 harness virtualenv =="
if [ -x ../.venv/bin/python ]; then
  echo "   ../.venv present: $(../.venv/bin/python --version)"
else
  echo "   ! ../.venv missing: run ../step1_setup.sh first (the analysis scripts need it)"
fi
echo "== 2/3 figure virtualenv =="
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
.venv/bin/pip install --quiet --requirement requirements.txt
echo "   $(.venv/bin/python -c 'import matplotlib, numpy; print("matplotlib", matplotlib.__version__, "numpy", numpy.__version__)')"
echo "== 3/3 TeX =="
if [ "${SKIP_TEX_CHECK:-}" = 1 ]; then
  echo "   skipped"
elif ! command -v pdflatex >/dev/null 2>&1; then
  echo "   ! no pdflatex on PATH. Debian/Ubuntu: sudo apt-get install --no-install-recommends"
  echo "     texlive-latex-base texlive-latex-recommended texlive-latex-extra texlive-fonts-recommended lmodern"
else
  missing=()
  while read -r sty; do
    [ -n "$sty" ] || continue
    kpsewhich "${sty}.sty" >/dev/null 2>&1 || missing+=("$sty")
  done < <(sed -n 's/^\\usepackage\(\[[^]]*\]\)\?{\([^}]*\)}.*/\2/p' main.tex | tr ',' '\n')
  if [ ${#missing[@]} -eq 0 ]; then
    echo "   $(pdflatex --version | head -n1); every package main.tex loads is present"
  else
    echo "   ! missing LaTeX packages: ${missing[*]}"
    exit 1
  fi
fi
echo
echo "Next: ./regenerate.sh (numbers, tables, figures from ../results), then ./build.sh (the PDF)"

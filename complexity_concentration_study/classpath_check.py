"""The classpath validation sub-study (README, 'The classpath validation sub-study').

PMD runs in the study WITHOUT an auxiliary classpath, so its type-resolution-dependent metrics
(ATFD in GodClass, the coupling rules) see only what the sources declare, and `pmd_GodClass`
is under-counted by an unknown amount. This module measures that amount on one repository:
it runs PMD twice over the same Java files, without and with a classpath, and reports every
class finding that flips.

    complexity-concentration-study classpath-check --repo PATH \\
        [--classpath-file cp.txt | --aux-classpath 'a.jar:b.jar'] [--pmd PMD] [--out r.json]

Getting a classpath (not done here; it needs the project's own build):
    Maven   mvn -q dependency:build-classpath -Dmdep.outputFile=cp.txt   (then --classpath-file cp.txt)
    Gradle  a task that prints `sourceSets.main.runtimeClasspath.asPath` to a file
The project's own compiled classes (every target/classes and build/classes/java/main under the
checkout) are added automatically unless --no-build-output, since cross-module references are
part of what the classpath resolves.

The file list is the study's own: the Java files the extractor would measure (tests, vendored,
generated and oversize files excluded the same way), so the flips are the flips the study's
numbers would see. Run it on about ten Java repositories of the sample and quote the GodClass
flip rate with the Java class-level headline.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import extract, study

_BUILD_OUTPUT = ("target/classes", "build/classes/java/main", "build/classes/kotlin/main")


def build_output_dirs(root: str) -> list[str]:
    """Every compiled-classes directory under the checkout (Maven and Gradle layouts)."""
    out = []
    for dirpath, dirnames, _ in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules")]
        rel = os.path.relpath(dirpath, root).replace(os.sep, "/")
        if any(rel == b or rel.endswith("/" + b) for b in _BUILD_OUTPUT):
            out.append(dirpath)
            dirnames[:] = []
    return sorted(out)


def read_classpath_file(path: str) -> str:
    """A classpath as Maven's dependency:build-classpath writes it (one line, path-separated),
    or one entry per line."""
    with open(path) as fh:
        text = fh.read().strip()
    parts = [p for line in text.splitlines() for p in line.split(os.pathsep) if p.strip()]
    return os.pathsep.join(p.strip() for p in parts)


def java_files(root: str) -> list[str]:
    """The Java files the study measures in this checkout (same filters as the extractor)."""
    return sorted(f for f in extract.scan_files(root)["source"] if f.endswith(".java"))


def compare(pmd: str, root: str, aux_classpath: str) -> dict:
    """Run PMD without and with `aux_classpath` on the study's Java files of `root`; report,
    per class rule, the files flagged under each and the ones that flip either way, and the
    GodClass flip rate (flips over the union of GodClass verdicts)."""
    files = java_files(root)
    without = study._pmd_report(pmd, root, files)
    with_cp = study._pmd_report(pmd, root, files, aux_classpath=aux_classpath)
    if without is None or with_cp is None:
        raise RuntimeError("PMD produced no parsable report "
                           + ("without" if without is None else "with") + " the classpath")
    rules: dict = {}
    for rule in study._PMD_CLASS_RULES:
        a = without["class"].get(rule, set())
        b = with_cp["class"].get(rule, set())
        rules[rule] = {"without": len(a), "with": len(b),
                       "gained": sorted(b - a), "lost": sorted(a - b)}
    g = rules["GodClass"]
    flips = len(g["gained"]) + len(g["lost"])
    stable = g["without"] - len(g["lost"])            # flagged under both
    union = stable + flips                            # every file flagged under either
    return {"root": os.path.abspath(root), "n_java_files": len(files),
            "aux_classpath_entries": len([p for p in aux_classpath.split(os.pathsep) if p]),
            "pmd": study.pmd_version(pmd), "rules": rules,
            "godclass_flips": flips,
            "godclass_flip_rate": round(flips / union, 4) if union else None,
            "method_findings": {"without": len(without["method"]), "with": len(with_cp["method"])}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="complexity-concentration-study classpath-check",
                                 description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__)
    ap.add_argument("--repo", required=True, help="a Java checkout (built, for --build-output)")
    ap.add_argument("--pmd", default=None, help="PMD binary (default: ./lib PMD)")
    ap.add_argument("--aux-classpath", default="", help="classpath string (path-separated)")
    ap.add_argument("--classpath-file", default=None,
                    help="file holding the classpath (Maven dependency:build-classpath output)")
    ap.add_argument("--no-build-output", action="store_true",
                    help="do not add the checkout's own compiled-classes directories")
    ap.add_argument("--out", default=None, help="write the JSON report here")
    args = ap.parse_args(argv)
    from . import deps
    pmd = args.pmd or deps.default_pmd()
    if not pmd:
        print("no PMD: pass --pmd or run ./step1_setup.sh", file=sys.stderr)
        return 2
    parts = []
    if args.classpath_file:
        parts.append(read_classpath_file(args.classpath_file))
    if args.aux_classpath:
        parts.append(args.aux_classpath)
    if not args.no_build_output:
        parts.extend(build_output_dirs(args.repo))
    cp = os.pathsep.join(p for p in parts if p)
    if not cp:
        print("no classpath: pass --classpath-file or --aux-classpath, or build the project "
              "so its compiled classes exist", file=sys.stderr)
        return 2
    rep = compare(pmd, args.repo, cp)
    print(f"{rep['root']}: {rep['n_java_files']} Java files, {rep['aux_classpath_entries']} "
          f"classpath entries, PMD {rep['pmd']}")
    for rule, r in rep["rules"].items():
        if r["without"] or r["with"]:
            print(f"  {rule:28} without {r['without']:>4}  with {r['with']:>4}  "
                  f"gained {len(r['gained']):>3}  lost {len(r['lost']):>3}")
    print(f"  GodClass flips: {rep['godclass_flips']} (flip rate {rep['godclass_flip_rate']})")
    for k in ("gained", "lost"):
        for f in rep["rules"]["GodClass"][k]:
            print(f"    GodClass {k}: {f}")
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(rep, fh, indent=2)
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

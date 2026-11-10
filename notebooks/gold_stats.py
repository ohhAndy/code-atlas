"""Function-level gold on dev: how many chunks per instance, of which kinds, how many
instances have none, and how many gold chunks come only from blank lines (the boundary
cost of the pure-insertion neighbor rule), and how many come only from pure-insertion
neighbors (no "-" line inside them).

Run: uv run python notebooks/gold_stats.py
"""

from collections import Counter

from unidiff import PatchSet

from code_atlas.eval.dataset import load_instances, read_split
from code_atlas.eval.gold import changed_lines, function_gold
from code_atlas.eval.repos import snapshot
from code_atlas.parse.chunks import chunk_file, owner
from code_atlas.parse.parser import parse

splits = read_split()
dev = [i for i in load_instances() if splits.get(i.instance_id) == "dev"]

sizes: Counter[int] = Counter()
kinds: Counter[str] = Counter()
empty: list[str] = []
blank_only: list[tuple[str, str]] = []  # (instance, chunk id) gold only via blank lines
syntax_errors: list[str] = []
neighbor_only: list[tuple[str, str]] = []  # (instance, chunk id) with no "-" line inside
n_runs = 0
boundary_runs: list[tuple[str, str, str | None, str | None]] = []  # neighbors' owners differ
boundary_only: list[tuple[str, str]] = []  # gold only through a boundary run's neighbor


def insertion_runs(patch: str) -> dict[str, list[tuple[int, int]]]:
    """Per file, the (before, after) old neighbors of each pure-insertion run (same rule
    as changed_lines)."""
    out: dict[str, list[tuple[int, int]]] = {}
    for pf in PatchSet(patch):
        runs: list[tuple[int, int]] = []
        for h in pf:
            last_old, in_add, saw_remove = h.source_start - 1, False, False
            for ln in h:
                if ln.is_removed:
                    last_old, saw_remove = ln.source_line_no, True
                elif ln.is_added:
                    in_add = True
                elif ln.is_context:
                    if in_add and not saw_remove:
                        runs.append((last_old, ln.source_line_no))
                    last_old, in_add, saw_remove = ln.source_line_no, False, False
            if in_add and not saw_remove:
                runs.append((last_old, last_old + 1))
        out[pf.path] = runs
    return out


def removed_lines(patch: str) -> dict[str, set[int]]:
    out: dict[str, set[int]] = {}
    for pf in PatchSet(patch):
        out[pf.path] = {
            ln.source_line_no for h in pf for ln in h if ln.is_removed and ln.source_line_no
        }
    return out


for inst in dev:
    root = snapshot(inst.repo, inst.base_commit)
    gold = function_gold(inst.patch, root)
    sizes[len(gold)] += 1
    if not gold:
        empty.append(inst.instance_id)

    removed = removed_lines(inst.patch)
    runs = insertion_runs(inst.patch)
    for path, lines in changed_lines(inst.patch).items():
        source = (root / path).read_bytes()

        if parse(source).root_node.has_error:
            syntax_errors.append(f"{inst.instance_id} {path}")
        chunks = chunk_file(path, source)
        by_name = {c.qualified_name: c for c in chunks}
        spans = [(c.qualified_name, c.start_line, c.end_line) for c in chunks]
        src_lines = source.splitlines()
        owned: dict[str, list[int]] = {}
        for ln in lines:
            name = owner(ln, spans)
            if name is not None:
                owned.setdefault(name, []).append(ln)
        # Lines that make a chunk gold for a "good" reason: "-" lines, and both neighbors of
        # an insertion that sits inside one chunk.
        good: set[int] = set(removed[path])
        for before, after in runs[path]:
            n_runs += 1
            ob, oa = owner(before, spans), owner(after, spans)
            if ob == oa:
                good |= {before, after}
            else:
                boundary_runs.append((inst.instance_id, path, ob, oa))
        for name, lns in owned.items():
            if not set(lns) & good:
                boundary_only.append((inst.instance_id, f"{path}::{name}"))
            kinds[by_name[name].kind] += 1
            if not set(lns) & removed[path]:
                neighbor_only.append((inst.instance_id, f"{path}::{name}"))
            if all(ln <= len(src_lines) and not src_lines[ln - 1].strip() for ln in lns):
                blank_only.append((inst.instance_id, f"{path}::{name}"))

print(f"dev instances: {len(dev)}")
print(f"gold chunks per instance: {dict(sorted(sizes.items()))}")
print(f"gold chunks by kind: {dict(kinds)}")
print(f"instances with no function-level gold: {len(empty)} {empty}")
blank_insts = sorted({i for i, _ in blank_only})
print(f"gold chunks reached only through blank lines: {len(blank_only)}")
print(f"  in {len(blank_insts)} instances")
for iid, cid in blank_only:
    print(f"  {iid}  {cid}")
n_neighbor = len({i for i, _ in neighbor_only})
print(f"gold chunks with no '-' line (only pure-insertion neighbors): {len(neighbor_only)}")
print(f"  in {n_neighbor} instances")
for iid, cid in neighbor_only:
    print(f"  {iid}  {cid}")
print(f"pure-insertion runs: {n_runs}; at a chunk boundary: {len(boundary_runs)}")
for iid, path, ob, oa in boundary_runs:
    print(f"  {iid}  {path}  {ob} | {oa}")
n_bo = len({i for i, _ in boundary_only})
print(f"gold chunks only through a boundary insertion: {len(boundary_only)} in {n_bo} instances")
for iid, cid in boundary_only:
    print(f"  {iid}  {cid}")
print(f"changed files with tree-sitter parse errors: {syntax_errors}")

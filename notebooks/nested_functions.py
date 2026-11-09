"""Throwaway: on dev, how many instances change a line inside a nested function?"""
import ast
from code_atlas.eval.dataset import load_instances, read_split
from code_atlas.eval.gold import changed_lines
from code_atlas.eval.repos import snapshot

def defs(tree):
    """Yield (node, chain of enclosing defs) for every function/class."""
    out = []
    def walk(node, chain):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                out.append((child, chain))
                walk(child, chain + [child])
            else:
                walk(child, chain)
    walk(tree, [])
    return out

FUNC = (ast.FunctionDef, ast.AsyncFunctionDef)
splits = read_split()
dev = [i for i in load_instances() if splits.get(i.instance_id) == "dev"]
nested_hits, buckets, failures = [], {"nested": 0, "def": 0, "module": 0}, []
for inst in dev:
    root = snapshot(inst.repo, inst.base_commit)
    inst_buckets = set()
    for path, lines in changed_lines(inst.patch).items():
        try:
            tree = ast.parse((root / path).read_bytes())
        except SyntaxError as e:
            failures.append((inst.instance_id, path, str(e))); continue
        ds = defs(tree)
        for ln in sorted(lines):
            containing = [(n, c) for n, c in ds if n.lineno <= ln <= n.end_lineno]
            if not containing:
                inst_buckets.add("module"); continue
            node, chain = min(containing, key=lambda nc: nc[0].end_lineno - nc[0].lineno)
            if isinstance(node, FUNC) and any(isinstance(p, FUNC) for p in chain):
                inst_buckets.add("nested")
                parent = next(p for p in reversed(chain) if isinstance(p, FUNC))
                qual = ".".join(p.name for p in chain + [node])
                nested_hits.append((inst.instance_id, path, ln, qual,
                                    node.end_lineno - node.lineno + 1,
                                    parent.name, parent.end_lineno - parent.lineno + 1))
            else:
                inst_buckets.add("def")
    for b in inst_buckets:
        buckets[b] += 1

print(f"dev instances: {len(dev)}")
print("instances with >=1 changed line in each bucket (an instance can be in several):")
for b, n in buckets.items(): print(f"  {b:7} {n}")
print("parse failures:", failures)
print("\nchanged lines inside a nested function:")
print(f"  {'instance':32} {'line':>5}  {'nested def (qualname, lines)':45} parent (lines)")
for iid, path, ln, qual, nlen, pname, plen in nested_hits:
    print(f"  {iid:32} {ln:>5}  {qual+f' ({nlen})':45} {pname} ({plen})   {path}")

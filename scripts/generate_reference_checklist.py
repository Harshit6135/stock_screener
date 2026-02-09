import os
import ast
from pathlib import Path

class ReferenceVisitor(ast.NodeVisitor):
    def __init__(self):
        self.definitions = []
        self.current_scope = None
        self.calls = None

    def visit_FunctionDef(self, node):
        self._handle_func(node)

    def visit_AsyncFunctionDef(self, node):
        self._handle_func(node)
    
    def visit_ClassDef(self, node):
        prev_scope = self.current_scope
        self.current_scope = node.name
        self.definitions.append({
            "type": "class",
            "name": node.name,
            "lineno": node.lineno,
            "calls": []
        })
        # We don't track calls at class level generally, but methods inside
        self.generic_visit(node)
        self.current_scope = prev_scope

    def _handle_func(self, node):
        name = node.name
        if self.current_scope:
            name = f"{self.current_scope}.{name}"
        
        # Capture args to show signature roughly
        args = [a.arg for a in node.args.args]
        
        func_def = {
            "type": "function",
            "name": name,
            "args": args,
            "lineno": node.lineno,
            "calls": set()
        }
        self.definitions.append(func_def)
        
        # Visit body to find calls
        # We temporarily set this func_def as the context for calls
        old_calls = self.calls
        self.calls = func_def["calls"]
        self.generic_visit(node)
        self.calls = old_calls

    def visit_Call(self, node):
        # Try to extract a readable name for the call
        func_name = self._get_func_name(node.func)
        if func_name and self.calls is not None:
             self.calls.add(func_name)
        self.generic_visit(node)

    def _get_func_name(self, node):
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            # recursive for things like os.path.join
            val = self._get_func_name(node.value)
            if val:
                return f"{val}.{node.attr}"
            return node.attr
        return None

def generate_checklist(root_dir):
    root_path = Path(root_dir).resolve()
    
    print("# Codebase Review Checklist\n")
    print("Use this checklist to track your review progress. 'Calls' lists functions called within the definition to help trace logic.\n")

    # Exclude these directories
    exclude_dirs = {".git", ".venv", ".agent", "logs", "instance", "migrations", "__pycache__", "docs", "templates", "data"}

    for dirpath, dirnames, filenames in os.walk(root_path):
        # Modify dirnames in-place to skip excluded directories
        dirnames[:] = [d for d in dirnames if d not in exclude_dirs]
        
        # Sort for consistent output
        filenames.sort()
        dirnames.sort()
        
        # skip __pycache__ etc (redundant with above but keeps logic similar)
        if "__pycache__" in dirpath:
            continue

        rel_dir = os.path.relpath(dirpath, root_path)
        if rel_dir == ".":
            rel_dir = ""
            
        py_files = [f for f in filenames if f.endswith(".py")]
        
        if not py_files:
            continue

        if rel_dir:
            print(f"## {rel_dir}\n")
        
        for fname in py_files:
            fpath = os.path.join(dirpath, fname)
            
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()
                    tree = ast.parse(content)
            except Exception as e:
                print(f"### {fname} (Error parsing: {e})\n")
                continue

            visitor = ReferenceVisitor()
            visitor.visit(tree)
            
            if not visitor.definitions:
                print(f"### {fname} (No definitions)\n")
                continue

            print(f"### {fname}\n")
            
            # Print top-level items first? Or just in order?
            # They are appended in order of traversal, which is usually file order.
            
            for idef in visitor.definitions:
                if idef["type"] == "class":
                    print(f"- [ ] **class {idef['name']}**")
                else:
                    args_str = ", ".join(idef["args"])
                    print(f"- [ ] **def {idef['name']}({args_str})**")
                    if idef["calls"]:
                        calls_list = ", ".join(sorted([f"`{c}`" for c in idef["calls"]]))
                        print(f"    - *Calls*: {calls_list}")
            print("")

if __name__ == "__main__":
    # Scan current directory (project root)
    generate_checklist(".")


import os
import ast
import re
import sys

def get_python_files(root_dir):
    py_files = []
    for root, dirs, files in os.walk(root_dir):
        if 'venv' in root or '.git' in root:
            continue
        for file in files:
            if file.endswith('.py') and file != 'analyze_unused.py':
                py_files.append(os.path.join(root, file))
    return py_files

class DefinitionVisitor(ast.NodeVisitor):
    def __init__(self):
        self.definitions = []

    def visit_FunctionDef(self, node):
        if not node.name.startswith('__'):
            self.definitions.append(('function', node.name, node.lineno))
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        self.definitions.append(('class', node.name, node.lineno))
        self.generic_visit(node)

    def visit_Assign(self, node):
        # Top level assignments or inside init?
        # For this script, we track top-level assignments (constants/globals)
        # We can try to track self.x in __init__ but it's complex to distinguish from usage vs def.
        # Let's stick to functions and classes and simple globals for now.
        for target in node.targets:
            if isinstance(target, ast.Name):
                 if not target.id.startswith('__'):
                    self.definitions.append(('variable', target.id, node.lineno))
        self.generic_visit(node)

def get_definitions(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        try:
            tree = ast.parse(f.read(), filename=file_path)
        except SyntaxError:
            return []
    
    visitor = DefinitionVisitor()
    visitor.visit(tree)
    return visitor.definitions

def count_usages(name, all_files):
    count = 0
    pattern = re.compile(r'\b' + re.escape(name) + r'\b')
    for file_path in all_files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                matches = pattern.findall(content)
                count += len(matches)
        except Exception:
            pass
    return count

def main():
    root_dir = os.path.dirname(os.path.abspath(__file__))
    all_files = get_python_files(root_dir)
    passed_files = 0
    
    print(f"Scanning {len(all_files)} files...")
    
    report = {}

    for file_path in all_files:
        defs = get_definitions(file_path)
        rel_path = os.path.relpath(file_path, root_dir)
        
        for type_, name, lineno in defs:
            # Skip common false positives
            if name in ['main', 'setUp', 'tearDown']: 
                continue
                
            count = count_usages(name, all_files)
            
            # Count <= 1 means it likely only appears in its definition (or not even there if dynamic?)
            # Usually definition = 1 usage.
            if count <= 1:
                if rel_path not in report:
                    report[rel_path] = []
                report[rel_path].append(f"[{type_}] {name} (Line {lineno}) - Count: {count}")

    print("\n POTENTIAL UNUSED DEFINITIONS:\n")
    for file, items in report.items():
        print(f"File: {file}")
        for item in items:
            print(f"  {item}")
        print("")

if __name__ == '__main__':
    main()

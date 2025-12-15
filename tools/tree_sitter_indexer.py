"""
Tree-sitter based code indexer for Java/Kotlin codebases.

Extracts symbols (classes, methods, fields) and builds a searchable index.
"""

import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional

try:
    import tree_sitter_java
    from tree_sitter import Language, Parser
except ImportError:
    print(
        "Error: tree-sitter not installed. Run: pip install tree-sitter tree-sitter-java"
    )
    exit(1)


@dataclass
class Symbol:
    """Represents a code symbol (class, method, field, etc.)"""

    name: str
    type: str  # "class", "method", "field", "interface"
    file_path: str
    line_start: int
    line_end: int
    parent: Optional[str] = None  # Parent class/interface name
    modifiers: List[str] = None  # public, private, static, etc.
    parameters: List[str] = None  # For methods
    return_type: Optional[str] = None  # For methods

    def __post_init__(self):
        if self.modifiers is None:
            self.modifiers = []
        if self.parameters is None:
            self.parameters = []


class CodebaseIndexer:
    """Index a codebase using tree-sitter for structural analysis."""

    def __init__(self):
        # Initialize tree-sitter parser
        self.parser = Parser()
        self.java_language = Language(tree_sitter_java.language())
        self.parser.language = self.java_language

        # Index storage
        self.symbols: Dict[str, Symbol] = {}  # symbol_name -> Symbol
        self.files: Dict[str, List[str]] = {}  # file_path -> [symbol_names]
        self.classes: Dict[str, Symbol] = {}  # class_name -> Symbol
        self.methods: Dict[str, List[Symbol]] = defaultdict(
            list
        )  # method_name -> [Symbols]
        self.fields: Dict[str, List[Symbol]] = defaultdict(
            list
        )  # field_name -> [Symbols]

    def index_file(self, file_path: str) -> int:
        """Index a single Java file. Returns number of symbols found."""
        try:
            with open(file_path, "rb") as f:
                source_code = f.read()

            tree = self.parser.parse(source_code)
            root_node = tree.root_node

            symbols_found = []

            # Extract symbols using tree-sitter queries
            self._extract_classes(root_node, file_path, source_code, symbols_found)

            # Store file mapping
            self.files[file_path] = [s.name for s in symbols_found]

            return len(symbols_found)

        except Exception as e:
            print(f"Error indexing {file_path}: {e}")
            return 0

    def _extract_classes(
        self, node, file_path: str, source_code: bytes, symbols_found: List[Symbol]
    ):
        """Extract class definitions and their members."""

        # Query for class declarations
        if node.type == "class_declaration":
            class_name = None
            modifiers = []

            for child in node.children:
                if child.type == "identifier":
                    class_name = source_code[child.start_byte : child.end_byte].decode(
                        "utf-8"
                    )
                elif child.type == "modifiers":
                    modifiers = [
                        source_code[m.start_byte : m.end_byte].decode("utf-8")
                        for m in child.children
                        if m.type != "comment"
                    ]
                elif child.type == "class_body":
                    # Extract methods and fields from class body
                    if class_name:
                        self._extract_class_members(
                            child, file_path, source_code, class_name, symbols_found
                        )

            if class_name:
                symbol = Symbol(
                    name=class_name,
                    type="class",
                    file_path=file_path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    modifiers=modifiers,
                )
                self.symbols[class_name] = symbol
                self.classes[class_name] = symbol
                symbols_found.append(symbol)

        # Query for interface declarations
        elif node.type == "interface_declaration":
            interface_name = None
            modifiers = []

            for child in node.children:
                if child.type == "identifier":
                    interface_name = source_code[
                        child.start_byte : child.end_byte
                    ].decode("utf-8")
                elif child.type == "modifiers":
                    modifiers = [
                        source_code[m.start_byte : m.end_byte].decode("utf-8")
                        for m in child.children
                        if m.type != "comment"
                    ]
                elif child.type == "interface_body":
                    if interface_name:
                        self._extract_class_members(
                            child, file_path, source_code, interface_name, symbols_found
                        )

            if interface_name:
                symbol = Symbol(
                    name=interface_name,
                    type="interface",
                    file_path=file_path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    modifiers=modifiers,
                )
                self.symbols[interface_name] = symbol
                self.classes[interface_name] = symbol
                symbols_found.append(symbol)

        # Recursively process children
        for child in node.children:
            self._extract_classes(child, file_path, source_code, symbols_found)

    def _extract_class_members(
        self,
        class_body_node,
        file_path: str,
        source_code: bytes,
        parent_class: str,
        symbols_found: List[Symbol],
    ):
        """Extract methods and fields from a class body."""

        for child in class_body_node.children:
            # Method declarations
            if child.type == "method_declaration":
                method_name = None
                modifiers = []
                parameters = []
                return_type = None

                for method_child in child.children:
                    if method_child.type == "identifier":
                        method_name = source_code[
                            method_child.start_byte : method_child.end_byte
                        ].decode("utf-8")
                    elif method_child.type == "modifiers":
                        modifiers = [
                            source_code[m.start_byte : m.end_byte].decode("utf-8")
                            for m in method_child.children
                            if m.type != "comment"
                        ]
                    elif method_child.type == "formal_parameters":
                        # Extract parameter types
                        for param in method_child.children:
                            if param.type == "formal_parameter":
                                param_type = self._extract_type(param, source_code)
                                if param_type:
                                    parameters.append(param_type)
                    elif method_child.type in [
                        "type_identifier",
                        "integral_type",
                        "void_type",
                        "boolean_type",
                    ]:
                        return_type = source_code[
                            method_child.start_byte : method_child.end_byte
                        ].decode("utf-8")
                    elif method_child.type == "generic_type":
                        return_type = source_code[
                            method_child.start_byte : method_child.end_byte
                        ].decode("utf-8")

                if method_name:
                    full_name = f"{parent_class}.{method_name}"
                    symbol = Symbol(
                        name=full_name,
                        type="method",
                        file_path=file_path,
                        line_start=child.start_point[0] + 1,
                        line_end=child.end_point[0] + 1,
                        parent=parent_class,
                        modifiers=modifiers,
                        parameters=parameters,
                        return_type=return_type,
                    )
                    self.symbols[full_name] = symbol
                    self.methods[method_name].append(symbol)
                    symbols_found.append(symbol)

            # Field declarations
            elif child.type == "field_declaration":
                field_type = None
                modifiers = []

                for field_child in child.children:
                    if field_child.type == "modifiers":
                        modifiers = [
                            source_code[m.start_byte : m.end_byte].decode("utf-8")
                            for m in field_child.children
                            if m.type != "comment"
                        ]
                    elif field_child.type in [
                        "type_identifier",
                        "integral_type",
                        "boolean_type",
                    ]:
                        field_type = source_code[
                            field_child.start_byte : field_child.end_byte
                        ].decode("utf-8")
                    elif field_child.type == "generic_type":
                        field_type = source_code[
                            field_child.start_byte : field_child.end_byte
                        ].decode("utf-8")
                    elif field_child.type == "variable_declarator":
                        # Get field name
                        for var_child in field_child.children:
                            if var_child.type == "identifier":
                                field_name = source_code[
                                    var_child.start_byte : var_child.end_byte
                                ].decode("utf-8")
                                full_name = f"{parent_class}.{field_name}"
                                symbol = Symbol(
                                    name=full_name,
                                    type="field",
                                    file_path=file_path,
                                    line_start=child.start_point[0] + 1,
                                    line_end=child.end_point[0] + 1,
                                    parent=parent_class,
                                    modifiers=modifiers,
                                    return_type=field_type,
                                )
                                self.symbols[full_name] = symbol
                                self.fields[field_name].append(symbol)
                                symbols_found.append(symbol)

    def _extract_type(self, param_node, source_code: bytes) -> Optional[str]:
        """Extract type from a parameter node."""
        for child in param_node.children:
            if child.type in [
                "type_identifier",
                "integral_type",
                "boolean_type",
                "generic_type",
            ]:
                return source_code[child.start_byte : child.end_byte].decode("utf-8")
        return None

    def index_directory(
        self, directory: str, extensions: List[str] = [".java"]
    ) -> Dict[str, int]:
        """
        Recursively index all files in a directory.

        Returns:
            Dict with stats: {total_files, total_symbols, files_by_extension}
        """
        stats = {
            "total_files": 0,
            "total_symbols": 0,
            "files_by_extension": defaultdict(int),
        }

        directory_path = Path(directory)

        for ext in extensions:
            for file_path in directory_path.rglob(f"*{ext}"):
                # Skip test files and generated code for cleaner index
                file_str = str(file_path)
                if "/test/" in file_str or "/build/generated/" in file_str:
                    continue

                print(f"Indexing: {file_path}")
                num_symbols = self.index_file(str(file_path))

                stats["total_files"] += 1
                stats["total_symbols"] += num_symbols
                stats["files_by_extension"][ext] += 1

        return stats

    def search_symbol(
        self, name: str, symbol_type: Optional[str] = None
    ) -> List[Symbol]:
        """Search for symbols by name (supports partial matching)."""
        results = []

        for symbol_name, symbol in self.symbols.items():
            # Match by symbol type if specified
            if symbol_type and symbol.type != symbol_type:
                continue

            # Partial name matching (case-insensitive)
            if name.lower() in symbol_name.lower():
                results.append(symbol)

        return results

    def get_class_symbols(self, class_name: str) -> Dict[str, List[Symbol]]:
        """Get all symbols (methods, fields) belonging to a class."""
        result = {"class": None, "methods": [], "fields": []}

        # Find the class
        if class_name in self.classes:
            result["class"] = self.classes[class_name]

        # Find all methods and fields with this parent
        for symbol in self.symbols.values():
            if symbol.parent == class_name:
                if symbol.type == "method":
                    result["methods"].append(symbol)
                elif symbol.type == "field":
                    result["fields"].append(symbol)

        return result

    def save_index(self, output_path: str):
        """Save index to JSON file."""
        index_data = {
            "symbols": {k: asdict(v) for k, v in self.symbols.items()},
            "files": self.files,
            "classes": {k: asdict(v) for k, v in self.classes.items()},
        }

        with open(output_path, "w") as f:
            json.dump(index_data, f, indent=2)

        print(f"\nIndex saved to: {output_path}")

    def load_index(self, index_path: str):
        """Load index from JSON file."""
        with open(index_path, "r") as f:
            index_data = json.load(f)

        # Reconstruct symbols
        self.symbols = {k: Symbol(**v) for k, v in index_data["symbols"].items()}
        self.files = index_data["files"]
        self.classes = {k: Symbol(**v) for k, v in index_data["classes"].items()}

        # Rebuild methods and fields indexes
        self.methods = defaultdict(list)
        self.fields = defaultdict(list)

        for symbol in self.symbols.values():
            if symbol.type == "method":
                method_name = symbol.name.split(".")[-1]
                self.methods[method_name].append(symbol)
            elif symbol.type == "field":
                field_name = symbol.name.split(".")[-1]
                self.fields[field_name].append(symbol)

        print(f"Index loaded: {len(self.symbols)} symbols from {len(self.files)} files")

    def get_stats(self) -> Dict:
        """Get indexing statistics."""
        return {
            "total_symbols": len(self.symbols),
            "total_files": len(self.files),
            "classes": len(self.classes),
            "methods": sum(len(v) for v in self.methods.values()),
            "fields": sum(len(v) for v in self.fields.values()),
        }

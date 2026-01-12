"""
Tree-sitter based code indexer for Java/Kotlin codebases.

Extracts symbols (classes, methods, fields) and builds a searchable index.
"""

import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional

import tree_sitter_java
import tree_sitter_kotlin
from tree_sitter import Language, Parser

from utils.logger import logger


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
        self.parser = Parser()
        self.java_language = Language(tree_sitter_java.language())
        self.kotlin_language = Language(tree_sitter_kotlin.language())
        self.parser.language = self.java_language

        self.symbols: Dict[str, Symbol] = {}  # symbol_name -> Symbol
        self.files: Dict[str, List[str]] = {}  # file_path -> [symbol_names]
        self.classes: Dict[str, Symbol] = {}  # class_name -> Symbol
        self.methods: Dict[str, List[Symbol]] = defaultdict(list)
        self.fields: Dict[str, List[Symbol]] = defaultdict(list)
        self.call_graph: Dict[str, List[str]] = defaultdict(list)  # caller -> [callees]

    def index_file(self, file_path: str) -> int:
        try:
            with open(file_path, "rb") as f:
                source_code = f.read()

            symbols_found = []

            if file_path.endswith(".kt"):
                self.parser.language = self.kotlin_language
                tree = self.parser.parse(source_code)
                root_node = tree.root_node
                self._extract_kotlin_symbols(
                    root_node, file_path, source_code, symbols_found
                )
            else:
                self.parser.language = self.java_language
                tree = self.parser.parse(source_code)
                root_node = tree.root_node
                self._extract_classes(root_node, file_path, source_code, symbols_found)

            # Store file mapping
            self.files[file_path] = [s.name for s in symbols_found]

            return len(symbols_found)

        except Exception as e:
            logger.error(f"Error indexing {file_path}: {e}")
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

                    # Extract method calls (Call Graph)
                    self._extract_method_calls(child, full_name, source_code)

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

    def _extract_method_calls(self, node, caller_name: str, source_code: bytes):
        """Recursively extract method calls from a method body."""
        if node.type == "method_invocation":
            method_name = None

            # Pattern: object.method() or method()
            for child in node.children:
                if child.type == "identifier":
                    method_name = source_code[child.start_byte : child.end_byte].decode(
                        "utf-8"
                    )
                elif child.type == "field_access":
                    # Extract from Obj.method
                    # field_access children: object, ., identifier
                    for fa_child in child.children:
                        if fa_child.type == "identifier":
                            # Last identifier is the method name
                            method_name = source_code[
                                fa_child.start_byte : fa_child.end_byte
                            ].decode("utf-8")

            if method_name:
                # Add edge to call graph
                # Optimistic linking: We store the simple name.
                # Later, the agent can resolve "foo" to "com.example.full.foo" locally.
                self.call_graph[caller_name].append(method_name)

        # Recurse
        for child in node.children:
            self._extract_method_calls(child, caller_name, source_code)

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

                logger.info(f"Indexing: {file_path}")
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
            "call_graph": self.call_graph,
        }

        with open(output_path, "w") as f:
            json.dump(index_data, f, indent=2)

        logger.info(f"Index saved to: {output_path}")

    def load_index(self, index_path: str):
        """Load index from JSON file."""
        with open(index_path, "r") as f:
            index_data = json.load(f)

        # Reconstruct symbols
        self.symbols = {k: Symbol(**v) for k, v in index_data["symbols"].items()}
        self.files = index_data["files"]
        self.classes = {k: Symbol(**v) for k, v in index_data["classes"].items()}
        self.call_graph = defaultdict(list, index_data.get("call_graph", {}))

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

        logger.info(
            f"Index loaded: {len(self.symbols)} symbols from {len(self.files)} files"
        )

    def get_stats(self) -> Dict:
        """Get indexing statistics."""
        return {
            "total_symbols": len(self.symbols),
            "total_files": len(self.files),
            "classes": len(self.classes),
            "methods": sum(len(v) for v in self.methods.values()),
            "fields": sum(len(v) for v in self.fields.values()),
        }

    def _extract_kotlin_symbols(
        self, node, file_path: str, source_code: bytes, symbols_found: List[Symbol]
    ):
        """Extract Kotlin symbols recursively."""

        if node.type == "class_declaration":
            class_name = None
            modifiers = []

            for child in node.children:
                if child.type == "identifier" or child.type == "type_identifier":
                    class_name = source_code[child.start_byte : child.end_byte].decode(
                        "utf-8"
                    )
                elif child.type == "modifiers":
                    modifiers = [
                        source_code[m.start_byte : m.end_byte].decode("utf-8")
                        for m in child.children
                    ]
                elif child.type == "class_body":
                    if class_name:
                        self._extract_kotlin_members(
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

        elif node.type == "object_declaration":
            obj_name = None
            for child in node.children:
                if child.type == "identifier":
                    obj_name = source_code[child.start_byte : child.end_byte].decode(
                        "utf-8"
                    )
                elif child.type == "class_body":
                    if obj_name:
                        self._extract_kotlin_members(
                            child, file_path, source_code, obj_name, symbols_found
                        )

            if obj_name:
                symbol = Symbol(
                    name=obj_name,
                    type="object",
                    file_path=file_path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                )
                self.symbols[obj_name] = symbol
                self.classes[obj_name] = symbol
                symbols_found.append(symbol)

        for child in node.children:
            self._extract_kotlin_symbols(child, file_path, source_code, symbols_found)

    def _extract_kotlin_members(
        self,
        body_node,
        file_path: str,
        source_code: bytes,
        parent: str,
        symbols_found: List[Symbol],
    ):
        for child in body_node.children:
            # Function
            if child.type == "function_declaration":
                func_name = None
                modifiers = []
                params = []

                for grand in child.children:
                    if grand.type == "identifier":
                        func_name = source_code[
                            grand.start_byte : grand.end_byte
                        ].decode("utf-8")
                    elif grand.type == "modifiers":
                        modifiers = [
                            source_code[m.start_byte : m.end_byte].decode("utf-8")
                            for m in grand.children
                        ]
                    elif grand.type == "function_value_parameters":
                        # Extract params: (a: Int, b: String)
                        for param in grand.children:
                            if param.type == "parameter":
                                # parameter -> identifier, user_type
                                p_type = None
                                for p_child in param.children:
                                    if (
                                        "type" in p_child.type
                                    ):  # user_type, nullable_type
                                        p_type = source_code[
                                            p_child.start_byte : p_child.end_byte
                                        ].decode("utf-8")
                                if p_type:
                                    params.append(p_type)

                if func_name:
                    full_name = f"{parent}.{func_name}"
                    symbol = Symbol(
                        name=full_name,
                        type="method",
                        file_path=file_path,
                        line_start=child.start_point[0] + 1,
                        line_end=child.end_point[0] + 1,
                        parent=parent,
                        modifiers=modifiers,
                        parameters=params,
                    )
                    self.symbols[full_name] = symbol
                    self.methods[func_name].append(symbol)
                    symbols_found.append(symbol)

                    # Call graph extraction for Kotlin
                    self._extract_kotlin_calls(child, full_name, source_code)

            # Property
            elif child.type == "property_declaration":
                # property_declaration -> variable_declaration -> identifier
                prop_name = None
                modifiers = []
                for grand in child.children:
                    if grand.type == "modifiers":
                        modifiers = [
                            source_code[m.start_byte : m.end_byte].decode("utf-8")
                            for m in grand.children
                        ]
                    elif grand.type == "variable_declaration":
                        for var_child in grand.children:
                            if var_child.type == "identifier":
                                prop_name = source_code[
                                    var_child.start_byte : var_child.end_byte
                                ].decode("utf-8")

                if prop_name:
                    full_name = f"{parent}.{prop_name}"
                    symbol = Symbol(
                        name=full_name,
                        type="field",
                        file_path=file_path,
                        line_start=child.start_point[0] + 1,
                        line_end=child.end_point[0] + 1,
                        parent=parent,
                        modifiers=modifiers,
                    )
                    self.symbols[full_name] = symbol
                    self.fields[prop_name].append(symbol)
                    symbols_found.append(symbol)

    def _extract_kotlin_calls(self, node, caller_name: str, source_code: bytes):
        """Extract function calls from Kotlin body."""
        # navigation_expression (obj.method) or call_expression (method())
        # This is simplified; Kotlin AST is complex
        if node.type == "call_expression":
            # call_expression -> identifier/navigation_expression -> ...
            callee = None
            for child in node.children:
                if child.type == "identifier":
                    callee = source_code[child.start_byte : child.end_byte].decode(
                        "utf-8"
                    )
                elif child.type == "navigation_expression":
                    # obj.method
                    # last child is usually the selector (method name)
                    if child.children:
                        last = child.children[-1]
                        if last.type == "navigation_suffix":
                            # navigation_suffix -> simple_identifier
                            callee = (
                                source_code[last.start_byte : last.end_byte]
                                .decode("utf-8")
                                .lstrip(".")
                            )

            if callee:
                self.call_graph[caller_name].append(callee)

        for child in node.children:
            self._extract_kotlin_calls(child, caller_name, source_code)

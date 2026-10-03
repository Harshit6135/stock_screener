"""Recursive import rules for the target domain and gate boundaries."""

import ast
from importlib.util import resolve_name
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
DOMAIN_ROOT = SOURCE_ROOT / "domains"
KERNEL_ROOT = SOURCE_ROOT / "platform_kernel"
GATE_ROOT = SOURCE_ROOT / "gates"
LEGACY_SOURCE_ROOTS = (
    "src.application",
    "src.execution_gateway",
    "src.indicators",
    "src.strategies",
)

# These are known transitional seams, tracked by exact file and import. Remove
# each entry when its owner moves; broad package or domain exemptions are not
# allowed.
TEMPORARY_IMPORT_ALLOWLIST = {}

KERNEL_FORBIDDEN_ROOTS = {
    "flask",
    "sqlalchemy",
    "kiteconnect",
    "yfinance",
    "waitress",
}


def _module_name(path: Path) -> str:
    parts = path.relative_to(SOURCE_ROOT).with_suffix("").parts
    return "src." + ".".join(parts)


def _import_target(node: ast.AST, current_module: str) -> str | None:
    if isinstance(node, ast.Import):
        return None
    if not isinstance(node, ast.ImportFrom):
        return None
    if node.level:
        package = current_module.rpartition(".")[0]
        relative_name = "." * node.level + (node.module or "")
        return resolve_name(relative_name, package)
    return node.module


def _domain_owner(module_name: str) -> str | None:
    parts = module_name.split(".")
    return parts[2] if len(parts) >= 3 and parts[:2] == ["src", "domains"] else None


def _is_package_or_child(module_name: str, package: str) -> bool:
    return module_name == package or module_name.startswith(f"{package}.")


def _boundary_violation(layer: str, module_name: str, target: str) -> str | None:
    if layer == "domain":
        owner = _domain_owner(module_name)
        if any(
            _is_package_or_child(target, package)
            for package in ("run", "src.application", "src.gates")
        ):
            return f"domain imports application layer {target}"
        if target.startswith("src.domains.") and _domain_owner(target) != owner:
            return f"domain {owner} imports another domain {target}"
        if target.startswith("src.") and not any(
            _is_package_or_child(target, package)
            for package in ("src.platform_kernel", "src.domains")
        ):
            return f"domain imports legacy/internal package {target}"
    elif layer == "kernel":
        if any(_is_package_or_child(target, package) for package in ("run", "src")) and not (
            _is_package_or_child(target, "src.platform_kernel")
        ):
            return f"platform kernel imports application/domain package {target}"
    elif layer == "gate":
        if target.startswith("src.domains."):
            parts = target.split(".")
            if len(parts) > 4 or (len(parts) == 4 and parts[3] != "api"):
                return f"gate imports non-public domain module {target}"
        if any(_is_package_or_child(target, root) for root in LEGACY_SOURCE_ROOTS):
            return f"gate imports a legacy application/domain implementation {target}"
    return None


def _tree_imports(tree: ast.AST, current_module: str) -> list[tuple[str, ast.AST]]:
    found: list[tuple[str, ast.AST]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((alias.name, node) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            target = _import_target(node, current_module)
            if target:
                found.append((target, node))
    return found


def _dynamic_imports(tree: ast.AST) -> list[ast.Call]:
    imported_names = {"import_module"}
    importlib_names = {"importlib"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "importlib":
                    importlib_names.add(alias.asname or "importlib")
        elif isinstance(node, ast.ImportFrom) and node.module == "importlib":
            for alias in node.names:
                if alias.name == "import_module":
                    imported_names.add(alias.asname or alias.name)

    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        is_dynamic = isinstance(node.func, ast.Name) and node.func.id in {
            "__import__",
            *imported_names,
        }
        is_dynamic = is_dynamic or (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "import_module"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in importlib_names
        )
        if is_dynamic:
            calls.append(node)
    return calls


def _check_file(path: Path, layer: str) -> tuple[list[str], set[tuple[str, str]]]:
    relative_path = path.relative_to(SOURCE_ROOT).as_posix()
    current_module = _module_name(path)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[str] = []
    observed_allowlist: set[tuple[str, str]] = set()
    for target, node in _tree_imports(tree, current_module):
        allowlist_key = (relative_path, target)
        if allowlist_key in TEMPORARY_IMPORT_ALLOWLIST:
            observed_allowlist.add(allowlist_key)
            continue
        reason = _boundary_violation(layer, current_module, target)
        if layer == "kernel" and target.split(".")[0] in KERNEL_FORBIDDEN_ROOTS:
            reason = f"platform kernel imports framework/provider package {target}"
        if reason:
            violations.append(f"{relative_path}:{node.lineno} imports {target}: {reason}")
    if layer in {"domain", "kernel", "gate"}:
        for call in _dynamic_imports(tree):
            argument = call.args[0] if call.args else None
            if not isinstance(argument, ast.Constant) or not isinstance(argument.value, str):
                violations.append(
                    f"{relative_path}:{call.lineno} has an unauditable dynamic import"
                )
            else:
                reason = _boundary_violation(layer, current_module, argument.value)
                if reason:
                    violations.append(
                        f"{relative_path}:{call.lineno} dynamically imports {argument.value}: {reason}"
                    )
    return violations, observed_allowlist


def _check_source_roots() -> tuple[list[str], set[tuple[str, str]]]:
    violations: list[str] = []
    observed_allowlist: set[tuple[str, str]] = set()
    files = [
        *((path, "domain") for path in DOMAIN_ROOT.rglob("*.py")),
        *((path, "kernel") for path in KERNEL_ROOT.rglob("*.py")),
        *((path, "gate") for path in GATE_ROOT.rglob("*.py")),
    ]
    for path, layer in files:
        file_violations, observed = _check_file(path, layer)
        violations.extend(file_violations)
        observed_allowlist.update(observed)
    return violations, observed_allowlist


def check_recursive_domain_kernel_and_gate_import_boundaries():
    violations, observed_allowlist = _check_source_roots()
    assert not violations, "\n".join(violations)
    assert observed_allowlist == set(TEMPORARY_IMPORT_ALLOWLIST), (
        "Update the exact temporary import allowlist; missing/stale entries: "
        f"{set(TEMPORARY_IMPORT_ALLOWLIST) ^ observed_allowlist}"
    )


def check_boundary_rules_detect_cross_domain_and_private_module_imports():
    market_module = "src.domains.market_data.reader"
    assert (
        _boundary_violation("domain", market_module, "src.domains.reference_data.api") is not None
    )
    assert (
        _boundary_violation("domain", market_module, "src.application.market_repository")
        is not None
    )
    assert _boundary_violation("gate", "src.gates.app", "src.application.composition") is not None
    assert (
        _boundary_violation(
            "gate", "src.gates.workflows.market", "src.domains.market_data.repository"
        )
        is not None
    )
    assert (
        _boundary_violation("gate", "src.gates.workflows.market", "src.domains.market_data.api")
        is None
    )


def check_relative_and_type_checking_imports_are_in_ast_scan():
    source = ast.parse(
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from ..reference_data.api import InstrumentReader\n"
    )
    imports = _tree_imports(source, "src.domains.market_data.reader")
    assert ("src.domains.reference_data.api", source.body[1].body[0]) in imports
    assert (
        _boundary_violation("domain", "src.domains.market_data.reader", imports[-1][0]) is not None
    )


def check_dynamic_imports_are_audited_for_hidden_dependency_edges():
    static_import = ast.parse(
        "import importlib\nimportlib.import_module('src.domains.reference_data.repository')\n"
    )
    dynamic_import = ast.parse(
        "from importlib import import_module as load_module\nload_module(runtime_module)\n"
    )
    calls = _dynamic_imports(static_import)
    assert len(calls) == 1
    assert (
        _boundary_violation("gate", "src.gates.workflows.market", calls[0].args[0].value)
        is not None
    )
    assert len(_dynamic_imports(dynamic_import)) == 1


def main() -> int:
    check_recursive_domain_kernel_and_gate_import_boundaries()
    check_boundary_rules_detect_cross_domain_and_private_module_imports()
    check_relative_and_type_checking_imports_are_in_ast_scan()
    check_dynamic_imports_are_audited_for_hidden_dependency_edges()
    print("Import-boundary checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

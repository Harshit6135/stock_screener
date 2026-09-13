"""Architecture rules for framework-free domain packages."""

import ast
from pathlib import Path

DOMAIN_PACKAGES = {
    "platform_kernel",
    "portfolio_engine",
    "portfolio_accounting",
    "reference_data",
    "market_data",
    "indicators",
    "strategies",
    "backtesting",
}
FORBIDDEN_ROOTS = {
    "flask",
    "sqlalchemy",
    "kiteconnect",
    "yfinance",
    "db",
    "models",
    "repositories",
    "services",
}


def test_domain_packages_do_not_depend_on_framework_or_legacy_layers():
    source_root = Path(__file__).parents[1] / "src"
    violations: list[str] = []
    for package in DOMAIN_PACKAGES:
        for file in (source_root / package).glob("*.py"):
            tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    roots = [name.name.split(".")[0] for name in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    roots = [node.module.split(".")[0]]
                    if node.module.startswith("src.") and node.module.count(".") > 1:
                        violations.append(
                            f"{file.relative_to(source_root)} imports internal module {node.module}"
                        )
                else:
                    continue
                for root in roots:
                    if root in FORBIDDEN_ROOTS:
                        violations.append(f"{file.relative_to(source_root)} imports {root}")
    assert not violations, "\n".join(violations)

"""Dev/test tooling for rosbagger (NOT shipped in any package's runtime path).

This package exists so the fixture-bag generator can be imported by the test
suite (``from tools.make_fixtures import make_all_fixtures``) and run as a
module (``python -m tools.make_fixtures``). It is intentionally outside the
``rosbagger_core`` / ``bagq`` shipped namespaces — fixtures are a dev artifact,
not a product feature, and ``tools`` is not a runtime dependency of either
package.
"""

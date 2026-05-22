"""Enable ``python -m bagq`` to run the same typer app as the ``bagq`` console script.

The ``[project.scripts]`` entry point (``bagq = "bagq.cli:app"``) already puts a ``bagq``
launcher on ``PATH``, but ``python -m bagq`` is the PATH-independent invocation: it runs
under a known interpreter (``sys.executable -m bagq``), which is what the CLI-01 real-shell
smoke test uses so it never depends on the console script being resolvable on ``PATH``.
"""

from bagq.cli import app

if __name__ == "__main__":
    app()

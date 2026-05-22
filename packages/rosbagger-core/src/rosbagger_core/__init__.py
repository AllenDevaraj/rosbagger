"""rosbagger-core: the pure-Python, offline ROS-bag library.

Keep this module light: do NOT import the heavy stack (duckdb, pyarrow,
sqlglot, rosbags) at top level. Defer those into the functions that use them
(landing in later phases) so the offline-import guard test stays fast and
`bagq --help` does not pay the duckdb import cost.
"""

__version__ = "0.0.0"

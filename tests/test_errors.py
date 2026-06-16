"""Unit tests for the stdlib-only typed errors (``rosbagger_core.errors``).

These prove the three "errors that teach" CARRY their data and build the right
teaching message, independent of the CLI or any bag (the API-first split — the data
lives in core, the CLI only presents):

* ``UnknownTableError`` (CLI-02) — difflib did-you-mean when a close table exists,
  else the available-tables list, else a no-tables note; carries name/available/suggestions.
* ``UnknownColumnError`` (CLI-03) — the offending column, a did-you-mean over all
  columns, and one ``Columns in <table>`` line per referenced table.
* ``UnresolvedTypeError`` (CLI-04) — registration guidance naming get_types_from_msg /
  .idl / register / default_typestore.

The back-compat re-export identity (``backend.query.UnknownTableError is
errors.UnknownTableError``) is asserted here too, so any existing importer keeps
catching the SAME class.
"""

from __future__ import annotations

from rosbagger_core.errors import (
    UnknownColumnError,
    UnknownTableError,
    UnresolvedTypeError,
)


class TestUnknownTableError:
    """CLI-02: did-you-mean / available-tables / no-tables + carried data."""

    def test_close_match_yields_did_you_mean(self) -> None:
        err = UnknownTableError("cmdvel", ["cmd_vel", "imu", "image"])
        assert "Did you mean" in str(err)
        assert "cmd_vel" in str(err)

    def test_no_close_match_lists_available_without_false_suggestion(self) -> None:
        err = UnknownTableError("wxyz123", ["cmd_vel", "imu"])
        assert "Available tables" in str(err)
        assert "cmd_vel" in str(err)
        assert "imu" in str(err)
        assert "Did you mean" not in str(err)  # no false suggestion when difflib returns []

    def test_empty_available_states_no_queryable_tables(self) -> None:
        err = UnknownTableError("foo", [])
        assert "no queryable tables" in str(err)

    def test_carries_structured_attributes(self) -> None:
        err = UnknownTableError("cmdvel", ["cmd_vel", "imu"])
        assert err.name == "cmdvel"
        assert err.available == ["cmd_vel", "imu"]
        assert "cmd_vel" in err.suggestions  # data-carrying, not just a string

    def test_is_value_error_for_back_compat(self) -> None:
        assert isinstance(UnknownTableError("x", []), ValueError)

    def test_reexport_identity_holds(self) -> None:
        """``backend.query.UnknownTableError`` IS ``errors.UnknownTableError`` (same object)."""
        from rosbagger_core.backend.query import UnknownTableError as FromQuery
        from rosbagger_core.errors import UnknownTableError as FromErrors

        assert FromQuery is FromErrors


class TestUnknownColumnError:
    """CLI-03: offending column + did-you-mean + per-table column list + carried data."""

    def test_message_lists_offending_column_and_table_columns(self) -> None:
        err = UnknownColumnError(
            "linearx",
            {"cmd_vel": ["t", "t_ns", "stamp", "topic", "linear.x", "linear.y"]},
        )
        assert "Unknown column 'linearx'" in str(err)
        assert "Did you mean" in str(err)  # 'linear.x' is a close match
        assert "Columns in cmd_vel:" in str(err)
        assert "linear.x" in str(err)

    def test_carries_structured_attributes(self) -> None:
        cols = {"cmd_vel": ["t", "topic", "linear.x"]}
        err = UnknownColumnError("linearx", cols)
        assert err.column == "linearx"
        assert err.columns_by_table == cols

    def test_multi_table_lists_all_referenced_tables(self) -> None:
        err = UnknownColumnError(
            "foo",
            {"cmd_vel": ["linear.x"], "imu": ["angular_velocity.z"]},
        )
        assert "Columns in cmd_vel:" in str(err)
        assert "Columns in imu:" in str(err)

    def test_suggestions_deduped_across_joined_tables(self) -> None:
        """A column shared across JOINed tables is suggested ONCE (no duplicate did-you-means).

        Regression: ``all_cols`` concatenated every table's columns, so a shared name
        (``header.stamp.sec``) appeared twice and difflib returned it twice — crowding out
        distinct near-misses within the n=3 budget. The order-preserving dedup fixes it.
        """
        err = UnknownColumnError(
            "header.stamp.sek",  # a near-miss of the shared header.stamp.sec
            {
                "imu": ["header.stamp.sec", "header.stamp.nanosec", "angular_velocity.z"],
                "image": ["header.stamp.sec", "header.stamp.nanosec", "height"],
            },
        )
        assert err.suggestions.count("header.stamp.sec") == 1
        # The whole suggestion list is distinct (no duplicate anywhere).
        assert len(err.suggestions) == len(set(err.suggestions))

    def test_is_value_error(self) -> None:
        assert isinstance(UnknownColumnError("c", {"t": ["a"]}), ValueError)


class TestUnresolvedTypeError:
    """CLI-04: registration guidance + carried detail."""

    def test_message_has_registration_guidance(self) -> None:
        err = UnresolvedTypeError()
        msg = str(err)
        assert "no embedded message definitions" in msg
        assert "register" in msg
        assert "get_types_from_msg" in msg
        assert "idl" in msg  # names .idl too (get_types_from_idl)

    def test_carries_detail_attribute(self) -> None:
        err = UnresolvedTypeError("Bag contains no type definitions.")
        assert err.detail == "Bag contains no type definitions."
        assert "Bag contains no type definitions." in str(err)

    def test_empty_detail_still_gives_guidance(self) -> None:
        err = UnresolvedTypeError()
        assert err.detail == ""
        assert "default_typestore" in str(err)

    def test_is_value_error(self) -> None:
        assert isinstance(UnresolvedTypeError(), ValueError)

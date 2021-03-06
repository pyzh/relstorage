##############################################################################
#
# Copyright (c) 2009 Zope Foundation and Contributors.
# All Rights Reserved.
#
# This software is subject to the provisions of the Zope Public License,
# Version 2.1 (ZPL).  A copy of the ZPL should accompany this distribution.
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE.
#
##############################################################################
"""Batch table row insert/delete support.
"""

from relstorage._compat import itervalues, iteritems
from collections import defaultdict

class RowBatcher(object):
    """
    Generic row batcher.

    Expects '%s' parameters and a tuple for each row.
    """

    row_limit = 100
    size_limit = 1 << 20

    def __init__(self, cursor, row_limit=None):
        self.cursor = cursor
        if row_limit is not None:
            self.row_limit = row_limit
        self.rows_added = 0
        self.size_added = 0
        self.deletes = defaultdict(set)   # {(table, columns_tuple): set([(column_value,)])}
        self.inserts = defaultdict(dict)  # {(command, header, row_schema, suffix): {rowkey: [row]}}

    def delete_from(self, table, **kw):
        """
        .. caution:: The keyword values must have a valid str representation.
        """
        if not kw:
            raise AssertionError("Need at least one column value")
        columns = tuple(sorted(kw))
        key = (table, columns)
        rows = self.deletes[key]
        # string conversion in done by _do_deletes
        row = tuple(kw[column] for column in columns)
        rows.add(row)
        self.rows_added += 1
        if self.rows_added >= self.row_limit:
            self.flush()

    def insert_into(self, header, row_schema, row, rowkey, size,
                    command='INSERT', suffix=''):
        key = (command, header, row_schema, suffix)
        rows = self.inserts[key]
        rows[rowkey] = row  # note that this may replace a row
        self.rows_added += 1
        self.size_added += size
        if (self.rows_added >= self.row_limit
                or self.size_added >= self.size_limit):
            self.flush()

    def flush(self):
        if self.deletes:
            self._do_deletes()
            self.deletes.clear()
        if self.inserts:
            self._do_inserts()
            self.inserts.clear()
        self.rows_added = 0
        self.size_added = 0

    def _do_deletes(self):
        for (table, columns), rows in sorted(iteritems(self.deletes)):
            # XXX: Stop doing string conversion manually. Let the
            # cursor do it. It may have a non-text protocol for integer
            # objects; it may also have a different representation in text.
            if len(columns) == 1:
                value_str = ','.join(str(v) for (v,) in rows)
                stmt = "DELETE FROM %s WHERE %s IN (%s)" % (
                    table, columns[0], value_str)
            else:
                lines = []
                for row in rows:
                    line = []
                    for i, column in enumerate(columns):
                        line.append("%s = %s" % (column, row[i]))
                    lines.append(" AND ".join(line))
                stmt = "DELETE FROM %s WHERE %s" % (
                    table, " OR ".join(lines))

            self.cursor.execute(stmt)

    def _do_inserts(self):
        items = sorted(iteritems(self.inserts))
        for (command, header, row_schema, suffix), rows in items:
            # Batched inserts
            parts = []
            params = []
            s = "(%s)" % row_schema
            for row in itervalues(rows):
                parts.append(s)
                params.extend(row)

            stmt = "%s INTO %s VALUES\n%s\n%s" % (
                command, header, ',\n'.join(parts), suffix)
            # e.g.,
            # INSERT INTO table(c1, c2)
            # VALUES (%s, %s), (%s, %s), (%s, %s)
            # <suffix>
            self.cursor.execute(stmt, tuple(params))

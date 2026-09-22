"""PyMySQL stands in for the MySQL driver.

Shared cPanel hosting has no compiler, so `mysqlclient` (which builds C
extensions) usually fails to install there. PyMySQL is pure Python and presents
itself to Django as the same driver.
"""

try:
    import pymysql

    pymysql.install_as_MySQLdb()
except ImportError:  # local development on SQLite does not need it
    pass

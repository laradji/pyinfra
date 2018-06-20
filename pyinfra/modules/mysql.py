# pyinfra
# File: pyinfra/modules/mysql.py
# Desc: manage MySQL databases/users/permissions

'''
Manage MySQL databases, users and permissions.

Requires the ``mysql`` CLI executable on the target host(s).
'''

import six

from pyinfra.api import operation
from pyinfra.facts.mysql import make_execute_mysql_command, make_mysql_command


@operation
def sql(
    state, host, sql,
    database=None,
    # Details for speaking to MySQL via `mysql` CLI
    mysql_user=None, mysql_password=None,
    mysql_host=None, mysql_port=None,
):
    '''
    Execute arbitrary SQL against MySQL.

    + sql: the SQL to send to MySQL
    + database: optional database to open the connection with
    + mysql_user: the username to connect to mysql with (defaults to current user)
    + mysql_password: the password to use when connecting to mysql
    '''

    yield make_execute_mysql_command(
        sql,
        database=database,
        user=mysql_user,
        password=mysql_password,
        host=mysql_host,
        port=mysql_port,
    )


@operation
def user(
    state, host, name,
    # Desired user settings
    present=True,
    user_hostname='localhost', password=None, permissions=None,
    # Details for speaking to MySQL via `mysql` CLI via `mysql` CLI
    mysql_user=None, mysql_password=None,
    mysql_host=None, mysql_port=None,
):
    '''
    Manage the state of MySQL users.

    + name: the name of the user
    + present: whether the user should exist or not
    + user_hostname: the hostname of the user
    + password: the password of the user (if created)
    + permissions: the global permissions for this user
    + mysql_user: the username to connect to mysql with (defaults to current user)
    + mysql_password: the password to use when connecting to mysql

    Hostname:
        this + ``name`` makes the username - so changing this will create a new
        user, rather than update users with the same ``name``.

    Password:
        will only be applied if the user does not exist - ie pyinfra cannot
        detect if the current password doesn't match the one provided, so won't
        attempt to change it.
    '''

    current_users = host.fact.mysql_users(
        mysql_user, mysql_password, mysql_host, mysql_port,
    )

    user_host = '{0}@{1}'.format(name, user_hostname)
    is_present = user_host in current_users

    # User not wanted?
    if not present:
        if is_present:
            yield make_execute_mysql_command(
                'DROP USER "{0}"@"{1}"'.format(name, user_hostname),
                user=mysql_user,
                password=mysql_password,
                host=mysql_host,
                port=mysql_port,
            )
        return

    # If we want the user and they don't exist
    if present and not is_present:
        sql_bits = ['CREATE USER "{0}"@"{1}"'.format(name, user_hostname)]
        if password:
            sql_bits.append('IDENTIFIED BY "{0}"'.format(password))

        yield make_execute_mysql_command(
            ' '.join(sql_bits),
            user=mysql_user,
            password=mysql_password,
            host=mysql_host,
            port=mysql_port,
        )

    # If we're here either the user exists or we just created them; either way
    # now we can check any permissions are set.
    if permissions:
        yield permission(
            state, host, name, permissions,
            mysql_user=mysql_user, mysql_password=mysql_password,
            mysql_host=mysql_host, mysql_port=mysql_port,
        )


@operation
def database(
    state, host, name,
    # Desired database settings
    present=True,
    collate=None, charset=None,
    user=None, user_hostname='localhost', user_permissions='ALL',
    # Details for speaking to MySQL via `mysql` CLI
    mysql_user=None, mysql_password=None,
    mysql_host=None, mysql_port=None,
):
    '''
    Manage the state of MySQL databases.

    + name: the name of the database
    + present: whether the database should exist or not
    + collate: the collate to use when creating the database
    + charset: the charset to use when creating the database
    + user: MySQL user to grant privileges on this database to
    + user_hostname: the hostname of the MySQL user to grant
    + user_permissions: permissions to grant to any specified user
    + mysql_user: the username to connect to mysql with (defaults to current user)
    + mysql_password: the password to use when connecting to mysql

    Collate/charset:
        these will only be applied if the database does not exist - ie pyinfra
        will not attempt to alter the existing databases collate/character sets.
    '''

    current_databases = host.fact.mysql_databases(
        mysql_user, mysql_password,
        mysql_host, mysql_port,
    )

    is_present = name in current_databases

    if not present:
        if is_present:
            yield make_execute_mysql_command(
                'DROP DATABASE {0}'.format(name),
                user=mysql_user,
                password=mysql_password,
                host=mysql_host,
                port=mysql_port,
            )
        return

    # We want the database but it doesn't exist
    if present and not is_present:
        sql_bits = ['CREATE DATABASE {0}'.format(name)]

        if collate:
            sql_bits.append('COLLATE {0}'.format(collate))

        if charset:
            sql_bits.append('CHARSET {0}'.format(charset))

        yield make_execute_mysql_command(
            ' '.join(sql_bits),
            user=mysql_user,
            password=mysql_password,
            host=mysql_host,
            port=mysql_port,
        )

    # Ensure any user permissions for this database
    if user and user_permissions:
        yield permission(
            state, host, user,
            user_hostname=user_hostname,
            permissions=user_permissions,
            database=name,
        )


@operation
def permission(
    state, host,
    user, permissions,
    user_hostname='localhost',
    database='*', table='*',
    present=True,
    flush=True,
    # Details for speaking to MySQL via `mysql` CLI
    mysql_user=None, mysql_password=None,
    mysql_host=None, mysql_port=None,
):
    '''
    Manage MySQL permissions for a user, either global, database or table specific.

    + user: name of the user to manage permissions for
    + permissions: list of permissions the user should have
    + user_hostname: the hostname of the user
    + database: name of the database to grant user permissions to (defaults to all)
    + table: name of the table to grant user permissions to (defaults to all)
    + present: whether these permissions should exist (False to ``REVOKE)
    + flush: whether to flush (and update) the permissions table after any changes
    + mysql_user: the username to connect to mysql with (defaults to current user)
    + mysql_password: the password to use when connecting to mysql
    '''

    # Ensure we have a list
    if isinstance(permissions, six.string_types):
        permissions = [permissions]

    if database != '*':
        database = '`{0}`'.format(database)

    if table != '*':
        table = '`{0}`'.format(table)

    database_table = '{0}.{1}'.format(database, table)
    user_grants = host.fact.mysql_user_grants(
        user, user_hostname,
        mysql_user, mysql_password,
        mysql_host, mysql_port,
    )

    existing_permissions = [
        'ALL' if permission == 'ALL PRIVILEGES' else permission
        for permission in user_grants[database_table]['permissions']
    ]

    has_permissions = (
        database_table in user_grants
        and all(
            permission in existing_permissions
            for permission in permissions
        )
    )

    target = action = None

    # No permission and we want it
    if not has_permissions and present:
        action = 'GRANT'
        target = 'TO'

    # Permission we don't want
    elif has_permissions and not present:
        action = 'REVOKE'
        target = 'FROM'

    if target and action:
        command = (
            '{action} {permissions} '
            'ON {database}.{table} '
            '{target} "{user}"@"{user_hostname}" '
        ).format(
            permissions=', '.join(permissions),
            action=action, target=target,
            database=database, table=table,
            user=user, user_hostname=user_hostname,
        ).replace('`', '\`')

        yield make_execute_mysql_command(
            command,
            user=mysql_user,
            password=mysql_password,
            host=mysql_host,
            port=mysql_port,
        )

        if flush:
            yield make_execute_mysql_command(
                'FLUSH PRIVILEGES',
                user=mysql_user,
                password=mysql_password,
                host=mysql_host,
                port=mysql_port,
            )


@operation
def dump(
    state, host,
    database, remote_filename,
    gzip=False,
    # Details for speaking to MySQL via `mysql` CLI
    mysql_user=None, mysql_password=None,
    mysql_host=None, mysql_port=None,
):
    '''
    Dump a MySQL database into a ``.sql`` file. Requires ``mysqldump``.
    '''

    yield '{0} > {1}'.format(make_mysql_command(
        executable='mysqldump',
        database=database,
        user=mysql_user,
        password=mysql_password,
        host=mysql_host,
        port=mysql_port,
    ), remote_filename)


@operation
def load(
    state, host,
    database, remote_filename,
    # Details for speaking to MySQL via `mysql` CLI
    mysql_user=None, mysql_password=None,
    mysql_host=None, mysql_port=None,
):
    '''
    Load ``.sql`` file into a database.
    '''

    yield '{0} < {1}'.format(make_mysql_command(
        database=database,
        user=mysql_user,
        password=mysql_password,
        host=mysql_host,
        port=mysql_port,
    ), remote_filename)

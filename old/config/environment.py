"""Pylons environment configuration"""
import os, re

from mako.lookup import TemplateLookup
from pylons.configuration import PylonsConfig
from pylons.error import handle_mako_error
from sqlalchemy import engine_from_config

import old.lib.app_globals as app_globals
import old.lib.helpers
from old.config.routing import make_map
from old.model import init_model

def load_environment(global_conf, app_conf):
    """Configure the Pylons environment via the ``pylons.config``
    object
    """
    config = PylonsConfig()
    
    # Pylons paths
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    paths = dict(root=root,
                 controllers=os.path.join(root, 'controllers'),
                 static_files=os.path.join(root, 'public'),
                 templates=[os.path.join(root, 'templates')])

    # Initialize config with the basic options
    config.init_app(global_conf, app_conf, package='old', paths=paths)

    config['routes.map'] = make_map(config)
    config['pylons.app_globals'] = app_globals.Globals(config)
    config['pylons.h'] = old.lib.helpers
    
    # Setup cache object as early as possible
    import pylons
    pylons.cache._push_object(config['pylons.app_globals'].cache)

    # Create the Mako TemplateLookup, with the default auto-escaping
    # TODO: SAFELY REMOVE THIS
    config['pylons.app_globals'].mako_lookup = TemplateLookup(
        directories=paths['templates'],
        error_handler=handle_mako_error,
        module_directory=os.path.join(app_conf['cache_dir'], 'templates'),
        input_encoding='utf-8', default_filters=['escape'],
        imports=['from webhelpers.html import escape'])

    engine = engine_from_config(config, 'sqlalchemy.')

    # CONFIGURATION OPTIONS HERE (note: all config options will override
    # any Pylons config options)

    # Patch the SQLAlchemy database engine if SQLite is the RDBMS.  Add a REGEXP
    # function and make LIKE searches case-sensitive.
    RDBMSName = config['sqlalchemy.url'].split(':')[0]
    app_globals.RDBMSName = RDBMSName
    if RDBMSName == 'sqlite':
        # Try to use the event API of SQLA>=0.7; otherwise use a PoolListener a l SQLA ca. 0.5.8
        try:
            from sqlalchemy import event
            from sqlalchemy.engine import Engine
            @event.listens_for(Engine, 'connect')
            def sqlite_patches(dbapi_connection, connection_record):
                # Define a regexp function for SQLite,
                def regexp(expr, item):
                    """This is the Python re-based regexp function that we provide
                    for SQLite.  Note that searches will be case-sensitive by
                    default.  Such behaviour is assured in MySQL by inserting
                    COLLATE expressions into the query (cf. in SQLAQueryBuilder.py).
                    """
                    patt = re.compile(expr)
                    try:
                        return item and patt.search(item) is not None
                    # This will make regexp searches work on int, date & datetime fields.
                    except TypeError:
                        return item and patt.search(str(item)) is not None
                dbapi_connection.create_function('regexp', 2, regexp)
                # Make LIKE searches case-sensitive in SQLite.
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA case_sensitive_like=ON")
                cursor.close()
        except ImportError:
            from sqlalchemy.interfaces import PoolListener
            engine = engine_from_config(
                config, 'sqlalchemy.', listeners=[SQLiteSetup()])
            # Make LIKE searches case sensitive in SQLite
            engine.execute('PRAGMA case_sensitive_like=ON')        
            class SQLiteSetup(PoolListener):
                """A PoolListener used to provide the SQLite dbapi with a regexp function.
                """
                def connect(self, conn, conn_record):
                    conn.create_function('regexp', 2, self.regexp)
            
                def regexp(self, expr, item):
                    """This is the Python re-based regexp function that we provide for SQLite.
                    Note that searches will be case-sensitive by default, which may not be
                    the default for the MySQL regexp, depending on the collation."""
                    patt = re.compile(expr)
                    try:
                        return item and patt.search(item) is not None
                    # This will make regexp searches work on int, date & datetime fields.
                    # I think this is desirable ...
                    except TypeError:
                        return item and patt.search(str(item)) is not None

    init_model(engine)
    return config
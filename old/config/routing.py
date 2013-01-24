"""Routes configuration

The more specific and detailed routes should be defined first so they
may take precedent over the more generic routes. For more information
refer to the routes manual at http://routes.groovie.org/docs/
"""

from routes import Mapper

def searchConnect(map, name, controller=None):
    controller = controller or name
    map.connect(name, '/%s' % name, controller=controller,
        action='search', conditions=dict(method='SEARCH'))
    map.connect('/%s/new_search' % name, controller=controller,
                action='new_search', conditions=dict(method='GET'))
    return map

def make_map(config):
    """Create, configure and return the routes Mapper"""
    map = Mapper(directory=config['pylons.paths']['controllers'],
                 always_scan=config['debug'])
    map.minimization = False
    map.explicit = False

    # The ErrorController route (handles 404/500 error pages); it should
    # likely stay at the top, ensuring it can always be resolved
    map.connect('/error/{action}', controller='error')
    map.connect('/error/{action}/{id}', controller='error')

    # CUSTOM ROUTES HERE
    map.connect('/forms/update_morpheme_references', controller='forms',
            action='update_morpheme_references', conditions=dict(method='PUT'))

    # SEARCH routes
    map = searchConnect(map, 'forms')
    map = searchConnect(map, 'files')
    map = searchConnect(map, 'collections', 'oldcollections')
    map.connect('/collections/search', controller='oldcollections', action='search')
    map = searchConnect(map, 'sources')
    map = searchConnect(map, 'collectionbackups')
    map = searchConnect(map, 'formbackups')
    map = searchConnect(map, 'languages')
    map = searchConnect(map, 'formsearches')

    # rememberedforms "resource"
    map.connect("rememberedforms", "/rememberedforms/{id}",
        controller="rememberedforms", action="show",
        conditions=dict(method=["GET"]))
    map.connect("/rememberedforms/{id}",
        controller="rememberedforms", action="update",
        conditions=dict(method=["PUT"]))
    map.connect("rememberedforms", "/rememberedforms/{id}",
        controller='rememberedforms', action='search',
        conditions=dict(method='SEARCH'))

    # RESTful resoure mappings
    map.resource('applicationsetting', 'applicationsettings')
    map.resource('collection', 'collections', controller='oldcollections')
    map.resource('collectionbackup', 'collectionbackups')       # read-only
    map.resource('elicitationmethod', 'elicitationmethods')
    map.resource('file', 'files')
    map.resource('form', 'forms')
    map.resource('formsearch', 'formsearches')
    map.resource('formbackup', 'formbackups')       # read-only
    map.resource('gloss', 'glosses')                # read-only
    map.resource('language', 'languages')           # read-only
    map.resource('orthography', 'orthographies')
    map.resource('page', 'pages')
    map.resource('phonology', 'phonologies')
    map.resource('source', 'sources')
    map.resource('speaker', 'speakers')
    map.resource('syntacticcategory', 'syntacticcategories')
    map.resource('tag', 'tags')
    map.resource('user', 'users')

    # Map '/collections' to oldcollections controller (conflict with Python
    # collections module).
    map.connect('collections', controller='oldcollections')

    # Pylons Defaults
    map.connect('/{controller}/{action}')
    map.connect('/{controller}/{id}/{action}')

    return map
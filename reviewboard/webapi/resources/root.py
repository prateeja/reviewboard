from djblets.util.decorators import augment_method_from
from djblets.webapi.resources import RootResource as DjbletsRootResource

from reviewboard.webapi.decorators import (webapi_check_login_required,
                                           webapi_check_local_site)
from reviewboard.webapi.resources import resources


class RootResource(DjbletsRootResource):
    """Links to all the main resources, including URI templates to resources
    anywhere in the tree.

    This should be used as a starting point for any clients that need to access
    any resources in the API. By browsing through the resource tree instead of
    hard-coding paths, your client can remain compatible with any changes in
    the resource URI scheme.
    """
    mimetype_vendor = 'reviewboard.org'

    def __init__(self, *args, **kwargs):
        super(RootResource, self).__init__([
            resources.default_reviewer,
            resources.extension,
            resources.hosting_service_account,
            resources.repository,
            resources.review_group,
            resources.review_request,
            resources.search,
            resources.server_info,
            resources.session,
            resources.user,
            resources.validation,
        ], *args, **kwargs)

    @webapi_check_login_required
    @webapi_check_local_site
    @augment_method_from(DjbletsRootResource)
    def get(self, request, *args, **kwargs):
        """Retrieves the list of top-level resources and templates."""
        pass


root_resource = RootResource()

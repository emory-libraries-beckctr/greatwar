from django.http import HttpResponse, Http404, HttpResponsePermanentRedirect
from django.conf import settings
from django.core.paginator import Paginator, InvalidPage, EmptyPage
from django.shortcuts import render
from django.template import RequestContext
from django.views.decorators.cache import cache_page

from eulfedora.server import Repository
from eulfedora.util import RequestFailed

from greatwar.postcards.models import ImageObject, PostcardCollection
from greatwar.postcards.forms import SearchForm

import logging

# FIXME: set repo default type somewhere in a single place


# search options for finding postcards
# note that pidspace restriction is largely for testing purposes
def postcard_search_opts():
    return {
        'relation': settings.RELATION,
        'pid': '%s:*' % settings.FEDORA_PIDSPACE,
        'type': ImageObject
    }

@cache_page(900)
def summary(request):
    '''Postcard summary/about page with information about the postcards and
    various entry points for accessing them.'''

    # get a list of all the postcards by searching in fedora
    # - used to get total count, and to display a random postcard
    # NOTE: this may be inefficient when all postcards are loaded; consider caching
    repo = Repository()
    postcards = list(repo.find_objects(**postcard_search_opts()))
    count = len(postcards)
    # get categories from fedora collection object
    categories = PostcardCollection.get().interp.content.interp_groups
    return render(request, 'postcards/index.html', {
       'categories': categories,
       'count': count,
       'postcards': postcards,
       })

def browse(request):
    "Browse postcards and display thumbnail images."
    repo = Repository()
    repo.default_object_type = ImageObject
    number_of_results = 15
    context = {}

    search_opts = postcard_search_opts().copy()
    if 'subject' in request.GET:
        context['subject'] = request.GET['subject']
        search_opts['subject'] = request.GET['subject']

    postcards = repo.find_objects(**search_opts)

    postcard_paginator = Paginator(list(postcards), number_of_results)
    try:
        page = int(request.GET.get('page', '1'))
    except ValueError:
        page = 1
    # If page request (9999) is out of range, deliver last page of results.
    try:
        postcard_page = postcard_paginator.page(page)
    except (EmptyPage, InvalidPage):
        postcard_page = postcard_paginator.page(postcard_paginator.num_pages)

    context['postcards_paginated'] = postcard_page

    return render(request, 'postcards/browse.html', context)

def view_postcard(request, pid):
    '''View a single postcard at actual postcard size, with description.'''
    repo = Repository()
    try:
        obj = repo.get_object(pid, type=ImageObject)
        obj.label   # access object label to trigger 404 before we get to the template

        #get ark from object
        ark = filter(lambda ident: 'ark' in ident, obj.dc.content.identifier_list)
        if len(ark) > 0:
            ark =  ark[0]
        else:
            ark = ''

#        #get description from description elements
        description = filter(lambda desc: desc.startswith(settings.POSTCARD_DESCRIPTION_LABEL), obj.dc.content.description_list)
        if len(description) > 0:
            description =  description[0]
            description = description[len(settings.POSTCARD_DESCRIPTION_LABEL):] #trim off label used to identify description
        else:
            description = ''

        #get postcard text from description elements
        postcard_text = filter(lambda desc:  desc.startswith(settings.POSTCARD_FLOATINGTEXT_LABEL), obj.dc.content.description_list)
        if len(postcard_text) > 0:
            postcard_text =  postcard_text[0]
            postcard_text =  postcard_text[len(settings.POSTCARD_FLOATINGTEXT_LABEL):] #trim off label used to identify postcard text

        else:
            postcard_text = ''


        return render(request, 'postcards/view_postcard.html',
            {'card': obj, 'ark': ark, 'description': description, 'postcard_text': postcard_text})
    except RequestFailed:
        raise Http404

def view_postcard_large(request, pid):
    '''View a large image of postcard with title only.'''
    repo = Repository()
    try:
        obj = repo.get_object(pid, type=ImageObject)
        obj.label   # access object label to trigger 404 before we get to the template
        return render(request, 'postcards/view_postcard_large.html',
                      {'card': obj})
    except RequestFailed:
        raise Http404

def postcard_image(request, pid, size):
    '''Lin to postcard image in requested size.

    :param pid: postcard object pid
    :param size: size to return, one of thumbnail, medium, or large
    '''

    # NOTE: formerly this served out actual image content, via
    # fedora dissemination & djatoka
    # Images now use an IIIF image server; adding redirects here
    # for the benefit of search engines or indexes referencing
    # the old urls
    try:
        repo = Repository()
        obj = repo.get_object(pid, type=ImageObject)
        if not obj.exists:
            raise Http404

        if size == 'thumbnail':
            url = obj.thumbnail_url
        elif size == 'medium':
            url = obj.medium_img_url
        elif size == 'large':
            url = obj.large_img_url

        return HttpResponsePermanentRedirect(url)

    except RequestFailed:
        raise Http404


def search(request):
    # rough fedora-based postcard search (borrowed heavily from digital masters)
    form = SearchForm(request.GET)
    response_code = None
    context = {'search': form}
    number_of_results = 5
    if form.is_valid():
        # adding wildcards because fedora has a weird notion of what 'contains' means

        # TODO: terms search can't be used with with field search
        # -- how to allow a keyword search but restrict to postcards?
        #keywords = '%s*' % form.cleaned_data['keyword'].rstrip('*')

        # TEMPORARY: restrict to postcards by pidspace
        search_opts = {'relation': settings.RELATION }
        if 'title' in form.cleaned_data:
            search_opts['title__contains'] = '%s*' % form.cleaned_data['title'].rstrip('*')
        if 'description' in form.cleaned_data:
            search_opts['description__contains'] = '%s*' % form.cleaned_data['description'].rstrip('*')
        try:
            repo = Repository()
            found = repo.find_objects(type=ImageObject, **search_opts)

            search_paginator = Paginator(list(found), number_of_results)
            try:
                page = int(request.GET.get('page', '1'))
            except ValueError:
                page = 1
            # If page request (9999) is out of range, deliver last page of results.
            try:
                search_page = search_paginator.page(page)
            except (EmptyPage, InvalidPage):
                search_page = search_paginator.page(search_paginator.num_pages)


            context['postcards_paginated'] = search_page
            context['title'] = form.cleaned_data['title']
            context['description'] = form.cleaned_data['description']
        except Exception as e:
            logging.debug(e)
            response_code = 500
            context['server_error'] = 'There was an error ' + \
                    'contacting the digital repository. This ' + \
                    'prevented us from completing your search. If ' + \
                    'this problem persists, please alert the ' + \
                    'repository administrator.'

    response = render(request, 'postcards/search.html', context)
    if response_code is not None:
        response.status_code = response_code
    return response

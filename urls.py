from django.contrib import admin
from django.urls import include, path

import root_views

its_urls = [
    path('', include('integration_utils.its_utils.app_gitpull.urls')),
]

urlpatterns = [
    path('email/', include('email_smartprocess.urls')) ,
    path('', root_views.index, name='index'),
    path('its/', include(its_urls)),
    path('admin/', admin.site.urls),
]

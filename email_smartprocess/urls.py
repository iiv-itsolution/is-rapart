from django.urls import path

from . import views

urlpatterns = [
    path("api/thread/<str:thread_id>/", views.thread_api, name="email_thread_api"),
    path("api/owner_thread/", views.owner_thread_api, name="email_owner_thread_api"),
    path("thread/<str:thread_id>/", views.thread_page, name="email_thread_page"),
    path("widget/", views.widget_page, name="email_thread_widget_query"),
    path("widget/<str:thread_id>/", views.thread_widget, name="email_thread_widget"),
    path("ui/<str:thread_id>/", views.thread_ui, name="email_thread_ui"),
    path("bitrix/widget/activity/", views.bitrix_activity_widget, name="email_bitrix_activity_widget"),
    path("bitrix/widgets/email_tab/", views.bitrix_email_tab, name="email_bitrix_email_tab"),
    path("thread/<str:thread_id>/send/", views.thread_send, name="email_thread_send"),
    path("demo/create_activity/", views.demo_create_activity, name="email_demo_create_activity"),
]
